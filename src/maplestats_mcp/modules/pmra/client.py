"""Client for the Pesticide Product Information Database CSV extracts.

Checked live 2026-10-03 against /api/extract/{product,ingredient,mrl}
and /api/extract/product/{registration number}, with and without ?lang=fr:

1. Every extract is Windows-1252 (the Content-Type says so; "É" is 0xC9),
   CRLF, standard CSV quoting. French files have French headers and
   French labels ("Homologation complète", "En cours", "0,018" in the MRL
   values) in the same column order, so columns are read by position
   after checking the column count.
2. Quoted cells contain line breaks ("GLYPHOSATE (N.M.) (PRÉSENT SOUS
   FORME DE\nSEL ..."), and some French names start with one; whitespace
   is collapsed.
3. Active ingredients are ";"-separated. 99.8% of current products' names
   match an ingredient extract row exactly (18 of 10,054 did not that
   day). Sites of use and pests are ";"-separated and cut at exactly
   2,000 characters in 262 products.
4. The product extract has 21,795 rows: 7,791 current, the rest
   historical, including 586 "NEVER REGISTERED" placeholders and rows
   left by a 1999 database migration.
5. MRL chemical names are common names ("Glyphosate") while products list
   salts ("GLYPHOSATE (PRESENT AS POTASSIUM SALT)"), so the join drops the
   parenthesis and compares case-folded names.
6. /product/{number} returns the one-row CSV, or HTTP 404 with a JSON
   body {"clientMessage":"Record not found"} for an unknown number.
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, NoReturn

import httpx

from maplestats_mcp.modules.pmra import constants
from maplestats_mcp.modules.pmra.schemas import (
    ActiveIngredient,
    PesticideProduct,
    PesticideProductDetail,
    PesticideProductList,
    ResidueLimit,
    ResidueLimitList,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance, raise_typed
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import get_raw
from maplestats_mcp.shared.i18n import french_spacing
from maplestats_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)
_REGISTRATION = re.compile(r"^\d{1,8}$")
_DIGITS_EN = "pmra: registration_number is digits only, e.g. 31153."
_DIGITS_FR = "pmra : registration_number ne contient que des chiffres, p. ex. 31153."


def _raise(exc_cls: type[ValueError], en: str, fr: str, lang: str) -> NoReturn:
    """English as before; French in the typed template ("Entrée invalide : ...")."""
    if lang == "fr":
        raise_typed(exc_cls, fr, "fr")
    raise exc_cls(en)


def _text(en: str, fr: str, lang: str) -> str:
    """The English text, or the French one with no-break spaces."""
    return french_spacing(fr) if lang == "fr" else en


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return " ".join("".join(c for c in decomposed if not unicodedata.combining(c)).split())


def _clean(text: str) -> str:
    return " ".join(text.split())


def _split(text: str) -> list[str]:
    return [part for part in (_clean(p) for p in text.split(";")) if part]


def _url(kind: str, lang: str, key: str = "") -> str:
    url = constants.EXTRACT_URL + kind + (f"/{key}" if key else "")
    return url + "?lang=fr" if lang == "fr" else url


async def _get(url: str, lang: str = "en") -> bytes:
    await _LIMITER.acquire()
    try:
        response = await get_raw(url, timeout=180.0)
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status == 404:
            _raise(NotFound, f"pmra: no record at {url}.", f"pmra : aucune fiche à {url}.", lang)
        _raise(
            UpstreamError,
            f"pmra: {url} returned HTTP {status}.",
            f"pmra : {url} a renvoyé HTTP {status}.",
            lang,
        )
    except httpx.HTTPError:
        _raise(
            UpstreamUnavailable,
            f"pmra: {url} did not respond in time.",
            f"pmra : {url} n'a pas répondu à temps.",
            lang,
        )
    if len(response.content) > constants.MAX_EXTRACT_BYTES:
        _raise(
            UpstreamError,
            f"pmra: {url} is much larger than expected; it changed.",
            f"pmra : {url} est beaucoup plus volumineux que prévu ; il a changé.",
            lang,
        )
    return response.content


def parse_extract(body: bytes, columns: int, what: str, lang: str = "en") -> list[list[str]]:
    """Rows of an extract (header dropped), cells whitespace-collapsed."""
    text = body.decode("cp1252", errors="replace").lstrip("﻿")
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or len(rows[0]) != columns:
        found = len(rows[0]) if rows else 0
        _raise(
            UpstreamError,
            f"pmra: the {what} extract has {found} columns, expected "
            f"{columns}; its layout changed.",
            f"pmra : l'extrait {what} a {found} colonnes au lieu de {columns} ; sa structure "
            "a changé.",
            lang,
        )
    return [[_clean(cell) for cell in row] for row in rows[1:] if len(row) == columns]


# ---------------------------------------------------------------- products


@dataclass(frozen=True)
class _Product:
    cells: tuple[str, ...]
    text: str  # folded names and registration number
    ingredients: str  # folded English and French active ingredients


def _is_current(value: str) -> bool:
    return _fold(value) in ("current", "en cours")


def to_product(cells: tuple[str, ...] | list[str], lang: str) -> PesticideProduct:
    name_en, name_fr = cells[1], cells[2] or None
    return PesticideProduct(
        registration_number=cells[0],
        product_name=(name_fr or name_en) if lang == "fr" else name_en,
        product_name_en=name_en,
        product_name_fr=name_fr,
        registration_status=cells[3] or None,
        current=_is_current(cells[15]),
        expiry_date=cells[4] or None,
        date_first_registered=cells[6] or None,
        marketing_type=cells[5] or None,
        product_type=cells[10] or None,
        registrant=cells[11] or None,
        active_ingredients=_split(cells[8]),
        use_site_categories=cells[12] or None,
    )


async def _products(lang: str) -> tuple[list[_Product], bool]:
    async def fetch() -> list[_Product]:
        rows = parse_extract(
            await _get(_url("product", lang), lang), constants.PRODUCT_COLUMNS, "product", lang
        )
        if len(rows) < 1000:
            _raise(
                UpstreamError,
                f"pmra: the product extract has only {len(rows)} rows.",
                f"pmra : l'extrait des produits n'a que {len(rows)} lignes.",
                lang,
            )
        return [
            _Product(
                cells=tuple(r),
                text=_fold(f"{r[0]} {r[1]} {r[2]}"),
                ingredients=_fold(f"{r[8]} {r[9]}"),
            )
            for r in rows
        ]

    return await cached_fetch(f"pmra:products:{lang}", constants.EXTRACT_TTL_SECONDS, fetch)


def _provenance(url: str, cached: bool, schema: str, lang: str, coverage: str | None = None) -> Any:
    return make_provenance(
        source=constants.RATE_LIMIT_SOURCE,
        url=url,
        cached=cached,
        schema_name=f"pmra.{schema}",
        freshness=_text(
            "daily (the database refreshes overnight, Eastern time)",
            "quotidienne (la base de données se met à jour la nuit, heure de l'Est)",
            lang,
        ),
        coverage=coverage,
        licence=_text(constants.LICENCE, constants.LICENCE_FR, lang),
        lang=lang,
    )


async def search_products(
    query: str = "",
    *,
    registration_number: str = "",
    active_ingredient: str = "",
    registrant: str = "",
    product_type: str = "",
    status: str = "current",
    limit: int = constants.SEARCH_DEFAULT_LIMIT,
    lang: str = "en",
) -> PesticideProductList:
    """Products matching every filter given (words are matched without accents or case)."""
    if not 1 <= limit <= constants.SEARCH_MAX_LIMIT:
        _raise(
            InvalidInput,
            f"pmra: limit must be 1 to {constants.SEARCH_MAX_LIMIT}.",
            f"pmra : limit doit être compris entre 1 et {constants.SEARCH_MAX_LIMIT}.",
            lang,
        )
    if status not in ("current", "historical", "all"):
        _raise(
            InvalidInput,
            "pmra: status must be current, historical or all.",
            "pmra : status doit valoir current, historical ou all.",
            lang,
        )
    number = registration_number.strip()
    if number and not _REGISTRATION.match(number):
        _raise(InvalidInput, _DIGITS_EN, _DIGITS_FR, lang)
    if not any(s.strip() for s in (query, number, active_ingredient, registrant, product_type)):
        _raise(
            InvalidInput,
            "pmra: pass a query, registration_number, active_ingredient, registrant or "
            "product_type.",
            "pmra : donnez query, registration_number, active_ingredient, registrant ou "
            "product_type.",
            lang,
        )
    products, cached = await _products(lang)
    words = _fold(query).split()
    ingredient_words = _fold(active_ingredient).split()
    wanted_registrant = _fold(registrant)
    wanted_type = _fold(product_type)
    matched = [
        p
        for p in products
        if (not number or p.cells[0] == number)
        and all(w in p.text for w in words)
        and all(w in p.ingredients for w in ingredient_words)
        and (not wanted_registrant or wanted_registrant in _fold(p.cells[11]))
        and (not wanted_type or wanted_type in _fold(p.cells[10]))
        and (status == "all" or (status == "current") == _is_current(p.cells[15]) or bool(number))
    ]
    counts: dict[str, int] = {}
    for p in matched:
        key = p.cells[10] or "-"
        counts[key] = counts.get(key, 0) + 1
    # Current products first, then by name.
    matched.sort(key=lambda p: (not _is_current(p.cells[15]), p.cells[1]))
    shown = [to_product(p.cells, lang) for p in matched[:limit]]
    return PesticideProductList(
        products=shown,
        returned_count=len(shown),
        total_matched=len(matched),
        by_product_type=dict(sorted(counts.items(), key=lambda kv: -kv[1])[:15]),
        provenance=_provenance(
            _url("product", lang),
            cached,
            "PesticideProductList",
            lang,
            _text(
                f"{len(products):,} products in the extract; status filter '{status}'",
                f"{len(products):,} produits dans l'extrait ; filtre de statut '{status}'".replace(
                    ",", "\u00a0"
                ),
                lang,
            ),
        ),
    )


# ------------------------------------------------------ ingredients and MRLs


async def _ingredients(lang: str = "en") -> tuple[dict[str, list[str]], bool]:
    async def fetch() -> dict[str, list[str]]:
        rows = parse_extract(
            await _get(_url("ingredient", "en"), lang),
            constants.INGREDIENT_COLUMNS,
            "ingredient",
            lang,
        )
        return {r[0]: r for r in rows if r[0]}

    return await cached_fetch("pmra:ingredients", constants.EXTRACT_TTL_SECONDS, fetch)


async def _mrls(lang: str, msg_lang: str | None = None) -> tuple[list[list[str]], bool]:
    """The MRL extract in `lang`; `msg_lang` (default `lang`) words any error."""
    say = msg_lang or lang

    async def fetch() -> list[list[str]]:
        rows = parse_extract(await _get(_url("mrl", lang), say), constants.MRL_COLUMNS, "mrl", say)
        if len(rows) < 1000:
            _raise(
                UpstreamError,
                f"pmra: the MRL extract has only {len(rows)} rows.",
                f"pmra : l'extrait des LMR n'a que {len(rows)} lignes.",
                say,
            )
        return rows

    return await cached_fetch(f"pmra:mrl:{lang}", constants.EXTRACT_TTL_SECONDS, fetch)


def base_chemical(ingredient: str) -> str:
    """'GLYPHOSATE (PRESENT AS POTASSIUM SALT)' -> 'glyphosate', the MRL list's key."""
    return _fold(re.sub(r"\s*\(.*$", "", ingredient))


