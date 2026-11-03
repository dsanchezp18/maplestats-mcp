"""Client for Job Bank's yearly "Wages" DataStore resources on open.canada.ca.

What the code relies on, each confirmed live 2026-11-03 (see constants.py
for the package and column history):

- package_show on the Wages package lists every release as a resource named
  "<year> Wages"; the newest readable one is picked at run time, so the
  yearly release (a new resource id each time) needs no code change.
- datastore_search takes exact `filters`, including a list of values for one
  column ({"NOC_CNP": ["NOC_21231", "NOC_21232"]}), and returns the
  resource's `fields`. Filtering on ER00 gives one national row per
  occupation (516 in 2023-2025), which is the occupation index; one
  occupation's rows give the 86 geographies in Job Bank's order.
- Wages are text columns: "56.49" (hourly) or "84000" (annual), empty
  (null) where Job Bank publishes no wage. Data_Source_E and
  Reference_Period are the literal "NA" on those rows, and Wage_Comment_E
  says to use the provincial wage instead.
- Annual_Wage_Flag_Salaire_annuel is "1" for the occupations Job Bank shows
  at an annual rate (18 in 2025, e.g. legislators, physicians, judges).
- In 2025 a Source2025_NHQ column says which geography each estimate was
  made for ("LFS 2023-24 PR NOC5" on the Ottawa row: Ottawa shows Ontario's
  wage). Its name carries the year, so it is found by pattern.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, NoReturn

from maplestats_mcp.modules.jobbank import constants
from maplestats_mcp.modules.jobbank.schemas import (
    EconomicRegion,
    EconomicRegionList,
    GeographyLevel,
    OccupationComparison,
    OccupationMatch,
    OccupationSearchResult,
    OccupationWages,
    WageRelease,
    WageRow,
    WageUnit,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.ckan import CkanConfig, action
from maplestats_mcp.shared.envelope import make_provenance, raise_localized
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError
from maplestats_mcp.shared.i18n import pick
from maplestats_mcp.shared.json_utils import list_or_empty
from maplestats_mcp.shared.limits import join_limits
from maplestats_mcp.shared.models import Provenance

_CONFIG = CkanConfig(
    source=constants.RATE_LIMIT_SOURCE,
    base_url=constants.BASE_URL,
    rate_limit_per_second=constants.RATE_LIMIT_PER_SECOND,
    rate_limit_capacity=constants.RATE_LIMIT_CAPACITY,
)
_RESOURCE_NAME = re.compile(constants.RESOURCE_NAME_PATTERN, re.IGNORECASE)
_NOC = re.compile(r"^(?:NOC[\s_\-]*)?(\d{5})$", re.IGNORECASE)
_REGION_CODE = re.compile(r"^(?:ER)?\s*(\d{2}|\d{4})$", re.IGNORECASE)
_SOURCE_DETAIL = re.compile(r"^source\d{4}_nhq$", re.IGNORECASE)
_MISSING = {"", "NA", "N/A", "NAN", "NULL", "X", "..", "F"}

# Logical column -> accepted spellings (lower case), oldest first.
_COLUMNS: dict[str, tuple[str, ...]] = {
    "noc": ("noc_cnp",),
    "title_en": ("noc_title_eng",),
    "title_fr": ("noc_title_fra",),
    "prov": ("prov",),
    "er_code": ("er_code_code_re",),
    "er_name_en": ("er_name",),
    "er_name_fr": ("nom_re",),
    "low": ("low_wage_salaire_minium", "low_wage_salaire_minimum"),
    "median": ("median_wage_salaire_median",),
    "high": ("high_wage_salaire_maximal",),
    "average": ("average_wage_salaire_moyen",),
    "q1": ("quartile1_wage_salaire_quartile1",),
    "q3": ("quartile3_wage_salaire_quartile3",),
    "source_en": ("data_source_e",),
    "source_fr": ("data_source_f",),
    "period": ("reference_period",),
    "revision": ("revision_date_date_revision",),
    "annual": ("annual_wage_flag_salaire_annuel",),
    "comment_en": ("wage_comment_e",),
    "comment_fr": ("wage_comment_f",),
    "benefits": ("employeeswithnonwagebenefit_pct", "non_wageben_pct"),
}
_REQUIRED = ("noc", "title_en", "title_fr", "er_code", "er_name_en", "median", "annual")


@dataclass(frozen=True)
class _Release:
    year: int
    resource_id: str
    available: tuple[int, ...]
    note: str | None


@dataclass(frozen=True)
class _Table:
    """A release's columns (logical name -> real column id) and its rows."""

    columns: dict[str, str]
    records: tuple[dict[str, Any], ...]


