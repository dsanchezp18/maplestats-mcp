"""Client for CRA's annual "List of charities" DataStore resources on open.canada.ca.

Confirmed live 2026-10-10:
- `package_search` (organization cra-arc, title "<year> List of charities") gives one
  package per year, newest 2024 that day; its resources are DataStore-active.
- The Identification resource (~84,000 rows) accepts full-text `q` (stemmed, matches any
  text column such as city, so "food bank toronto" works) and exact `filters` on BN,
  Province and Designation. Over 100,000 rows `q` is rejected with HTTP 409, which is why
  the directors table (~569,000 rows) is read with an exact BN filter only.
- `Account Name` carries literal U+FFFD characters where the source lost accents; `Legal
  Name` is cleaner.
- A BN in the files is 15 characters: nine digits, "RR", four digits.
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any, NoReturn

from maplestats_mcp.modules.cra_charities import constants
from maplestats_mcp.modules.cra_charities.schemas import (
    CharityDetail,
    CharityDirector,
    CharityDirectors,
    CharityProgram,
    CharityRecord,
    CharitySearchResult,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.ckan import CkanConfig, action
from maplestats_mcp.shared.envelope import make_provenance, raise_localized
from maplestats_mcp.shared.errors import InvalidInput, NotFound
from maplestats_mcp.shared.i18n import pick
from maplestats_mcp.shared.json_utils import list_or_empty
from maplestats_mcp.shared.licences import OGL_CANADA
from maplestats_mcp.shared.models import Provenance

_CONFIG = CkanConfig(
    source=constants.RATE_LIMIT_SOURCE,
    base_url=constants.BASE_URL,
    rate_limit_per_second=constants.RATE_LIMIT_PER_SECOND,
    rate_limit_capacity=constants.RATE_LIMIT_CAPACITY,
)
_TITLE = re.compile(constants.DATASET_TITLE_PATTERN)
_BN_FULL = re.compile(r"^\d{9}RR\d{4}$")
_PROVINCE = re.compile(r"^[A-Z]{2}$")


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _date(value: Any) -> date | None:
    text = _text(value)
    if text is None:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _compact(raw: str) -> str:
    return re.sub(r"[\s\-]", "", raw).upper()


def _is_bn(raw: str) -> bool:
    compact = _compact(raw)
    return bool(re.fullmatch(r"\d{9}", compact) or _BN_FULL.match(compact))


def normalize_bn(raw: str, lang: str = "en") -> str:
    """A 9-digit BN or a 15-character BN (spaces, dashes and case ignored) as in the files."""
    cleaned = _compact(raw)
    if re.fullmatch(r"\d{9}", cleaned):
        return cleaned + "RR0001"
    if _BN_FULL.match(cleaned):
        return cleaned
    _bad_bn(raw, lang)


def _bad_bn(raw: str, lang: str) -> NoReturn:
    raise_localized(
        InvalidInput,
        f"business_number must be 9 digits or 15 characters like 119219814RR0001, got {raw!r}.",
        f"business_number doit compter 9 chiffres ou 15 caractères comme 119219814RR0001 "
        f"(reçu : {raw!r}).",
        lang,
    )


async def _list_resources(lang: str) -> tuple[int, str, dict[str, str]]:
    """(year, package id, DataStore resource ids by name) for the newest list."""

    async def fetch() -> Any:
        return await action(
            _CONFIG,
            "package_search",
            {
                "q": "List of charities",
                "fq": f"organization:{constants.ORGANIZATION}",
                "rows": 100,
            },
            lang=lang,
        )

    result, _ = await cached_fetch(
        "cra-charities:discovery", constants.CACHE_TTL_DISCOVERY_SECONDS, fetch
    )
    best: tuple[int, dict[str, Any]] | None = None
    for package in list_or_empty(result, "results"):
        title = package.get("title")
        match = _TITLE.match(title) if isinstance(title, str) else None
        if match and (best is None or int(match.group(1)) > best[0]):
            best = (int(match.group(1)), package)
    if best is not None:
        year, package = best
        by_name: dict[str, str] = {}
        for res in list_or_empty(package, "resources"):
            name = res.get("name")
            if isinstance(name, str) and res.get("datastore_active"):
                by_name.setdefault(name.strip(), res["id"])
        needed = (constants.RESOURCE_IDENTIFICATION, constants.RESOURCE_GENERAL)
        if all(name in by_name for name in needed):
            return year, package["id"], by_name
    return (
        constants.FALLBACK_YEAR,
        constants.FALLBACK_PACKAGE_ID,
        dict(constants.FALLBACK_RESOURCES),
    )


async def _datastore(
    resource_id: str, params: dict[str, Any], lang: str
) -> tuple[dict[str, Any], bool]:
    query = {"resource_id": resource_id, **params}

    async def fetch() -> Any:
        return await action(_CONFIG, "datastore_search", query, lang=lang)

    return await cached_fetch(
        f"cra-charities:ds:{json.dumps(query, sort_keys=True)}",
        constants.CACHE_TTL_SECONDS,
        fetch,
    )


def _record(row: dict[str, Any], lang: str) -> CharityRecord:
    code = _text(row.get("Designation"))
    labels = constants.DESIGNATIONS.get(code or "")
    return CharityRecord(
        business_number=_text(row.get("BN")) or "",
        legal_name=_text(row.get("Legal Name")),
        account_name=_text(row.get("Account Name")),
        designation_code=code,
        designation=pick(lang, labels[0], labels[1]) if labels else None,
        category_code=_text(row.get("Category")),
        sub_category_code=_text(row.get("Sub Category")),
        address_line_1=_text(row.get("Address Line 1")),
        address_line_2=_text(row.get("Address Line 2")),
        city=_text(row.get("City")),
        province=_text(row.get("Province")),
        postal_code=_text(row.get("Postal Code")),
        country=_text(row.get("Country")),
    )


def _limits(lang: str) -> str:
    return pick(
        lang,
        "Latest published annual list, not CRA's live Charities Listing: a recent registration "
        "or revocation may be missing, and absence does not prove a charity is unregistered. "
        "Account Name can contain replacement characters where the source lost accents; "
        "Legal Name is cleaner. Category and sub-category are CRA codes (see the dataset's "
        "Codes Lists file).",
        "Dernière liste annuelle publiée, et non la Liste des organismes de bienfaisance en "
        "direct de l'ARC : une inscription ou une révocation récente peut manquer, et "
        "l'absence d'un organisme ne prouve pas qu'il n'est pas enregistré. Le nom du "
        "compte peut contenir des caractères de remplacement là où la source a perdu les "
        "accents ; le nom légal est plus fiable. Catégorie et sous-catégorie sont des codes "
        "de l'ARC (voir le fichier des listes de codes du jeu de données).",
    )


def _provenance(year: int, resource: str, cached: bool, schema: str, lang: str) -> Provenance:
    return make_provenance(
        source=constants.RATE_LIMIT_SOURCE,
        url=f"{constants.BASE_URL}datastore_search?resource_id={resource}",
        cached=cached,
        schema_name=f"cra_charities.{schema}",
        coverage=pick(
            lang,
            f"{year} List of charities (CRA T3010 data)",
            f"Liste des organismes de bienfaisance {year} (données T3010 de l'ARC)",
        ),
        limits=_limits(lang),
        licence=OGL_CANADA,
        lang=lang,
    )


async def search_charities(
    query: str | None = None,
    province: str | None = None,
    designation: str | None = None,
    limit: int = constants.LIMIT_DEFAULT,
    offset: int = 0,
    lang: str = "en",
) -> CharitySearchResult:
    """Search the Identification table by words (name, city) and exact province/designation."""
    text = (query or "").strip()
    prov = province.strip().upper() if province and province.strip() else None
    desig = designation.strip().upper() if designation and designation.strip() else None
    if not text and not prov and not desig:
        raise_localized(
            InvalidInput,
            "Give a query, a province or a designation.",
            "Indiquez une requête, une province ou une désignation.",
            lang,
        )
    if prov and not _PROVINCE.match(prov):
        raise_localized(
            InvalidInput,
            f"province must be a two-letter code such as ON or QC, got {province!r}.",
            f"province doit être un code de deux lettres comme ON ou QC (reçu : {province!r}).",
            lang,
        )
    if desig and desig not in constants.DESIGNATIONS:
        raise_localized(
            InvalidInput,
            f"designation must be A (public foundation), B (private foundation) or "
            f"C (charitable organization), got {designation!r}.",
            f"designation doit être A (fondation publique), B (fondation privée) ou "
            f"C (organisme de bienfaisance) (reçu : {designation!r}).",
            lang,
        )
    if limit < 1 or limit > constants.LIMIT_MAX:
        raise_localized(
            InvalidInput,
            f"limit must be between 1 and {constants.LIMIT_MAX}, got {limit}.",
            f"limit doit être entre 1 et {constants.LIMIT_MAX} (reçu : {limit}).",
            lang,
        )
    if offset < 0:
        raise_localized(
            InvalidInput, f"offset must be >= 0, got {offset}.", "offset doit être >= 0.", lang
        )
    year, _, resources = await _list_resources(lang)
    resource = resources[constants.RESOURCE_IDENTIFICATION]
    filters: dict[str, str] = {}
    if prov:
        filters["Province"] = prov
    if desig:
        filters["Designation"] = desig
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    # A business number typed as the query is an exact lookup, not a word search.
    if text and _is_bn(text):
        filters["BN"] = normalize_bn(text, lang)
    elif text:
        params["q"] = text
    if filters:
        params["filters"] = json.dumps(filters)
    if not text:
        params["sort"] = "Legal Name asc"
    result, cached = await _datastore(resource, params, lang)
    rows = list_or_empty(result, "records")
    return CharitySearchResult(
        list_year=year,
        query=text or None,
        province=prov,
        designation=desig,
        total_count=int(result.get("total", len(rows))),
        returned_count=len(rows),
        offset=offset,
        limit=limit,
        charities=[_record(r, lang) for r in rows],
        provenance=_provenance(year, resource, cached, "CharitySearchResult", lang),
    )


async def get_charity(business_number: str, lang: str = "en") -> CharityDetail:
    """One charity from the Identification table, plus its fiscal period end and programs."""
    bn = normalize_bn(business_number, lang)
    year, package_id, resources = await _list_resources(lang)
    ident, cached = await _datastore(
        resources[constants.RESOURCE_IDENTIFICATION],
        {"filters": json.dumps({"BN": bn}), "limit": 1},
        lang,
    )
    rows = list_or_empty(ident, "records")
    if not rows:
        raise_localized(
            NotFound,
            f"No charity with business number {bn} in the {year} List of charities.",
            f"Aucun organisme avec le numéro d'entreprise {bn} dans la liste {year}.",
            lang,
        )
    general, _ = await _datastore(
        resources[constants.RESOURCE_GENERAL],
        {"filters": json.dumps({"BN": bn}), "limit": 1},
        lang,
    )
    info = (list_or_empty(general, "records") or [{}])[0]
    programs = [
        CharityProgram(
            code=_text(info.get(f"Program #{n} Code")),
            percent=_text(info.get(f"Program #{n} %")),
            description=_text(info.get(f"Program #{n} Desc")),
        )
        for n in (1, 2, 3)
        if any(_text(info.get(f"Program #{n} {suffix}")) for suffix in ("Code", "%", "Desc"))
    ]
    return CharityDetail(
        list_year=year,
        charity=_record(rows[0], lang),
        fiscal_period_end=_date(info.get("FPE")),
        programs=programs,
        dataset_url=constants.DATASET_PAGE.format(id=package_id),
        provenance=_provenance(
            year, resources[constants.RESOURCE_IDENTIFICATION], cached, "CharityDetail", lang
        ),
    )


async def get_directors(business_number: str, lang: str = "en") -> CharityDirectors:
    """Directors and officers of one charity from the directors/officers table."""
    bn = normalize_bn(business_number, lang)
    year, _, resources = await _list_resources(lang)
    resource = resources.get(constants.RESOURCE_DIRECTORS)
    if resource is None:
        raise_localized(
            NotFound,
            f"The {year} list has no directors/officers resource.",
            f"La liste {year} n'a pas de ressource sur les administrateurs.",
            lang,
        )
    # Exact BN filter only: full-text q is refused on resources over 100,000 rows.
    result, cached = await _datastore(
        resource,
        {"filters": json.dumps({"BN": bn}), "limit": constants.DIRECTORS_MAX, "sort": "_id asc"},
        lang,
    )
    rows = list_or_empty(result, "records")
    if not rows:
        raise_localized(
            NotFound,
            f"No directors or officers listed for {bn} in the {year} list.",
            f"Aucun administrateur ou dirigeant pour {bn} dans la liste {year}.",
            lang,
        )
    return CharityDirectors(
        list_year=year,
        business_number=bn,
        fiscal_period_end=_date(rows[0].get("FPE")),
        total_count=int(result.get("total", len(rows))),
        returned_count=len(rows),
        directors=[
            CharityDirector(
                last_name=_text(r.get("Last Name")),
                first_name=_text(r.get("First Name")),
                initials=_text(r.get("Initials")),
                position=_text(r.get("Position")),
                at_arms_length={"Y": True, "N": False}.get(_text(r.get("At Arm's Length")) or ""),
                start_date=_date(r.get("Start Date")),
                end_date=_date(r.get("End Date")),
            )
            for r in rows
        ],
        provenance=_provenance(year, resource, cached, "CharityDirectors", lang),
    )