async def get_product(registration_number: str, *, lang: str = "en") -> PesticideProductDetail:
    """One product, fresh from the registry, with its ingredients joined and MRLs counted."""
    number = registration_number.strip()
    if not _REGISTRATION.match(number):
        _raise(InvalidInput, _DIGITS_EN, _DIGITS_FR, lang)
    url = _url("product", lang, number)
    rows = parse_extract(await _get(url, lang), constants.PRODUCT_COLUMNS, "product", lang)
    if not rows:
        _raise(
            NotFound,
            f"pmra: no product with registration number {number}.",
            f"pmra : aucun produit avec le numéro d'homologation {number}.",
            lang,
        )
    cells = rows[0]
    ingredients, ingredients_cached = await _ingredients(lang)
    mrls, mrls_cached = await _mrls("en", lang)
    mrl_counts: dict[str, int] = {}
    mrl_names: dict[str, str] = {}
    for row in mrls:
        key = _fold(row[0])
        mrl_counts[key] = mrl_counts.get(key, 0) + 1
        mrl_names.setdefault(key, row[0])
    joined: list[ActiveIngredient] = []
    # The English list is the join key in both languages (French files keep it).
    for name in _split(cells[8]):
        record = ingredients.get(name)
        base = base_chemical(name)
        joined.append(
            ActiveIngredient(
                name=name,
                name_fr=(record[1] or None) if record else None,
                cas_number=(record[3] or None) if record else None,
                under_reevaluation=(record[2].upper() in ("YES", "OUI")) if record else None,
                mrl_chemical=mrl_names.get(base),
                mrl_count=mrl_counts.get(base, 0),
            )
        )
    return PesticideProductDetail(
        product=to_product(cells, lang),
        ingredients=joined,
        sites_of_use=_split(cells[13]),
        pests=_split(cells[14]),
        lists_truncated=max(len(cells[13]), len(cells[14])) >= constants.TRUNCATED_AT,
        provenance=_provenance(
            url, ingredients_cached and mrls_cached, "PesticideProductDetail", lang
        ),
    )