# ---------------------------------------------------------------- helpers


def _fold(text: str) -> str:
    """Lower case, accents dropped, punctuation and '--' turned into single spaces."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^0-9a-z]+", " ", stripped.casefold()).split())


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return None if text.upper() in _MISSING else text


def _number(value: Any) -> float | None:
    text = _text(value)
    if text is None:
        return None
    try:
        return float(text.replace(",", "").replace("$", "").replace(" ", ""))
    except ValueError:
        return None


def _date(value: Any) -> date | None:
    text = _text(value)
    if text is None:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _level(code: str) -> GeographyLevel:
    digits = code.upper().removeprefix("ER")
    if digits == "00":
        return "national"
    return "provincial" if len(digits) == 2 else "economic_region"


def _estimate_geography(detail: str | None) -> GeographyLevel | None:
    if not detail:
        return None
    tokens = set(detail.upper().split())
    if "ER" in tokens:
        return "economic_region"
    if "PR" in tokens:
        return "provincial"
    if "CAN" in tokens:
        return "national"
    return None


def _upstream(en: str, fr: str, lang: str) -> NoReturn:
    raise_localized(UpstreamError, en, fr, lang)


def _columns(fields: list[Any], lang: str) -> dict[str, str]:
    by_lower = {
        str(f.get("id")).lower(): str(f.get("id"))
        for f in fields
        if isinstance(f, dict) and f.get("id")
    }
    columns: dict[str, str] = {}
    for logical, spellings in _COLUMNS.items():
        for spelling in spellings:
            if spelling in by_lower:
                columns[logical] = by_lower[spelling]
                break
    detail = next((real for low, real in by_lower.items() if _SOURCE_DETAIL.match(low)), None)
    if detail:
        columns["detail"] = detail
    missing = [name for name in _REQUIRED if name not in columns]
    if missing:
        wanted = ", ".join(_COLUMNS[name][0] for name in missing)
        _upstream(
            f"The Job Bank wages resource no longer has the columns this tool reads ({wanted}); "
            "its layout changed. Read it with ckan_datastore_search (portal='federal') meanwhile.",
            f"la ressource des salaires du Guichet-Emplois n'a plus les colonnes que cet outil "
            f"lit ({wanted}) ; sa structure a changé. Lisez-la avec ckan_datastore_search "
            "(portal='federal') en attendant.",
            lang,
        )
    return columns


# ---------------------------------------------------------------- fetching


async def _release(release_year: int | None, lang: str) -> _Release:
    async def fetch() -> Any:
        return await action(_CONFIG, "package_show", {"id": constants.PACKAGE_ID}, lang=lang)

    package, _ = await cached_fetch(
        f"jobbank:package:{constants.PACKAGE_ID}", constants.DISCOVERY_TTL_SECONDS, fetch
    )
    found: dict[int, str] = {}
    resources = list_or_empty(package, "resources") if isinstance(package, dict) else []
    for res in resources:
        if not isinstance(res, dict) or not res.get("id"):
            continue
        names = [res.get("name")]
        translated = res.get("name_translated")
        if isinstance(translated, dict):
            names.append(translated.get("en"))
        match = next((_RESOURCE_NAME.match(n) for n in names if isinstance(n, str)), None)
        active = res.get("datastore_active")
        if match is None or active not in (True, "true", "True"):
            continue
        year = int(match.group(1))
        if year >= constants.MIN_RELEASE_YEAR:
            found.setdefault(year, str(res["id"]))
    available = tuple(sorted(found, reverse=True))
    if not available:
        note = pick(
            lang,
            f"Fallback: the Wages package on open.canada.ca lists no '<year> Wages' DataStore "
            f"resource this tool can read, so MapleStats used its pinned {constants.FALLBACK_YEAR} "
            f"release (resource {constants.FALLBACK_RESOURCE_ID}); a newer release may exist.",
            f"Solution de repli : le jeu de données Salaires d'ouvert.canada.ca ne liste aucune "
            f"ressource « <année> Wages » que cet outil sait lire ; MapleStats a donc utilisé sa "
            f"diffusion {constants.FALLBACK_YEAR} enregistrée (ressource "
            f"{constants.FALLBACK_RESOURCE_ID}) ; une diffusion plus récente peut exister.",
        )
        if release_year not in (None, constants.FALLBACK_YEAR):
            raise_localized(
                NotFound,
                f"No {release_year} Job Bank wages release could be found.",
                f"aucune diffusion {release_year} des salaires du Guichet-Emplois trouvée.",
                lang,
            )
        return _Release(
            constants.FALLBACK_YEAR,
            constants.FALLBACK_RESOURCE_ID,
            (constants.FALLBACK_YEAR,),
            note,
        )
    if release_year is None:
        return _Release(available[0], found[available[0]], available, None)
    if release_year not in found:
        years = ", ".join(str(y) for y in available)
        raise_localized(
            InvalidInput,
            f"release_year must be one of {years} (NOC 2021 releases), got {release_year}. "
            "Older releases use NOC 2016: read them with ckan_datastore_search.",
            f"release_year doit être l'une des années {years} (diffusions CNP 2021) "
            f"(reçu : {release_year}). Les diffusions antérieures utilisent la CNP 2016 : "
            "lisez-les avec ckan_datastore_search.",
            lang,
        )
    return _Release(release_year, found[release_year], available, None)


async def _datastore_all(
    resource_id: str, filters: dict[str, Any], lang: str
) -> tuple[_Table, bool]:
    """Every row matching `filters`, paged, with the release's columns resolved."""

    async def fetch() -> _Table:
        records: list[dict[str, Any]] = []
        fields: list[Any] = []
        for page in range(constants.DATASTORE_MAX_PAGES):
            result = await action(
                _CONFIG,
                "datastore_search",
                {
                    "resource_id": resource_id,
                    "filters": json.dumps(filters, sort_keys=True),
                    "limit": constants.DATASTORE_PAGE,
                    "offset": page * constants.DATASTORE_PAGE,
                    "sort": "_id",
                },
                lang=lang,
            )
            if not isinstance(result, dict):
                _upstream(
                    "open.canada.ca returned a datastore_search result that is not an object.",
                    "ouvert.canada.ca a renvoyé un résultat datastore_search qui n'est pas un objet.",
                    lang,
                )
            fields = fields or list_or_empty(result, "fields")
            batch = [r for r in list_or_empty(result, "records") if isinstance(r, dict)]
            records.extend(batch)
            total = result.get("total")
            if len(batch) < constants.DATASTORE_PAGE or (
                isinstance(total, int) and len(records) >= total
            ):
                break
        return _Table(_columns(fields, lang), tuple(records))

    key = f"jobbank:ds:{resource_id}:{json.dumps(filters, sort_keys=True)}"
    return await cached_fetch(key, constants.DATA_TTL_SECONDS, fetch)


