"""Client for DFO commercial fisheries landings on open.canada.ca.

Confirmed live 2026-11-08:

- package_show on open.canada.ca lists each dataset's files (resource
  `url`, `language` list, `name`); the files themselves are on DFO's data
  hub, api-proxy.edh-cde.dfo-mpo.gc.ca, keyless, licence ca-ogl-lgo.
- Sea fisheries: one CSV per language (627 kB), header
  `Year,Province,Species Group,Species,Quantity (kgs),Value (CAD)` (French:
  `Année,Province,Groupe d'espèces,Espèces,Quantité (kg),Valeur (CAD)`),
  encoded cp1252. English numbers carry thousands commas and are mostly
  rounded to the unit; the French file has unrounded decimals and no commas,
  so the two languages can differ by under a dollar. Suppressed cells are
  "x". Group totals are species "Total shellfish" etc.; the species group
  "Grand total" holds the all-species total. The last rows are DFO's notes
  (source, rounding), with the note in the first cell.
- Freshwater: one wide CSV per year and language, a title and units line,
  then a header row starting " Species" with each region's name over a pair
  of columns, a Q/V row, species rows ending with "Total", then footnotes
  "(1) Includes ...". Quantity is tonnes, value thousands of dollars. The
  region headers change across years (full names to 2010; "N.S.", "N.B.",
  "N.W.T." from 2011; French "N.-E.", "N._B.", "T.-N.-O."). In the 2011 and
  2012 files the Q/V row reads "V, Q" over Nova Scotia and New Brunswick,
  but their first columns add up to the Canada quantity, so every pair is
  read as (Q, V). Numbers use commas or spaces as thousands separators;
  "-" and blank mean no landings reported, "-0" is read as zero.
- The 1991 English file has a bilingual title (two title lines); the header
  row is found by its first cell, not by position.
"""

from __future__ import annotations

import csv
import re
import unicodedata
from typing import Any

import httpx

from maplestats_mcp.modules.dfo_landings import constants
from maplestats_mcp.modules.dfo_landings.schemas import (
    Fishery,
    Landings,
    LandingsCatalogue,
    LandingsFile,
    LandingsRow,
    LandingsTable,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance, raise_localized
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import api_get, get_raw
from maplestats_mcp.shared.licences import OGL_CANADA
from maplestats_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)

ParsedRow = dict[str, Any]

# Region headers in the freshwater files -> the name used in rows.
_REGIONS_EN = {
    "N.S.": "Nova Scotia",
    "N.B.": "New Brunswick",
    "N.W.T.": "Northwest Territories",
}
_REGIONS_FR = {
    "N.-E.": "Nouvelle-Écosse",
    "N._B.": "Nouveau-Brunswick",
    "N.-B.": "Nouveau-Brunswick",
    "T.-N.-O.": "Territoires du Nord-Ouest",
    "Territoires Du Nord-Ouest": "Territoires du Nord-Ouest",
}


def _say(en: str, fr: str, lang: str) -> str:
    return fr if lang == "fr" else en


def _fold(text: str) -> str:
    """Lower case without accents, for matching user filters."""
    plain = unicodedata.normalize("NFKD", text)
    return "".join(c for c in plain if not unicodedata.combining(c)).lower().strip()


def _decode(raw: bytes) -> str:
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252")


async def _fetch_bytes(url: str, context: str, lang: str) -> bytes:
    await _LIMITER.acquire()
    try:
        response = await get_raw(url, timeout=60.0)
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status == 404:
            raise_localized(
                NotFound,
                f"dfo_landings:{context}: no file at {url}.",
                f"dfo_landings:{context} : aucun fichier à {url}.",
                lang,
            )
        raise_localized(
            UpstreamError,
            f"dfo_landings:{context}: DFO returned HTTP {status}.",
            f"dfo_landings:{context} : le MPO a renvoyé HTTP {status}.",
            lang,
        )
    except httpx.HTTPError:
        raise_localized(
            UpstreamUnavailable,
            f"dfo_landings:{context}: the file host did not respond in time.",
            f"dfo_landings:{context} : le serveur de fichiers n'a pas répondu à temps.",
            lang,
        )
    return response.content