def _ppm(text: str) -> float | None:
    try:
        return float(text.replace(",", ".").replace(" ", ""))
    except ValueError:
        return None


async def get_residue_limits(
    chemical: str = "",
    *,
    commodity: str = "",
    limit: int = constants.MRL_DEFAULT_LIMIT,
    lang: str = "en",
) -> ResidueLimitList:
    """Maximum residue limits for a pesticide, a food commodity, or both."""
    if not 1 <= limit <= constants.MRL_MAX_LIMIT:
        _raise(
            InvalidInput,
            f"pmra: limit must be 1 to {constants.MRL_MAX_LIMIT}.",
            f"pmra : limit doit être compris entre 1 et {constants.MRL_MAX_LIMIT}.",
            lang,
        )
    if not chemical.strip() and not commodity.strip():
        _raise(
            InvalidInput,
            "pmra: pass a chemical (e.g. glyphosate), a commodity, or both.",
            "pmra : donnez une substance chimique (p. ex. glyphosate), une denrée, ou les deux.",
            lang,
        )
    rows, cached = await _mrls(lang)
    wanted_chemical = _fold(chemical)
    commodity_words = _fold(commodity).split()
    exact = {r[0] for r in rows if _fold(r[0]) == wanted_chemical}
    matched = [
        r
        for r in rows
        if (not wanted_chemical or (r[0] in exact if exact else wanted_chemical in _fold(r[0])))
        and all(w in _fold(r[1]) for w in commodity_words)
    ]
    shown = [
        ResidueLimit(
            chemical=r[0],
            commodity=r[1],
            mrl_ppm=_ppm(r[2]),
            comments=r[3] or None,
            established_via=r[4] or None,
        )
        for r in matched[:limit]
    ]
    return ResidueLimitList(
        limits=shown,
        returned_count=len(shown),
        total_matched=len(matched),
        chemicals=sorted({r[0] for r in matched})[:50],
        provenance=_provenance(
            _url("mrl", lang),
            cached,
            "ResidueLimitList",
            lang,
            _text(f"{len(rows):,} MRLs", f"{len(rows):,} LMR".replace(",", "\u00a0"), lang),
        ),
    )