async def _national(release: _Release, lang: str) -> tuple[_Table, bool]:
    """The occupation index: one national (ER00) row per occupation."""
    # The ER code column is named the same in every NOC 2021 release (checked
    # 2023, 2024, 2025), so it can be used before the columns are resolved.
    table, cached = await _datastore_all(
        release.resource_id, {"ER_Code_Code_RE": constants.NATIONAL_ER_CODE}, lang
    )
    if not table.records:
        _upstream(
            f"The Job Bank wages resource {release.resource_id} returned no national rows.",
            f"la ressource des salaires du Guichet-Emplois {release.resource_id} n'a renvoyé "
            "aucune ligne nationale.",
            lang,
        )
    return table, cached


# ---------------------------------------------------------------- shaping


def _release_model(release: _Release, lang: str) -> WageRelease:
    dataset = pick(lang, constants.DATASET_PAGE_EN, constants.DATASET_PAGE_FR)
    citation = pick(
        lang,
        f"Employment and Social Development Canada, Job Bank, '{release.year} Wages' (Wages "
        f"dataset, open.canada.ca, resource {release.resource_id}). Contains information "
        f"licensed under the Open Government Licence - Canada. {dataset}",
        f"Emploi et Développement social Canada, Guichet-Emplois, « Salaires de {release.year} » "
        f"(jeu de données Salaires, ouvert.canada.ca, ressource {release.resource_id}). "
        f"Contient des informations visées par la Licence du gouvernement ouvert - Canada. "
        f"{dataset}",
    )
    return WageRelease(
        release_year=release.year,
        resource_id=release.resource_id,
        dataset_url=dataset,
        job_bank_url=pick(lang, constants.JOB_BANK_WAGES_EN, constants.JOB_BANK_WAGES_FR),
        methodology_url=constants.METHODOLOGY_URL,
        citation=citation,
        available_years=list(release.available),
        note=release.note,
    )