async def _package(dataset_id: str, lang: str) -> dict[str, Any]:
    async def fetch() -> dict[str, Any]:
        await _LIMITER.acquire()
        try:
            data = await api_get(constants.CKAN_PACKAGE_SHOW, params={"id": dataset_id})
        except httpx.HTTPError:
            raise_localized(
                UpstreamUnavailable,
                "dfo_landings: open.canada.ca did not answer package_show.",
                "dfo_landings : ouvert.canada.ca n'a pas répondu à package_show.",
                lang,
            )
        result = data.get("result") if isinstance(data, dict) else None
        if not isinstance(result, dict):
            raise_localized(
                UpstreamError,
                f"dfo_landings: package_show returned no record for {dataset_id}.",
                f"dfo_landings : package_show n'a renvoyé aucune fiche pour {dataset_id}.",
                lang,
            )
        return result

    package, _ = await cached_fetch(
        f"dfo_landings:package:{dataset_id}", constants.CACHE_TTL_SECONDS, fetch
    )
    return package


def _number(text: str) -> tuple[float | None, bool]:
    """(value, suppressed) for one published cell."""
    cell = text.strip()
    if cell.lower() == "x":
        return None, True
    cleaned = cell.replace(",", "").replace(" ", "").replace(" ", "")
    if cleaned in {"", "-"}:
        return None, False
    if cleaned == "-0":
        return 0.0, False
    try:
        return float(cleaned), False
    except ValueError:
        return None, False


def _resource_language(resource: dict[str, Any]) -> str:
    languages = resource.get("language") or []
    return "fr" if languages == ["fr"] else "en"


def _year_of(resource: dict[str, Any]) -> int | None:
    match = re.search(r"(19|20)\d{2}", str(resource.get("url", "")).rsplit("/", 1)[-1])
    return int(match.group(0)) if match else None


# ------------------------------------------------------------------ parsers


def parse_sea_csv(text: str) -> tuple[list[ParsedRow], list[str]]:
    """Rows of the sea fisheries CSV (published units) and its notes."""
    rows: list[ParsedRow] = []
    notes: list[str] = []
    for cells in csv.reader(text.splitlines()):
        if not cells or not any(c.strip() for c in cells):
            continue
        first = cells[0].strip()
        if not re.fullmatch(r"\d{4}", first):
            if first and not first.startswith(("Year", "Année")):
                notes.extend(c.strip() for c in cells if c.strip())
            continue
        if len(cells) < 6:
            continue
        quantity, q_hidden = _number(cells[4])
        value, v_hidden = _number(cells[5])
        group = cells[2].strip()
        species = cells[3].strip()
        rows.append(
            {
                "year": int(first),
                "region": cells[1].strip(),
                "species_group": group,
                "species": species,
                "quantity_tonnes": round(quantity / 1000, 3) if quantity is not None else None,
                "value_dollars": value,
                "suppressed": q_hidden or v_hidden,
                "is_total": _fold(species).startswith("total") or _fold(group) == "grand total",
            }
        )
    return rows, list(dict.fromkeys(notes))


def parse_freshwater_csv(text: str, year: int, lang: str) -> tuple[list[ParsedRow], list[str]]:
    """Tidy rows of one freshwater year file (published units converted) and its footnotes."""
    table = list(csv.reader(text.splitlines()))
    header_at = next(
        (
            i
            for i, cells in enumerate(table)
            if cells and _fold(cells[0]) in {"species", "especes", "espece"}
        ),
        None,
    )
    if header_at is None:
        raise ValueError("no Species header row")
    header = table[header_at]
    names = _REGIONS_FR if lang == "fr" else _REGIONS_EN
    # Each region name sits over its (Q, V) pair; see the module docstring
    # for why the Q/V row itself is not trusted.
    regions = [
        (index, names.get(cell.strip(), cell.strip()))
        for index, cell in enumerate(header)
        if index > 0 and cell.strip()
    ]
    rows: list[ParsedRow] = []
    notes: list[str] = []
    for cells in table[header_at + 2 :]:
        if not cells or not any(c.strip() for c in cells):
            continue
        label = cells[0].strip()
        if re.match(r"^\(\d+\)", label):
            # Usually one quoted cell; an unquoted footnote spills over commas.
            notes.append(" ".join(", ".join(c.strip() for c in cells if c.strip()).split()))
            continue
        if not label:
            continue
        species = re.sub(r"\s*\(\d+\)\s*$", "", label)
        for index, region in regions:
            q_cell = cells[index] if index < len(cells) else ""
            v_cell = cells[index + 1] if index + 1 < len(cells) else ""
            quantity, q_hidden = _number(q_cell)
            value, v_hidden = _number(v_cell)
            if quantity is None and value is None and not (q_hidden or v_hidden):
                continue  # nothing reported for this region
            rows.append(
                {
                    "year": year,
                    "region": region,
                    "species_group": None,
                    "species": species,
                    "quantity_tonnes": quantity,
                    "value_dollars": value * 1000 if value is not None else None,
                    "suppressed": q_hidden or v_hidden,
                    "is_total": _fold(species) == "total",
                }
            )
    return rows, notes


