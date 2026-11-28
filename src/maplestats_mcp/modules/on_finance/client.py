"""Ontario Ministry of Finance population projections from data.ontario.ca.

The dataset's resources are listed through the CKAN family's client (portal
"on"), so a caller never supplies a URL; the English workbook of the asked
geography is downloaded through the same per-portal file bucket and byte cache
as ckan_read_resource, and read row by row with only the asked rows kept.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal, NoReturn
from urllib.parse import urlparse

from maplestats_mcp.modules.ckan import client as ckan
from maplestats_mcp.modules.ckan.constants import PORTALS
from maplestats_mcp.modules.ckan.files import host_matcher
from maplestats_mcp.modules.ckan.schemas import ResourceInfo
from maplestats_mcp.modules.on_finance import constants
from maplestats_mcp.modules.on_finance.schemas import (
    ComponentsRow,
    Gender,
    PopulationProjection,
    ProjectionArea,
    ProjectionComponents,
    ProjectionRow,
    Scenario,
)
from maplestats_mcp.shared import file_download
from maplestats_mcp.shared.envelope import make_provenance, raise_localized
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError
from maplestats_mcp.shared.executor import check_deadline, run_parse
from maplestats_mcp.shared.i18n import pick
from maplestats_mcp.shared.licences import licence_for
from maplestats_mcp.shared.rate_limiter import get_limiter
from maplestats_mcp.shared.xlsx_sheets import fix_dimensions, open_workbook

Lang = Literal["en", "fr"]
Geography = Literal["ontario", "region", "census_division", "public_health_unit", "mccss_region"]
GenderChoice = Literal["all", "women+", "men+", "any"]
ScenarioChoice = Literal["reference", "low", "high", "any"]
AgeGroups = Literal["broad", "five_year", "single_year"]
Release = Literal["latest", "annual"]

_FILES = get_limiter(constants.FILES_BUCKET, rate=constants.FILES_RATE_PER_SECOND, capacity=1.0)
_SCENARIOS: dict[str, Scenario] = {
    "REFERENCE": "reference",
    "LOW-GROWTH": "low",
    "HIGH-GROWTH": "high",
}
_GENDERS: dict[str, Gender] = {
    "MEN+": "men+",
    "WOMEN+": "women+",
    "TOTAL ALL GENDERS": "all",
    "TOTAL BOTH GENDERS": "all",
}
# The band row above the header names the age-group blocks (live 2026-11-24).
_BANDS: dict[str, AgeGroups] = {
    "BROAD AGE GROUPS": "broad",
    "5-YEAR AGE GROUPS": "five_year",
    "SINGLE-YEAR OF AGE": "single_year",
}
_RELEASE = re.compile(r"\(([^()]*\d{4}[^()]*)\)\s*\.?\s*$")
# Components header (upper case, spaces collapsed) -> field.
_COMPONENTS = {
    "START POPULATION (JULY 1)": "start_population",
    "BIRTHS": "births",
    "DEATHS": "deaths",
    "NATURAL INCREASE": "natural_increase",
    "IMMIGRATION": "immigration",
    "EMIGRATION": "emigration",
    "NET CHANGE IN NON-PERMANENT RESIDENTS": "net_non_permanent_residents",
    "NET INTERNATIONAL MIGRATION": "net_international_migration",
    "INTERPROVINCIAL IN-MIGRATION": "interprovincial_in",
    "INTERPROVINCIAL OUT-MIGRATION": "interprovincial_out",
    "NET INTERPROVINCIAL MIGRATION": "net_interprovincial",
    "NET MIGRATION": "net_migration",
    "TOTAL POPULATION CHANGE": "total_change",
    "RATE OF TOTAL POPULATION CHANGE (%)": "growth_rate_percent",
}


def _fail(cls: type[ValueError], en: str, fr: str, lang: str) -> NoReturn:
    raise_localized(cls, f"on_finance: {en}", f"on_finance : {fr}", lang)


def _head(value: Any) -> str:
    return " ".join(str(value).split()).upper() if value is not None else ""


def _int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return round(value)
    text = str(value).replace(",", "").strip()
    try:
        return round(float(text))
    except ValueError:
        return None


def _float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return round(float(value), 4)
    try:
        return round(float(str(value).replace(",", "").strip()), 4)
    except ValueError:
        return None


@dataclass
class Sheet:
    """The asked rows of one workbook, with what the file says about itself."""

    title: str | None = None
    release: str | None = None
    notes: list[str] = field(default_factory=list)
    header: list[str] = field(default_factory=list)
    bands: list[AgeGroups | None] = field(default_factory=list)
    areas: list[tuple[int | None, str]] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    first_year: int | None = None


def parse_workbook(body: bytes, keep: Any = None) -> Sheet:
    """Read the single sheet; `keep(row_dict)` says which data rows to hold on to."""
    workbook = open_workbook(body)
    try:
        sheet = workbook.worksheets[0]
        # A sheet declared as just A1 yields one row, so the header is never found;
        # an inflated declared size pads every row and runs into the parse deadline
        # (xlsx_sheets.fix_dimensions, both writer bugs confirmed live).
        fix_dimensions(sheet)
        result = Sheet()
        band_row: list[Any] = []
        header_at: int | None = None
        seen_areas: dict[tuple[int | None, str], None] = {}
        for index, raw in enumerate(sheet.iter_rows(values_only=True)):
            if index % 200 == 0:
                check_deadline()
            cells = list(raw)
            if header_at is None:
                labels = [_head(c) for c in cells]
                if "GENDER" in labels or "PERIOD" in labels:
                    header_at = index
                    result.header = labels
                    current: AgeGroups | None = None
                    for i in range(len(labels)):
                        band = _head(band_row[i]) if i < len(band_row) else ""
                        found = _BANDS.get(band)
                        current = found if found is not None else current
                        result.bands.append(current)
                    continue
                if index >= constants.HEADER_SEARCH_ROWS:
                    break
                text = " ".join(str(c) for c in cells if c is not None).strip()
                if result.title is None and text:
                    result.title = text
                elif text.lower().startswith("sources"):
                    match = _RELEASE.search(text)
                    result.release = match.group(1).strip() if match else None
                    result.notes.append(text)
                elif text.lower().startswith("note"):
                    result.notes.append(text)
                band_row = cells
                continue
            if all(c is None or str(c).strip() == "" for c in cells):
                continue
            record = {
                name: cells[i] if i < len(cells) else None for i, name in enumerate(result.header)
            }
            year = _int(record.get("YEAR (JULY 1)"))
            if year is not None and (result.first_year is None or year < result.first_year):
                result.first_year = year
            if "REGION NAME" in record and record["REGION NAME"] is not None:
                key = (
                    _int(record.get("REGION CODE")),
                    " ".join(str(record["REGION NAME"]).split()),
                )
                seen_areas.setdefault(key, None)
            if keep is None or keep(record):
                result.rows.append(cells)
        result.areas = list(seen_areas)
        return result
    finally:
        workbook.close()


async def _resources() -> tuple[list[ResourceInfo], bool]:
    # Read in English whatever `lang` is: the French catalogue translates the
    # resource names this module matches on (live 2026-11-24).
    package = await ckan.get_dataset(constants.PORTAL, constants.DATASET, "en")
    english = [
        r
        for r in package.resources
        if r.url and constants.ENGLISH_FILE_MARKER in urlparse(r.url).path.lower()
    ]
    return english, package.provenance.cached


def _resource(
    resources: list[ResourceInfo], words: str, release: Release, lang: Lang
) -> tuple[ResourceInfo, bool]:
    # Resource names are the same in both catalogue languages' English files:
    # "Ontario MOF Population Projections", "Interim Ontario MOF ...".
    def name(r: ResourceInfo) -> str:
        return " ".join(r.name.lower().split())

    matching = [r for r in resources if words in name(r)]
    interim = [r for r in matching if name(r).startswith(constants.INTERIM_PREFIX)]
    annual = [r for r in matching if not name(r).startswith(constants.INTERIM_PREFIX)]
    if release == "latest" and interim:
        return interim[0], True
    if annual:
        return annual[0], False
    _fail(
        NotFound,
        f"no workbook named with {words!r} in data.ontario.ca dataset {constants.DATASET}; "
        "the ministry may have renamed its files (see ckan_get_dataset, portal=on).",
        f"aucun classeur dont le nom contient {words!r} dans le jeu {constants.DATASET} de "
        "data.ontario.ca ; le ministère a peut-être renommé ses fichiers (voir "
        "ckan_get_dataset, portal=on).",
        lang,
    )


async def _body(resource: ResourceInfo, lang: Lang) -> tuple[bytes, bool]:
    url = resource.url or ""
    if resource.size and resource.size > constants.MAX_FILE_BYTES:
        _fail(
            UpstreamError,
            f"{url} is larger than this tool reads.",
            f"{url} dépasse la taille que cet outil lit.",
            lang,
        )

    async def fetch() -> file_download.Downloaded:
        return await file_download.download(
            url,
            allow_host=host_matcher(PORTALS[constants.PORTAL]),
            limiter_for=lambda _host: _FILES,
            max_bytes=constants.MAX_FILE_BYTES,
            context="on_finance",
            timeout=120.0,
        )

    # The key ckan_read_resource (portal "on") uses for this URL: one cached copy.
    downloaded, cached = await file_download.cached_download(
        file_download.cache_key(url), constants.CACHE_TTL_FILE_SECONDS, fetch
    )
    return downloaded.body, cached


async def _parse(body: bytes, url: str, keep: Any, lang: Lang) -> Sheet:
    try:
        sheet = await run_parse(parse_workbook, body, keep)
    except UpstreamError:
        raise
    except Exception as exc:  # noqa: BLE001 (re-raised as UpstreamError)
        _fail(
            UpstreamError, f"could not read {url}: {exc}", f"impossible de lire {url} : {exc}", lang
        )
    if not sheet.header:
        _fail(
            UpstreamError,
            f"{url} no longer has the header row this tool reads (GENDER or PERIOD); read it "
            "with ckan_read_resource (portal=on).",
            f"{url} n'a plus la ligne d'en-tête que cet outil lit (GENDER ou PERIOD) ; lisez-le "
            "avec ckan_read_resource (portal=on).",
            lang,
        )
    return sheet


def _years(start_year: int | None, end_year: int | None, lang: Lang) -> None:
    if start_year is not None and end_year is not None and start_year > end_year:
        _fail(
            InvalidInput,
            "start_year must not be after end_year.",
            "start_year ne doit pas être postérieure à end_year.",
            lang,
        )


def _match_area(
    areas: list[tuple[int | None, str]], area: str, lang: Lang
) -> tuple[int | None, str]:
    wanted = " ".join(area.lower().split())
    by_code = [a for a in areas if a[0] is not None and str(a[0]) == wanted]
    exact = [a for a in areas if a[1].lower() == wanted]
    partial = [a for a in areas if wanted in a[1].lower()]
    for found in (by_code, exact, partial):
        if len(found) == 1:
            return found[0]
    shown = ", ".join(a[1] for a in areas)
    _fail(
        InvalidInput,
        f"area {area!r} matches {len(partial)} areas; give a name or code of: {shown}.",
        f"la zone {area!r} correspond à {len(partial)} zones ; donnez un nom ou un code parmi : "
        f"{shown}.",
        lang,
    )


def _licence(lang: Lang) -> str:
    return licence_for(constants.PROVENANCE_SOURCE, constants.DATASET_URL) or ""


async def get_population_projection(
    geography: Geography = "ontario",
    area: str | None = None,
    scenario: ScenarioChoice = "reference",
    gender: GenderChoice = "all",
    start_year: int | None = None,
    end_year: int | None = None,
    age_groups: AgeGroups | None = None,
    release: Release = "latest",
    lang: Lang = "en",
) -> PopulationProjection:
    _years(start_year, end_year, lang)
    words = constants.GEOGRAPHY_FILES.get(geography)
    if words is None:
        _fail(
            InvalidInput,
            f"geography must be one of {', '.join(constants.GEOGRAPHY_FILES)}.",
            f"geography doit être l'une de {', '.join(constants.GEOGRAPHY_FILES)}.",
            lang,
        )
    provincial = geography == "ontario"
    if provincial and area is not None:
        _fail(
            InvalidInput,
            "area is for a sub-provincial geography; leave it unset for Ontario.",
            "area vaut pour une géographie infraprovinciale ; laissez-la vide pour l'Ontario.",
            lang,
        )
    if not provincial and scenario not in ("reference", "any"):
        _fail(
            InvalidInput,
            "sub-provincial projections are published for the reference scenario only; low "
            "and high growth exist for Ontario as a whole.",
            "les projections infraprovinciales ne sont publiées que pour le scénario de "
            "référence ; la croissance faible et forte existent pour l'Ontario seulement.",
            lang,
        )
    if not provincial and area is None and age_groups not in (None, "broad"):
        _fail(
            InvalidInput,
            "five-year and single-year ages are given for one area at a time; pass `area`.",
            "les groupes quinquennaux et les années d'âge se donnent pour une zone à la fois ; "
            "passez `area`.",
            lang,
        )
    resources, _ = await _resources()
    resource, interim = _resource(resources, words, release, lang)
    url = resource.url or ""
    body, cached = await _body(resource, lang)

    # A first pass learns the areas (cheap: nothing kept) when an area is named.
    chosen_area: tuple[int | None, str] | None = None
    if area is not None:
        listing = await _parse(body, url, lambda _r: False, lang)
        chosen_area = _match_area(listing.areas, area, lang)

    def keep(record: dict[str, Any]) -> bool:
        year = _int(record.get("YEAR (JULY 1)"))
        if year is None:
            return False
        if start_year is not None and year < start_year:
            return False
        if end_year is not None and year > end_year:
            return False
        published = _GENDERS.get(_head(record.get("GENDER")))
        if published is None or (gender != "any" and published != gender):
            return False
        if provincial:
            found = _SCENARIOS.get(_head(record.get("SCENARIO")))
            if found is None or (scenario != "any" and found != scenario):
                return False
        if chosen_area is not None:
            name = " ".join(str(record.get("REGION NAME") or "").split())
            return name == chosen_area[1]
        return True

    sheet = await _parse(body, url, keep, lang)
    header = sheet.header
    index = {name: i for i, name in enumerate(header)}
    # Mean Age and Median Age follow the single years in the public health unit
    # file; only labels that start with a digit are ages.
    age_columns = [
        (i, name)
        for i, name in enumerate(header)
        if age_groups is not None
        and i < len(sheet.bands)
        and sheet.bands[i] == age_groups
        and name[:1].isdigit()
    ]
    rows: list[ProjectionRow] = []
    for cells in sheet.rows:

        def cell(name: str, cells: list[Any] = cells) -> Any:
            i = index.get(name)
            return cells[i] if i is not None and i < len(cells) else None

        year = _int(cell("YEAR (JULY 1)")) or 0
        rows.append(
            ProjectionRow(
                area=" ".join(str(cell("REGION NAME")).split()) if not provincial else "Ontario",
                code=_int(cell("REGION CODE")),
                scenario=_SCENARIOS.get(_head(cell("SCENARIO")), "reference"),
                year=year,
                projected=sheet.first_year is None or year > sheet.first_year,
                gender=_GENDERS[_head(cell("GENDER"))],
                total=_int(cell("TOTAL")),
                ages={
                    str(header_cell(sheet, i)): _int(cells[i] if i < len(cells) else None)
                    for i, _name in age_columns
                }
                if age_groups is not None
                else None,
                mean_age=_float(cell("MEAN AGE")),
                median_age=_float(cell("MEDIAN AGE")),
            )
        )
    total = len(rows)
    limits: list[str] = []
    if total > constants.ROWS_MAX:
        rows = rows[: constants.ROWS_MAX]
        limits.append(
            pick(
                lang,
                f"the first {constants.ROWS_MAX} of {total} rows; narrow with area, gender or "
                "years",
                f"les {constants.ROWS_MAX} premières lignes sur {total} ; restreignez avec area, "
                "gender ou les années",
            )
        )
    if age_groups is not None and not age_columns:
        limits.append(
            pick(
                lang,
                f"this file has no {age_groups} age columns",
                f"ce fichier n'a pas de colonnes d'âge {age_groups}",
            )
        )
    what = pick(
        lang,
        f"Ontario Ministry of Finance population projections, {resource.name}"
        + (f" ({sheet.release})" if sheet.release else "")
        + f". Population on July 1; {sheet.first_year} is a Statistics Canada estimate "
        "(projected false).",
        f"Projections démographiques du ministère des Finances de l'Ontario, {resource.name}"
        + (f" ({sheet.release})" if sheet.release else "")
        + f". Population au 1er juillet ; {sheet.first_year} est une estimation de "
        "Statistique Canada (projected faux). Noms des zones en anglais, comme publiés.",
    )
    return PopulationProjection(
        geography=geography,
        release=sheet.release,
        interim=interim,
        base_year=sheet.first_year,
        areas=[ProjectionArea(code=c, name=n) for c, n in sheet.areas]
        if not provincial
        else [ProjectionArea(name="Ontario")],
        rows=rows,
        total_rows=total,
        title=sheet.title,
        resource_name=resource.name,
        url=url,
        dataset_url=constants.DATASET_URL,
        licence=_licence(lang),
        provenance=make_provenance(
            source=constants.PROVENANCE_SOURCE,
            url=url,
            cached=cached,
            schema_name="on_finance.PopulationProjection",
            freshness=pick(
                lang,
                "Released yearly in summer, with a fall interim update for Ontario as a whole.",
                "Diffusion annuelle en été, avec une mise à jour intérimaire à l'automne pour "
                "l'ensemble de l'Ontario.",
            ),
            coverage=what,
            limits=pick(lang, "; ", " ; ").join(limits) or None,
            lang=lang,
        ),
    )


def header_cell(sheet: Sheet, i: int) -> str:
    """An age column's published label: '0 to 14', '65 PLUS' -> '65 Plus', 0 -> '0'."""
    label = sheet.header[i]
    return label.title().replace(" To ", " to ") if not label.isdigit() else label