def _limits(lang: str) -> str:
    return pick(
        lang,
        "Job Bank estimates, not a Statistics Canada table: mostly from the Labour Force Survey, "
        "with Small Area Estimation, Employment Insurance survey data, the 2021 Census and "
        "administrative data where it is too thin; the source and reference period differ "
        "from cell to cell. Low and high are in most cases the 10th and 90th percentiles. "
        "Unpublished cells (published false) have no wage; some regions show their "
        "province's wage (see estimate_geography). Wages do not account for experience",
        "Estimations du Guichet-Emplois, et non un tableau de Statistique Canada : surtout "
        "tirées de l'Enquête sur la population active, complétée par l'estimation pour petits "
        "domaines, les données d'enquête de l'assurance-emploi, le Recensement de 2021 et des "
        "données administratives ; la source et la période de référence varient d'une cellule "
        "à l'autre. Les salaires bas et élevés correspondent le plus souvent aux 10e et 90e "
        "centiles. Les cellules non publiées (published false) n'ont pas de salaire ; "
        "certaines régions affichent le salaire de leur province (voir estimate_geography). "
        "Les salaires ne tiennent pas compte de l'expérience",
    )


def _provenance(
    release: _Release,
    schema: str,
    lang: str,
    *,
    cached: bool,
    as_of: date | None = None,
    coverage: str | None = None,
) -> Provenance:
    return make_provenance(
        source=constants.RATE_LIMIT_SOURCE,
        url=f"{constants.BASE_URL}datastore_search?resource_id={release.resource_id}",
        cached=cached,
        schema_name=f"jobbank.{schema}",
        as_of=datetime(as_of.year, as_of.month, as_of.day, tzinfo=UTC) if as_of else None,
        freshness=pick(
            lang,
            "yearly; ESDC publishes a new release each autumn. MapleStats checks for it daily",
            "annuelle ; EDSC publie une nouvelle diffusion chaque automne. MapleStats la "
            "cherche chaque jour",
        ),
        coverage=coverage,
        limits=join_limits(release.note, _limits(lang)),
        lang=lang,
    )


def _get(row: dict[str, Any], columns: dict[str, str], name: str) -> Any:
    column = columns.get(name)
    return row.get(column) if column else None