# ------------------------------------------------------------------- tools


def _dataset_id(fishery: Fishery) -> str:
    return constants.SEA_DATASET_ID if fishery == "sea" else constants.FRESHWATER_DATASET_ID


def _page(dataset_id: str, lang: str) -> str:
    template = constants.DATASET_PAGE_FR if lang == "fr" else constants.DATASET_PAGE_EN
    return template.format(id=dataset_id)


async def list_tables(*, lang: str = "en") -> LandingsCatalogue:
    tables: list[LandingsTable] = []
    for fishery in ("sea", "freshwater"):
        dataset_id = _dataset_id(fishery)  # type: ignore[arg-type]
        package = await _package(dataset_id, lang)
        files = [
            LandingsFile(
                year=_year_of(r) if fishery == "freshwater" else None,
                language=_resource_language(r),
                url=str(r.get("url", "")),
            )
            for r in package.get("resources") or []
            if str(r.get("format", "")).upper() == "CSV"
            and "dictionary" not in str(r.get("name", "")).lower()
        ]
        if fishery == "freshwater":
            years = [f.year for f in files if f.year is not None]
            first, last = (min(years), max(years)) if years else (None, None)
        else:
            first = _year_text(package.get("time_period_coverage_start"))
            last = _year_text(package.get("time_period_coverage_end"))
        title = package.get("title_translated", {}).get(lang) or package.get("title", "")
        tables.append(
            LandingsTable(
                fishery=fishery,  # type: ignore[arg-type]
                title=str(title),
                dataset_id=dataset_id,
                dataset_url=_page(dataset_id, lang),
                first_year=first,
                last_year=last,
                quantity_unit_published=(
                    _say("kilograms, live weight", "kilogrammes, poids vif", lang)
                    if fishery == "sea"
                    else _say("tonnes, live weight", "tonnes, poids vif", lang)
                ),
                value_unit_published=(
                    _say("dollars", "dollars", lang)
                    if fishery == "sea"
                    else _say("thousands of dollars", "milliers de dollars", lang)
                ),
                regions=(
                    _say(
                        "Atlantic total, NL, PE, NS, NB, QC, BC and Canada",
                        "total de l'Atlantique, T.-N.-L., Î.-P.-É., N.-É., N.-B., Qc, C.-B. et "
                        "Canada",
                        lang,
                    )
                    if fishery == "sea"
                    else _say(
                        "NS, NB, QC, ON, MB, SK, AB, NU, NT and Canada (varies by year)",
                        "N.-É., N.-B., Qc, Ont., Man., Sask., Alb., Nt, T.N.-O. et Canada (selon "
                        "l'année)",
                        lang,
                    )
                ),
                files=sorted(files, key=lambda f: (f.year or 0, f.language)),
                last_modified=package.get("metadata_modified"),
            )
        )
    return LandingsCatalogue(
        tables=tables,
        provenance=make_provenance(
            source=constants.SOURCE,
            url=f"{constants.CKAN_PACKAGE_SHOW}?id={constants.SEA_DATASET_ID}",
            cached=False,
            schema_name="dfo_landings.LandingsCatalogue",
            freshness=_say(
                "annual; sea fisheries to 2024, freshwater to 2019",
                "annuelle ; pêches maritimes jusqu'en 2024, eau douce jusqu'en 2019",
                lang,
            ),
            licence=OGL_CANADA,
            lang=lang,
        ),
    )