async def get_projection_components(
    scenario: ScenarioChoice = "reference",
    start_year: int | None = None,
    end_year: int | None = None,
    release: Release = "latest",
    lang: Lang = "en",
) -> ProjectionComponents:
    _years(start_year, end_year, lang)
    resources, _ = await _resources()
    resource, interim = _resource(resources, constants.COMPONENTS_FILE, release, lang)
    url = resource.url or ""
    body, cached = await _body(resource, lang)
    sheet = await _parse(body, url, None, lang)
    index = {name: i for i, name in enumerate(sheet.header)}
    if "SCENARIO" not in index or "PERIOD" not in index:
        _fail(
            UpstreamError,
            f"{url} no longer has SCENARIO and PERIOD columns.",
            f"{url} n'a plus de colonnes SCENARIO et PERIOD.",
            lang,
        )
    rows: list[ComponentsRow] = []
    for cells in sheet.rows:
        found = _SCENARIOS.get(_head(cells[index["SCENARIO"]]))
        if found is None or (scenario != "any" and found != scenario):
            continue
        period = " ".join(str(cells[index["PERIOD"]]).split())
        first = _int(period[:4])
        if first is not None and (
            (start_year is not None and first < start_year)
            or (end_year is not None and first > end_year)
        ):
            continue
        values: dict[str, Any] = {}
        for head, name in _COMPONENTS.items():
            i = index.get(head)
            raw = cells[i] if i is not None and i < len(cells) else None
            values[name] = _float(raw) if name == "growth_rate_percent" else _int(raw)
        rows.append(ComponentsRow(scenario=found, period=period, **values))
    missing = [name for head, name in _COMPONENTS.items() if head not in index]
    return ProjectionComponents(
        release=sheet.release,
        interim=interim,
        rows=rows,
        title=sheet.title,
        notes=sheet.notes,
        resource_name=resource.name,
        url=url,
        dataset_url=constants.DATASET_URL,
        licence=_licence(lang),
        provenance=make_provenance(
            source=constants.PROVENANCE_SOURCE,
            url=url,
            cached=cached,
            schema_name="on_finance.ProjectionComponents",
            freshness=pick(
                lang,
                "Released yearly in summer, with a fall interim update.",
                "Diffusion annuelle en été, avec une mise à jour intérimaire à l'automne.",
            ),
            coverage=pick(
                lang,
                f"Ontario Ministry of Finance, {resource.name}"
                + (f" ({sheet.release})" if sheet.release else "")
                + ": components for each July-to-June period; the period starting in the "
                "file's first year begins from a Statistics Canada estimate.",
                f"Ministère des Finances de l'Ontario, {resource.name}"
                + (f" ({sheet.release})" if sheet.release else "")
                + " : composantes pour chaque période de juillet à juin ; la période qui "
                "commence la première année du fichier part d'une estimation de Statistique "
                "Canada.",
            ),
            limits=pick(
                lang,
                f"columns not found in this release: {', '.join(missing)}",
                f"colonnes absentes de cette diffusion : {', '.join(missing)}",
            )
            if missing
            else None,
            lang=lang,
        ),
    )