def _noc_code(row: dict[str, Any], columns: dict[str, str]) -> str:
    raw = str(_get(row, columns, "noc") or "")
    match = re.search(r"(\d{4,5})$", raw.strip())
    return match.group(1) if match else raw.strip()


def _unit(row: dict[str, Any], columns: dict[str, str]) -> WageUnit:
    return "annual" if str(_get(row, columns, "annual") or "").strip() == "1" else "hourly"


def _wage_row(row: dict[str, Any], columns: dict[str, str], lang: str) -> WageRow:
    code = str(_get(row, columns, "er_code") or "").strip().upper()
    prov = _text(_get(row, columns, "prov"))
    name_en = _text(_get(row, columns, "er_name_en")) or code
    name_fr = _text(_get(row, columns, "er_name_fr")) or name_en
    title_en = _text(_get(row, columns, "title_en")) or ""
    title_fr = _text(_get(row, columns, "title_fr")) or title_en
    wages = {k: _number(_get(row, columns, k)) for k in ("low", "median", "high")}
    detail = _text(_get(row, columns, "detail"))
    level = _level(code)
    return WageRow(
        noc_code=_noc_code(row, columns),
        occupation=pick(lang, title_en, title_fr),
        region_code=code,
        region_name=pick(lang, name_en, name_fr),
        province=None if level == "national" or prov in constants.NATIONAL_PROV_CODES else prov,
        geography_level=level,
        wage_unit=_unit(row, columns),
        low_wage=wages["low"],
        median_wage=wages["median"],
        high_wage=wages["high"],
        average_wage=_number(_get(row, columns, "average")),
        quartile_1_wage=_number(_get(row, columns, "q1")),
        quartile_3_wage=_number(_get(row, columns, "q3")),
        published=any(v is not None for v in wages.values()),
        data_source=_text(_get(row, columns, "source_fr" if lang == "fr" else "source_en"))
        or _text(_get(row, columns, "source_en")),
        reference_period=_text(_get(row, columns, "period")),
        source_detail=detail,
        estimate_geography=_estimate_geography(detail),
        revision_date=_date(_get(row, columns, "revision")),
        comment=_text(_get(row, columns, "comment_fr" if lang == "fr" else "comment_en")),
        employees_with_non_wage_benefits_pct=_number(_get(row, columns, "benefits")),
    )


def _latest_revision(rows: list[WageRow]) -> date | None:
    dates = [r.revision_date for r in rows if r.revision_date]
    return max(dates) if dates else None


def normalize_noc(raw: str, lang: str = "en") -> str:
    """'21231', 'NOC 21231' or 'NOC_21231' -> '21231'."""
    match = _NOC.match(str(raw).strip())
    if not match:
        raise_localized(
            InvalidInput,
            f"noc must be a five-digit NOC 2021 code such as 21231, got {raw!r}. Find codes "
            "with jobbank_search_occupations.",
            f"noc doit être un code de la CNP 2021 à cinq chiffres comme 21231 (reçu : {raw!r}). "
            "Trouvez les codes avec jobbank_search_occupations.",
            lang,
        )
    return match.group(1)


# ---------------------------------------------------------------- regions


def _regions_from(table: _Table, lang: str) -> list[EconomicRegion]:
    """The geographies of one occupation's rows, in Job Bank's order."""
    regions: list[EconomicRegion] = []
    seen: set[str] = set()
    for record in table.records:
        row = _wage_row(record, table.columns, lang)
        if row.region_code in seen:
            continue
        seen.add(row.region_code)
        regions.append(
            EconomicRegion(
                region_code=row.region_code,
                name=row.region_name,
                province=row.province,
                geography_level=row.geography_level,
            )
        )
    return regions


async def _geographies(release: _Release, lang: str) -> tuple[_Table, bool]:
    """Every geography's row for the release's first occupation, in Job Bank's order."""
    national, cached = await _national(release, lang)
    first = str(national.records[0].get(national.columns["noc"]))
    sample, also = await _datastore_all(release.resource_id, {national.columns["noc"]: first}, lang)
    return sample, cached and also