def _year_text(value: Any) -> int | None:
    match = re.match(r"(\d{4})", str(value or ""))
    return int(match.group(1)) if match else None


def _pick_file(package: dict[str, Any], lang: str, year: int | None = None) -> str | None:
    candidates = [
        r
        for r in package.get("resources") or []
        if str(r.get("format", "")).upper() == "CSV"
        and "dictionary" not in str(r.get("name", "")).lower()
        and (year is None or _year_of(r) == year)
    ]
    wanted = [r for r in candidates if _resource_language(r) == lang]
    chosen = (wanted or candidates)[:1]
    return str(chosen[0]["url"]) if chosen else None


def _check_years(
    year: int | None, start_year: int | None, end_year: int | None, lang: str
) -> tuple[int | None, int | None]:
    if year is not None and (start_year is not None or end_year is not None):
        raise_localized(
            InvalidInput,
            "Pass year, or start_year and end_year, not both.",
            "Indiquez year, ou start_year et end_year, pas les deux.",
            lang,
        )
    first = year if year is not None else start_year
    last = year if year is not None else end_year
    if first is not None and last is not None and last < first:
        raise_localized(
            InvalidInput,
            f"end_year {last} is before start_year {first}.",
            f"end_year {last} précède start_year {first}.",
            lang,
        )
    return first, last


def _matches(row: ParsedRow, region: str | None, species: str | None, group: str | None) -> bool:
    if region and _fold(region) not in _fold(row["region"]):
        return False
    if species and _fold(species) not in _fold(row["species"]):
        return False
    return not (group and _fold(group) not in _fold(row["species_group"] or ""))


