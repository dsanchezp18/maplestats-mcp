"""Client for the Licensed Natural Health Products Database (LNHPD) API.

Checked live 2026-10-03 (see also ../api.py and constants.py):

1. `productlicence?id=` takes the NPN (licence number, e.g. 80000035),
   not the LNHPD id; it answers one row per brand name of the licence
   (flag_primary_name 1 for the main one) and [] for an unknown NPN. The
   other endpoints take the `lnhpd_id` from that row.
2. medicinalingredient, productpurpose and productrisk wrap rows as
   {"metadata": {...}, "data": [...]}; the others answer a bare list.
3. With lang=fr the API translates labels (submission type "(M) non
   traditionnelle", route "Orale", population "Adultes", risk type
   "Contre-indications") but purpose and risk statements stay in the
   language the company filed them in.
4. There is no name or company filter, so searching means reading the
   whole licence table (60 s before its first byte, 148 MB). It is read
   once a day as a stream into a compact index: one tab-separated line
   per product name, about 37 MB of UTF-8, searched with a regular
   expression rather than kept as 307,002 Python objects.
5. flag_product_status is 1 for an active licence; 0, 2, 3 and 4 are the
   non-active states (0 for most), which the API does not name.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from maplestats_mcp.modules.health_products import api
from maplestats_mcp.modules.health_products.lnhpd import constants
from maplestats_mcp.modules.health_products.lnhpd.schemas import (
    NhpDose,
    NhpMedicinalIngredient,
    NhpProductDetail,
    NhpProductName,
    NhpRisk,
    NhpSearchResult,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.errors import InvalidInput, NotFound

_NPN = re.compile(r"^\d{1,8}$")
_CLEAN = str.maketrans({"\t": " ", "\n": " ", "\r": " "})
# Index line fields, in order.
_FIELDS = (
    "npn",
    "lnhpd_id",
    "product_name",
    "company_name",
    "dosage_form",
    "status",
    "licence_date",
    "revised_date",
    "primary",
)


def _cell(value: Any) -> str:
    return "" if value is None else str(value).translate(_CLEAN).strip()


def index_line(row: dict[str, Any]) -> str:
    return "\t".join(
        _cell(row.get(key))
        for key in (
            "licence_number",
            "lnhpd_id",
            "product_name",
            "company_name",
            "dosage_form",
            "flag_product_status",
            "licence_date",
            "revised_date",
            "flag_primary_name",
        )
    )


async def _index() -> tuple[bytes, bool]:
    async def fetch() -> bytes:
        lines = [
            index_line(row)
            async for row in api.stream_objects(constants.PATH_LICENCE, lang="en")
            if row.get("licence_number")
        ]
        if not lines:
            raise NotFound("The LNHPD licence table came back empty.")
        return "\n".join(lines).encode("utf-8")

    return await cached_fetch("hc_lnhpd:index", constants.INDEX_TTL_SECONDS, fetch)


def _int(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        return 0


def _name(fields: list[str]) -> NhpProductName:
    row = dict(zip(_FIELDS, fields, strict=False))
    status = _int(row.get("status", ""))
    return NhpProductName(
        npn=row["npn"],
        lnhpd_id=_int(row.get("lnhpd_id", "")),
        product_name=row.get("product_name", ""),
        primary_name=row.get("primary") == "1",
        company_name=row.get("company_name") or None,
        dosage_form=row.get("dosage_form") or None,
        active=status == 1,
        status_code=status,
        licence_date=row.get("licence_date") or None,
        revised_date=row.get("revised_date") or None,
    )


def search_index(
    blob: bytes, *, query: str, company: str, active_only: bool
) -> list[NhpProductName]:
    """Product names whose name or NPN contains `query` and company contains `company`."""
    scan = query or company
    pattern = re.compile(re.escape(scan.encode("utf-8")), re.IGNORECASE)
    q, c = query.casefold(), company.casefold()
    seen: set[int] = set()
    found: list[NhpProductName] = []
    for match in pattern.finditer(blob):
        start = blob.rfind(b"\n", 0, match.start()) + 1
        if start in seen:
            continue
        seen.add(start)
        end = blob.find(b"\n", match.end())
        fields = blob[start : end if end >= 0 else len(blob)].decode("utf-8").split("\t")
        if len(fields) != len(_FIELDS):
            continue
        npn, name, holder = fields[0], fields[2], fields[3]
        if q and q not in name.casefold() and not npn.startswith(query):
            continue
        if c and c not in holder.casefold():
            continue
        if active_only and fields[5] != "1":
            continue
        found.append(_name(fields))
    return found


async def search_products(
    query: str = "",
    *,
    company: str = "",
    active_only: bool = True,
    limit: int = constants.LIMIT_DEFAULT,
    lang: str = "en",
) -> NhpSearchResult:
    query, company = query.strip(), company.strip()
    if len(query) < 3 and len(company) < 3:
        api.fail(
            InvalidInput,
            "Give at least 3 characters of a product name, NPN or company.",
            "donnez au moins 3 caractères d'un nom de produit, d'un NPN ou d'une entreprise.",
            lang,
        )
    if not 1 <= limit <= constants.LIMIT_MAX:
        api.fail(
            InvalidInput,
            f"limit must be between 1 and {constants.LIMIT_MAX}.",
            f"limit doit être compris entre 1 et {constants.LIMIT_MAX}.",
            lang,
        )
    # Names and companies are stored as filed; the index has no labels to translate.
    blob, cached = await api.in_lang(lang, _index())
    found = search_index(blob, query=query, company=company, active_only=active_only)
    found.sort(key=lambda p: (not p.active, not p.primary_name, p.product_name.casefold()))
    page = found[:limit]
    what = " and ".join(
        part
        for part in (
            f"name or NPN contains '{query}'" if query else "",
            f"company contains '{company}'" if company else "",
        )
        if part
    )
    what_fr = " et ".join(
        part
        for part in (
            f"le nom ou le NPN contient '{query}'" if query else "",
            f"l'entreprise contient '{company}'" if company else "",
        )
        if part
    )
    return NhpSearchResult(
        products=page,
        returned_count=len(page),
        total_matched=len(found),
        licences_matched=len({p.npn for p in found}),
        provenance=api.provenance(
            api.url_for(constants.PATH_LICENCE),
            cached=cached,
            schema="NhpSearchResult",
            freshness=constants.FRESHNESS,
            coverage=(
                f"{len(page)} of {len(found)} product names where {what}"
                + (", active licences only" if active_only else "")
            ),
            limits=(
                "the whole licence table is read once a day (about a minute the first time); "
                "ingredients cannot be searched, only read per licence"
            ),
            lang=lang,
            freshness_fr=constants.FRESHNESS_FR,
            coverage_fr=(
                f"{len(page)} noms de produits sur {len(found)} où {what_fr}"
                + (", licences actives seulement" if active_only else "")
            ),
            limits_fr=(
                "la table complète des licences est lue une fois par jour (environ une minute "
                "la première fois) ; les ingrédients ne se cherchent pas, ils se lisent par "
                "licence. Les noms de produits et d'entreprises sont ceux déposés."
            ),
        ),
    )


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number or None


def _join(*parts: Any) -> str | None:
    out = " ".join(str(p).strip() for p in parts if p not in (None, "", 0, 0.0) and str(p).strip())
    return out or None


def _fmt(value: Any) -> str | None:
    number = _num(value)
    if number is None:
        return None
    return f"{number:g}"


def _range(value: Any, low: Any, high: Any) -> str | None:
    if _num(low) and _num(high):
        return f"{_fmt(low)}-{_fmt(high)}"
    return _fmt(value)


async def get_product(npn: str, *, lang: str = "en") -> NhpProductDetail:
    cleaned = npn.strip().upper().removeprefix("NPN").removeprefix("DIN-HM").strip(" -:")
    if not _NPN.match(cleaned):
        api.fail(
            InvalidInput,
            f"'{npn}' is not an NPN: give the 8-digit licence number, e.g. 80000035.",
            f"'{npn}' n'est pas un NPN : donnez le numéro de licence à 8 chiffres, "
            "p. ex. 80000035.",
            lang,
        )
    cleaned = cleaned.zfill(8)

    async def fetch() -> NhpProductDetail:
        rows = api.as_list(await api.get_json(constants.PATH_LICENCE, {"id": cleaned}, lang=lang))
        rows = [r for r in rows if r.get("licence_number")]
        if not rows:
            api.fail(
                NotFound,
                f"No licensed natural health product has NPN {cleaned}.",
                f"aucun produit de santé naturel homologué n'a le NPN {cleaned}.",
                lang,
            )
        lnhpd_id = int(rows[0]["lnhpd_id"])
        by_id = {"id": lnhpd_id}
        medicinal, non_medicinal, purposes, risks, routes, doses = await asyncio.gather(
            api.get_json(constants.PATH_MEDICINAL, by_id, lang=lang, missing_ok=True),
            api.get_json(constants.PATH_NON_MEDICINAL, by_id, lang=lang, missing_ok=True),
            api.get_json(constants.PATH_PURPOSE, by_id, lang=lang, missing_ok=True),
            api.get_json(constants.PATH_RISK, by_id, lang=lang, missing_ok=True),
            api.get_json(constants.PATH_ROUTE, by_id, lang=lang, missing_ok=True),
            api.get_json(constants.PATH_DOSE, by_id, lang=lang, missing_ok=True),
        )
        names = [_name(index_line(r).split("\t")) for r in rows]
        names.sort(key=lambda n: not n.primary_name)
        first = rows[0]
        attested = first.get("flag_attested_monograph")
        return NhpProductDetail(
            npn=cleaned,
            lnhpd_id=lnhpd_id,
            names=names,
            submission_type=api.text(first.get("sub_submission_type_desc")),
            attested_monograph=None if attested is None else attested == 1,
            medicinal_ingredients=[
                NhpMedicinalIngredient(
                    name=api.text(r.get("ingredient_name")) or "",
                    quantity=_num(r.get("quantity")),
                    quantity_unit=api.text(r.get("quantity_unit_of_measure")),
                    potency=_join(
                        _fmt(r.get("potency_amount")),
                        r.get("potency_unit_of_measure"),
                        r.get("potency_constituent"),
                    ),
                    extract_ratio=(
                        f"{r['ratio_numerator']}:{r['ratio_denominator']}"
                        if api.text(r.get("ratio_numerator"))
                        and api.text(r.get("ratio_denominator"))
                        else None
                    ),
                    dried_herb_equivalent=_join(
                        r.get("dried_herb_equivalent"), r.get("dhe_unit_of_measure")
                    ),
                    source_material=api.text(r.get("source_material")),
                )
                for r in api.as_list(medicinal)
                if api.text(r.get("ingredient_name"))
            ],
            non_medicinal_ingredients=[
                name
                for r in api.as_list(non_medicinal)
                if (name := api.text(r.get("ingredient_name")))
            ],
            routes=[
                name for r in api.as_list(routes) if (name := api.text(r.get("route_type_desc")))
            ],
            doses=[
                NhpDose(
                    population=api.text(r.get("population_type_desc")),
                    age=_join(
                        _range(r.get("age"), r.get("age_minimum"), r.get("age_maximum")),
                        r.get("uom_type_desc_age"),
                    ),
                    dose=_join(
                        _range(
                            r.get("quantity_dose"),
                            r.get("quantity_dose_minimum"),
                            r.get("quantity_dose_maximum"),
                        ),
                        r.get("uom_type_desc_quantity_dose"),
                    ),
                    frequency=_join(
                        _range(
                            r.get("frequency"),
                            r.get("frequency_minimum"),
                            r.get("frequency_maximum"),
                        ),
                        r.get("uom_type_desc_frequency"),
                    ),
                )
                for r in api.as_list(doses)
            ],
            purposes=[text for r in api.as_list(purposes) if (text := api.text(r.get("purpose")))],
            risks=[
                NhpRisk(
                    risk_type=api.text(r.get("risk_type_desc")),
                    sub_type=api.text(r.get("sub_risk_type_desc")),
                    text=text,
                )
                for r in api.as_list(risks)
                if (text := api.text(r.get("risk_text")))
            ],
            lnhpd_page=constants.PRODUCT_PAGE.format(npn=cleaned),
            provenance=api.provenance(
                f"{api.url_for(constants.PATH_LICENCE)}?id={cleaned}&lang={lang}&type=json",
                cached=False,
                schema="NhpProductDetail",
                freshness=constants.FRESHNESS,
                lang=lang,
                freshness_fr=constants.FRESHNESS_FR,
                limits_fr="Les noms, les fins et les mises en garde sont ceux que l'entreprise "
                "a déposés, parfois en anglais seulement.",
            ),
        )

    detail, cached = await api.in_lang(
        lang,
        cached_fetch(f"hc_lnhpd:product:{cleaned}:{lang}", constants.LOOKUP_TTL_SECONDS, fetch),
    )
    if cached:
        detail = detail.model_copy(
            update={"provenance": detail.provenance.model_copy(update={"cached": True})}
        )
    return detail