def _region_names(record: dict[str, Any], columns: dict[str, str]) -> set[str]:
    names = {_fold(str(_get(record, columns, k) or "")) for k in ("er_name_en", "er_name_fr")}
    return {n for n in names if n}


def _province_code(raw: str | None, lang: str) -> str | None:
    if raw is None or not raw.strip():
        return None
    code = constants.PROVINCE_ALIASES.get(raw.strip().upper())
    if code is None:
        raise_localized(
            InvalidInput,
            f"province must be a province or territory code such as ON, QC, BC or YT, got {raw!r}.",
            f"province doit être un code de province ou de territoire comme ON, QC, BC ou YT "
            f"(reçu : {raw!r}).",
            lang,
        )
    return code


def _resolve_region(
    region: str, province: str | None, sample: _Table, lang: str
) -> tuple[str, str]:
    """A region name, code or province -> (ER code, display name)."""
    columns = sample.columns
    rows = [_wage_row(r, columns, lang) for r in sample.records]
    text = region.strip()
    folded = _fold(text)
    if folded in {"canada", "national", "nat", "er00"}:
        national = next((r for r in rows if r.geography_level == "national"), None)
        if national:
            return national.region_code, national.region_name
    code_match = _REGION_CODE.match(text)
    if code_match:
        code = f"ER{code_match.group(1)}"
        hit = next((r for r in rows if r.region_code == code), None)
        if hit:
            return hit.region_code, hit.region_name
    alias = constants.PROVINCE_ALIASES.get(text.upper())
    candidates = rows
    if province:
        candidates = [r for r in rows if r.province == province]
    if alias:
        in_prov = [r for r in rows if r.province == alias]
        top = [r for r in in_prov if r.geography_level == "provincial"] or in_prov[:1]
        if top:
            return top[0].region_code, top[0].region_name
    by_name = {
        r.region_code: _region_names(rec, columns)
        for r, rec in zip(rows, sample.records, strict=True)
    }
    exact = [r for r in candidates if folded in by_name[r.region_code]]
    if not exact:
        exact = [
            r for r in candidates if any(folded and folded in n for n in by_name[r.region_code])
        ]
    # A province's own row beats its economic regions with the same name
    # (PEI, Yukon) and "Ontario" must not also match nothing else.
    if len(exact) > 1:
        provincial = [r for r in exact if r.geography_level != "economic_region"]
        if len(provincial) == 1:
            exact = provincial
    if len(exact) == 1:
        return exact[0].region_code, exact[0].region_name
    if not exact:
        raise_localized(
            NotFound,
            f"No Job Bank geography matches region {region!r}. List them with "
            "jobbank_list_regions, or pass a code such as ER3530 or a province code such as ON.",
            f"aucune géographie du Guichet-Emplois ne correspond à la région {region!r}. "
            "Listez-les avec jobbank_list_regions, ou passez un code comme ER3530 ou un code "
            "de province comme ON.",
            lang,
        )
    options = "; ".join(f"{r.region_code} {r.region_name} ({r.province})" for r in exact[:10])
    raise_localized(
        InvalidInput,
        f"region {region!r} matches several geographies: {options}. Pass its code, or a province.",
        f"la région {region!r} correspond à plusieurs géographies : {options}. Passez son code "
        "ou une province.",
        lang,
    )


# ---------------------------------------------------------------- public API