async def get_landings(
    fishery: Fishery = "sea",
    year: int | None = None,
    start_year: int | None = None,
    end_year: int | None = None,
    region: str | None = None,
    species: str | None = None,
    species_group: str | None = None,
    include_totals: bool = True,
    limit: int = constants.DEFAULT_LIMIT,
    *,
    lang: str = "en",
) -> Landings:
    if not 1 <= limit <= constants.MAX_LIMIT:
        raise_localized(
            InvalidInput,
            f"limit must be between 1 and {constants.MAX_LIMIT}, got {limit}.",
            f"limit doit être compris entre 1 et {constants.MAX_LIMIT}, reçu {limit}.",
            lang,
        )
    if species_group and fishery == "freshwater":
        raise_localized(
            InvalidInput,
            "species_group applies to sea fisheries only.",
            "species_group ne s'applique qu'aux pêches maritimes.",
            lang,
        )
    first, last = _check_years(year, start_year, end_year, lang)
    dataset_id = _dataset_id(fishery)
    package = await _package(dataset_id, lang)
    notes: list[str] = []
    all_rows: list[ParsedRow] = []
    urls: list[str] = []

    if fishery == "sea":
        url = _pick_file(package, lang)
        if url is None:
            raise_localized(
                NotFound,
                "dfo_landings: the sea fisheries record lists no CSV file.",
                "dfo_landings : la fiche des pêches maritimes ne liste aucun fichier CSV.",
                lang,
            )

        async def fetch_sea() -> tuple[list[ParsedRow], list[str]]:
            return parse_sea_csv(_decode(await _fetch_bytes(url, "sea", lang)))

        (parsed, notes), _ = await cached_fetch(
            f"dfo_landings:sea:{lang}", constants.CACHE_TTL_SECONDS, fetch_sea
        )
        urls.append(url)
        available = sorted({r["year"] for r in parsed})
        if not available:
            raise_localized(
                UpstreamError,
                "dfo_landings: the sea fisheries file had no rows.",
                "dfo_landings : le fichier des pêches maritimes n'avait aucune ligne.",
                lang,
            )
        if first is None and last is None:
            first = last = available[-1]
        first = first if first is not None else available[0]
        last = last if last is not None else available[-1]
        all_rows = [r for r in parsed if first <= r["year"] <= last]
        years = [y for y in available if first <= y <= last]
    else:
        by_year = {
            _year_of(r): r
            for r in package.get("resources") or []
            if str(r.get("format", "")).upper() == "CSV" and _year_of(r) is not None
        }
        available = sorted(y for y in by_year if y is not None)
        if not available:
            raise_localized(
                UpstreamError,
                "dfo_landings: the freshwater record lists no yearly files.",
                "dfo_landings : la fiche des pêches en eau douce ne liste aucun fichier annuel.",
                lang,
            )
        if first is None and last is None:
            first = last = available[-1]
        first = first if first is not None else available[0]
        last = last if last is not None else available[-1]
        years = [y for y in available if first <= y <= last]
        if len(years) > constants.MAX_FRESHWATER_YEARS:
            raise_localized(
                InvalidInput,
                f"At most {constants.MAX_FRESHWATER_YEARS} freshwater years per call (one file "
                f"each); got {len(years)}.",
                f"Au plus {constants.MAX_FRESHWATER_YEARS} années d'eau douce par appel (un "
                f"fichier chacune) ; reçu {len(years)}.",
                lang,
            )
        for one_year in years:
            url = _pick_file(package, lang, one_year)
            if url is None:
                continue

            async def fetch_year(
                url: str = url, one_year: int = one_year
            ) -> tuple[list[ParsedRow], list[str]]:
                text = _decode(await _fetch_bytes(url, f"freshwater_{one_year}", lang))
                try:
                    return parse_freshwater_csv(text, one_year, lang)
                except ValueError:
                    raise_localized(
                        UpstreamError,
                        f"dfo_landings: the {one_year} freshwater file has no Species header.",
                        f"dfo_landings : le fichier d'eau douce {one_year} n'a pas d'en-tête "
                        "Species.",
                        lang,
                    )

            (rows, file_notes), _ = await cached_fetch(
                f"dfo_landings:freshwater:{one_year}:{lang}",
                constants.CACHE_TTL_SECONDS,
                fetch_year,
            )
            urls.append(url)
            all_rows.extend(rows)
            notes.extend(n for n in file_notes if n not in notes)

    if not years:
        raise_localized(
            NotFound,
            f"No {fishery} landings for {first}-{last}; available {available[0]}-{available[-1]}.",
            f"Aucun débarquement ({fishery}) pour {first}-{last} ; offert de {available[0]} à "
            f"{available[-1]}.",
            lang,
        )
    matched = [
        r
        for r in all_rows
        if _matches(r, region, species, species_group) and (include_totals or not r["is_total"])
    ]
    return Landings(
        fishery=fishery,
        years=years,
        rows=[LandingsRow(**r) for r in matched[:limit]],
        rows_matched=len(matched),
        notes=notes,
        provenance=make_provenance(
            source=constants.SOURCE,
            url=urls[0] if urls else _page(dataset_id, lang),
            cached=False,
            schema_name="dfo_landings.Landings",
            freshness=_say(
                "annual; DFO may revise past years",
                "annuelle ; le MPO peut réviser les années passées",
                lang,
            ),
            coverage=_say(
                "sea fisheries 1990-2024 by Atlantic province and BC; freshwater 1990-2019",
                "pêches maritimes 1990-2024 par province de l'Atlantique et C.-B. ; eau douce "
                "1990-2019",
                lang,
            ),
            limits=_say(
                f"Rows capped at {limit}; {len(matched)} matched. Sea quantities are DFO's "
                "kilograms divided by 1,000; freshwater values are DFO's thousands of dollars "
                "times 1,000. Suppressed cells ('x') are null with suppressed=true. Dataset: "
                f"{_page(dataset_id, lang)}",
                f"Lignes plafonnées à {limit} ; {len(matched)} correspondent. Les quantités "
                "maritimes sont les kilogrammes du MPO divisés par 1 000 ; les valeurs en eau "
                "douce sont les milliers de dollars du MPO multipliés par 1 000. Les cellules "
                "confidentielles ('x') sont nulles avec suppressed=true. Jeu de données : "
                f"{_page(dataset_id, lang)}",
                lang,
            ),
            licence=OGL_CANADA,
            lang=lang,
        ),
    )