async def search_occupations(
    query: str,
    limit: int = constants.SEARCH_LIMIT_DEFAULT,
    release_year: int | None = None,
    lang: str = "en",
) -> OccupationSearchResult:
    text = (query or "").strip()
    if not text:
        raise_localized(
            InvalidInput,
            "query must not be empty: give words from an occupation title or a NOC code.",
            "query ne doit pas être vide : donnez des mots d'un titre de profession ou un "
            "code CNP.",
            lang,
        )
    if not 1 <= limit <= constants.SEARCH_LIMIT_MAX:
        raise_localized(
            InvalidInput,
            f"limit must be between 1 and {constants.SEARCH_LIMIT_MAX}, got {limit}.",
            f"limit doit être entre 1 et {constants.SEARCH_LIMIT_MAX} (reçu : {limit}).",
            lang,
        )
    release = await _release(release_year, lang)
    national, cached = await _national(release, lang)
    columns = national.columns
    digits = re.sub(r"^NOC[\s_\-]*", "", text, flags=re.IGNORECASE)
    scored: list[tuple[int, str, dict[str, Any]]] = []
    if digits.isdigit():
        for record in national.records:
            code = _noc_code(record, columns)
            if code.startswith(digits):
                scored.append((0 if code == digits else 1, code, record))
    else:
        words = _fold(text).split()
        for record in national.records:
            en = _fold(str(_get(record, columns, "title_en") or ""))
            fr = _fold(str(_get(record, columns, "title_fr") or ""))
            haystack = f"{en} {fr}"
            if not all(w in haystack for w in words):
                continue
            whole = _fold(text)
            score = (
                0
                if whole in (en, fr)
                else 1
                if (en.startswith(whole) or fr.startswith(whole))
                else 2
            )
            scored.append((score, _noc_code(record, columns), record))
    scored.sort(key=lambda item: (item[0], item[1]))
    matches = []
    for _, code, record in scored[:limit]:
        row = _wage_row(record, columns, lang)
        matches.append(
            OccupationMatch(
                noc_code=code,
                title_en=_text(_get(record, columns, "title_en")) or "",
                title_fr=_text(_get(record, columns, "title_fr")) or "",
                national_median_wage=row.median_wage,
                wage_unit=row.wage_unit,
                reference_period=row.reference_period,
                data_source=row.data_source,
            )
        )
    return OccupationSearchResult(
        query=text,
        matches=matches,
        total_matching=len(scored),
        returned_count=len(matches),
        release=_release_model(release, lang),
        provenance=_provenance(
            release,
            "OccupationSearchResult",
            lang,
            cached=cached,
            coverage=pick(
                lang,
                f"{len(matches)} of {len(scored)} matching occupations out of "
                f"{len(national.records)} in the {release.year} release; national median shown",
                f"{len(matches)} professions sur {len(scored)} correspondantes, parmi les "
                f"{len(national.records)} de la diffusion {release.year} ; médiane nationale "
                "affichée",
            ),
        ),
    )


async def list_regions(
    province: str | None = None, release_year: int | None = None, lang: str = "en"
) -> EconomicRegionList:
    prov = _province_code(province, lang)
    release = await _release(release_year, lang)
    sample, cached = await _geographies(release, lang)
    regions = _regions_from(sample, lang)
    if prov:
        regions = [r for r in regions if r.province == prov]
    return EconomicRegionList(
        regions=regions,
        returned_count=len(regions),
        release=_release_model(release, lang),
        provenance=_provenance(
            release,
            "EconomicRegionList",
            lang,
            cached=cached,
            coverage=pick(
                lang,
                f"Canada, provinces and territories and economic regions in the {release.year} "
                "release" + (f", province {prov} only" if prov else ""),
                f"Canada, provinces et territoires et régions économiques de la diffusion "
                f"{release.year}" + (f", province {prov} seulement" if prov else ""),
            ),
        ),
    )


async def get_wages(
    noc: str,
    region: str | None = None,
    province: str | None = None,
    published_only: bool = False,
    release_year: int | None = None,
    lang: str = "en",
) -> OccupationWages:
    code = normalize_noc(noc, lang)
    prov = _province_code(province, lang)
    release = await _release(release_year, lang)
    national, _ = await _national(release, lang)
    noc_column = national.columns["noc"]
    table, cached = await _datastore_all(release.resource_id, {noc_column: f"NOC_{code}"}, lang)
    if not table.records:
        raise_localized(
            NotFound,
            f"NOC {code} is not in the {release.year} Job Bank wages release. Find the code "
            "with jobbank_search_occupations.",
            f"la CNP {code} ne figure pas dans la diffusion {release.year} des salaires du "
            "Guichet-Emplois. Trouvez le code avec jobbank_search_occupations.",
            lang,
        )
    rows = [_wage_row(r, table.columns, lang) for r in table.records]
    if region and region.strip():
        er_code, _ = _resolve_region(region, prov, table, lang)
        rows = [r for r in rows if r.region_code == er_code]
    elif prov:
        rows = [r for r in rows if r.province == prov]
    if published_only:
        rows = [r for r in rows if r.published]
    published = sum(r.published for r in rows)
    return OccupationWages(
        noc_code=code,
        occupation=_wage_row(table.records[0], table.columns, lang).occupation,
        rows=rows,
        returned_count=len(rows),
        published_count=published,
        unpublished_count=len(rows) - published,
        release=_release_model(release, lang),
        provenance=_provenance(
            release,
            "OccupationWages",
            lang,
            cached=cached,
            as_of=_latest_revision(rows),
            coverage=pick(
                lang,
                f"{len(rows)} of {len(table.records)} geographies for NOC {code}, "
                f"{published} with a published wage",
                f"{len(rows)} géographies sur {len(table.records)} pour la CNP {code}, dont "
                f"{published} avec un salaire publié",
            ),
        ),
    )


async def compare_occupations(
    nocs: list[str],
    region: str = "Canada",
    province: str | None = None,
    release_year: int | None = None,
    lang: str = "en",
) -> OccupationComparison:
    codes = list(dict.fromkeys(normalize_noc(n, lang) for n in nocs))
    if not constants.COMPARE_MIN <= len(codes) <= constants.COMPARE_MAX:
        raise_localized(
            InvalidInput,
            f"nocs must list {constants.COMPARE_MIN} to {constants.COMPARE_MAX} different NOC "
            f"codes, got {len(codes)}.",
            f"nocs doit lister de {constants.COMPARE_MIN} à {constants.COMPARE_MAX} codes CNP "
            f"différents (reçu : {len(codes)}).",
            lang,
        )
    prov = _province_code(province, lang)
    release = await _release(release_year, lang)
    sample, _ = await _geographies(release, lang)
    er_code, er_name = _resolve_region(region or "Canada", prov, sample, lang)
    columns = sample.columns
    table, cached = await _datastore_all(
        release.resource_id,
        {columns["noc"]: [f"NOC_{c}" for c in codes], columns["er_code"]: er_code},
        lang,
    )
    by_code = {
        row.noc_code: row for row in (_wage_row(r, table.columns, lang) for r in table.records)
    }
    rows = [by_code[c] for c in codes if c in by_code]
    not_found = [c for c in codes if c not in by_code]
    if not rows:
        raise_localized(
            NotFound,
            f"None of the NOC codes {', '.join(codes)} is in the {release.year} release. Find "
            "codes with jobbank_search_occupations.",
            f"aucun des codes CNP {', '.join(codes)} ne figure dans la diffusion {release.year}. "
            "Trouvez les codes avec jobbank_search_occupations.",
            lang,
        )
    return OccupationComparison(
        region_code=er_code,
        region_name=er_name,
        rows=rows,
        not_found=not_found,
        mixed_units=len({r.wage_unit for r in rows}) > 1,
        release=_release_model(release, lang),
        provenance=_provenance(
            release,
            "OccupationComparison",
            lang,
            cached=cached,
            as_of=_latest_revision(rows),
            coverage=pick(
                lang,
                f"{len(rows)} of {len(codes)} occupations in {er_name} ({er_code})",
                f"{len(rows)} professions sur {len(codes)} dans {er_name} ({er_code})",
            ),
        ),
    )
