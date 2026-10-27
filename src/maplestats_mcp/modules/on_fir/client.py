"""Ontario's municipal Financial Information Return (FIR), from the Ministry's yearly CSVs.

The Ministry of Municipal Affairs and Housing posts one ZIP per year,
2000 to the newest, on "FIR Data By Year - .CSV Format" (MYCIndex.html,
read from the 2026-09-09 copy: 26 rows, each with the year, its last
update and posting dates as YYYYMMDD and a relative link to
fir_data_<year>.zip). Every file carries the labels itself (schedule,
sub-schedule, line and column descriptions next to each SLC code), so no
FIR template is needed. Labels are English only.

A year's file holds only the returns filed so far: the 2025 file had 2
municipalities in March 2026 and the 2023 file 364 of 444 in April 2025.
Every result says how many filed, so a comparison across municipalities
is not read as complete when it is not.

The whole year is downloaded once (about 10 MB) and kept as Parquet (see
store.py); every query after that is local.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from maplestats_mcp.modules.on_fir import constants, store
from maplestats_mcp.modules.on_fir.schemas import (
    ComparisonResult,
    ComparisonRow,
    FirYear,
    Line,
    LineSearch,
    Municipality,
    MunicipalitySearch,
    Schedule,
    ScheduleList,
    ScheduleResult,
    ScheduleValue,
)
from maplestats_mcp.shared import duck
from maplestats_mcp.shared.arg_checks import format_choices
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance, raise_localized
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError
from maplestats_mcp.shared.executor import run_in_pool
from maplestats_mcp.shared.fr_typography import fr_or_en, truncation_note_lang
from maplestats_mcp.shared.http import get_raw
from maplestats_mcp.shared.models import Provenance
from maplestats_mcp.shared.rate_limiter import get_limiter

_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
_CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.IGNORECASE | re.DOTALL)
_ZIP_LINK = re.compile(r'href="([^"]*fir_data_(\d{4})\.zip)"', re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")
_SLC = re.compile(r"slc\.[0-9]{2}[A-Z]\.L[0-9]{4}\.C[0-9]{2}\.[0-9A-Z]{2}")
_SCHEDULE = re.compile(r"[0-9]{2}[A-Z]")


def _iso(stamp: str | None) -> str | None:
    if stamp and re.fullmatch(r"\d{8}", stamp):
        return f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}"
    return None


def parse_index(html: str) -> list[FirYear]:
    """The years listed on MYCIndex.html, newest first."""
    years: dict[int, FirYear] = {}
    for row in _ROW.findall(html):
        link = _ZIP_LINK.search(row)
        if not link:
            continue
        cells = [_TAG.sub("", cell).strip() for cell in _CELL.findall(row)]
        dates = [cell for cell in cells if re.fullmatch(r"\d{8}", cell)]
        year = int(link.group(2))
        years[year] = FirYear(
            year=year,
            last_updated=_iso(dates[0]) if dates else None,
            posted=_iso(dates[1]) if len(dates) > 1 else None,
            url=constants.ZIP_URL.format(year=year),
        )
    return sorted(years.values(), key=lambda item: item.year, reverse=True)


async def list_years(lang: str = "en") -> tuple[list[FirYear], bool]:
    async def fetch() -> list[FirYear]:
        await get_limiter(
            constants.RATE_LIMIT_SOURCE,
            constants.RATE_LIMIT_PER_SECOND,
            constants.RATE_LIMIT_CAPACITY,
        ).acquire()
        response = await get_raw(constants.INDEX_URL, timeout=60.0)
        years = parse_index(response.text)
        if not years:
            raise_localized(
                UpstreamError,
                f"on_fir: {constants.INDEX_URL} lists no yearly FIR files; the page has changed.",
                f"on_fir : {constants.INDEX_URL} ne liste aucun fichier annuel du RIF ; la page "
                "a changé.",
                lang,
            )
        return years

    return await cached_fetch("on_fir:index", constants.INDEX_TTL_SECONDS, fetch)


def _default_year(years: list[FirYear]) -> FirYear:
    # The newest year fills in over the following year (2 returns by March
    # 2026 for 2025), so a call without a year reads the one before it.
    return years[1] if len(years) > 1 else years[0]


def _pick_year(years: list[FirYear], year: int | None, lang: str) -> FirYear:
    if year is None:
        return _default_year(years)
    for item in years:
        if item.year == year:
            return item
    raise_localized(
        NotFound,
        f"on_fir: no FIR file for {year}. Years published: "
        f"{format_choices([y.year for y in years])}.",
        f"on_fir : aucun fichier du RIF pour {year}. Années publiées : "
        f"{format_choices([y.year for y in years], 'fr')}.",
        lang,
    )


async def _year_file(year: int | None, lang: str) -> tuple[FirYear, Path, list[FirYear], bool]:
    years, cached = await list_years(lang)
    chosen = _pick_year(years, year, lang)
    path = await store.local_year(chosen.year, chosen.url, chosen.last_updated)
    return chosen, path, years, cached


def _query(path: Path | list[Path], sql: str, params: list[Any]) -> list[tuple[Any, ...]]:
    paths = path if isinstance(path, list) else [path]
    files = ", ".join("'" + str(p).replace("\\", "/").replace("'", "''") + "'" for p in paths)
    with duck.connect() as connection:
        connection.execute(f"CREATE VIEW fir AS SELECT * FROM read_parquet([{files}])")
        return connection.execute(sql, params).fetchall()


async def _run(path: Path | list[Path], sql: str, params: list[Any]) -> list[tuple[Any, ...]]:
    return await run_in_pool(_query, path, sql, params)


def _as_of(stamp: str | None) -> datetime | None:
    return datetime.fromisoformat(stamp).replace(tzinfo=UTC) if stamp else None


def _coverage(year: int, filed: int, newest: int, lang: str) -> str:
    total = constants.ONTARIO_MUNICIPALITIES
    if filed >= total:
        # Older years count more: the 2005 file has 445 municipalities.
        english = f"{filed} municipalities have a {year} return in the file."
        french = f"{filed} municipalités ont une déclaration {year} au fichier."
    else:
        english = f"{filed} of Ontario's {total} municipalities have a {year} return in the file."
        french = (
            f"{filed} des {total} municipalités de l'Ontario ont une déclaration {year} au fichier."
        )
    if year == newest or filed < total - 10:
        english += (
            " Returns are due May 31 of the following year and are added as they are filed and "
            "reviewed, so a recent year is incomplete until every return is in."
        )
        french += (
            " Les déclarations sont dues le 31 mai de l'année suivante et sont ajoutées à mesure "
            "qu'elles sont déposées et vérifiées : une année récente reste incomplète tant que "
            "toutes ne sont pas reçues."
        )
    return fr_or_en(lang, english, french)


def _provenance(
    schema: str,
    url: str,
    cached: bool,
    lang: str,
    *,
    as_of: str | None = None,
    coverage: str | None = None,
    limits: str | None = None,
) -> Provenance:
    return make_provenance(
        source=constants.SOURCE,
        url=url,
        cached=cached,
        schema_name=f"on_fir.{schema}",
        as_of=_as_of(as_of),
        freshness=fr_or_en(
            lang,
            "Yearly files, re-posted as returns are filed and revised; labels in English only.",
            "Fichiers annuels, republiés à mesure que les déclarations sont déposées et "
            "révisées ; libellés en anglais seulement.",
        ),
        coverage=coverage,
        limits=limits,
        lang=lang,
    )


async def _filed(path: Path) -> int:
    rows = await _run(path, "SELECT count(DISTINCT munid) FROM fir", [])
    return int(rows[0][0])


async def list_schedules(year: int | None = None, *, lang: str = "en") -> ScheduleList:
    chosen, path, years, cached = await _year_file(year, lang)
    rows = await _run(
        path,
        "SELECT schedule, any_value(schedule_desc), "
        "list(DISTINCT sub_schedule ORDER BY sub_schedule) FILTER (WHERE sub_schedule IS NOT NULL), "
        "count(DISTINCT line), count(DISTINCT slc) FROM fir GROUP BY schedule ORDER BY schedule",
        [],
    )
    filed = await _filed(path)
    return ScheduleList(
        year=chosen.year,
        municipalities_filed=filed,
        years=years,
        schedules=[
            Schedule(
                code=code,
                name=name,
                sub_schedules=list(subs or []),
                lines=int(lines),
                data_points=int(points),
            )
            for code, name, subs, lines, points in rows
        ],
        provenance=_provenance(
            "ScheduleList",
            chosen.url,
            cached,
            lang,
            as_of=chosen.last_updated,
            coverage=_coverage(chosen.year, filed, years[0].year, lang),
        ),
    )


_MUNICIPALITY_SQL = """
SELECT munid, any_value(municipality), any_value(tier), any_value(mtype), any_value(ut_number),
       any_value(assessment_code), any_value(sgc_code), any_value(mso),
       max(amount) FILTER (WHERE slc = ?), max(amount) FILTER (WHERE slc = ?),
       max(last_update)
FROM fir {where}
GROUP BY munid
ORDER BY any_value(municipality)
"""


def _municipality(row: tuple[Any, ...], lang: str) -> Municipality:
    munid, name, tier, mtype, ut_number, assessment, sgc, mso, population, households, updated = row
    tier_names = constants.TIER_NAMES.get(tier or "", (tier or "", tier or ""))
    mtype_names = constants.MUNICIPAL_TYPES.get(mtype or "")
    mso_names = constants.MSO_NAMES.get(mso or "")
    return Municipality(
        munid=munid,
        name=name,
        tier=tier or "",
        tier_name=fr_or_en(lang, *tier_names),
        municipal_type=fr_or_en(lang, *mtype_names) if mtype_names else mtype,
        upper_tier_number=ut_number,
        assessment_code=assessment,
        sgc_code=sgc,
        service_office=fr_or_en(lang, *mso_names) if mso_names else mso,
        population=population,
        households=households,
        last_updated=_iso(updated),
    )


def _fold_sql(column: str) -> str:
    return f"strip_accents(lower({column}))"


def _words(query: str) -> list[str]:
    return [word for word in re.split(r"\s+", query.strip().lower()) if word]


async def _municipalities(path: Path, where: str, params: list[Any]) -> list[tuple[Any, ...]]:
    sql = _MUNICIPALITY_SQL.format(where=where)
    return await _run(path, sql, [constants.POPULATION_SLC, constants.HOUSEHOLDS_SLC, *params])


async def search_municipalities(
    query: str = "",
    year: int | None = None,
    tier: str | None = None,
    limit: int = constants.DEFAULT_SEARCH_LIMIT,
    *,
    lang: str = "en",
) -> MunicipalitySearch:
    limit = max(1, min(limit, constants.MAX_SEARCH_LIMIT))
    chosen, path, years, cached = await _year_file(year, lang)
    clauses: list[str] = []
    params: list[Any] = []
    for word in _words(query):
        if word.isdigit():
            clauses.append("(munid = ? OR assessment_code = ?)")
            params += [word.lstrip("0") or "0", word.zfill(4)]
        else:
            clauses.append(f"{_fold_sql('municipality')} LIKE '%' || strip_accents(?) || '%'")
            params.append(word)
    if tier:
        clauses.append("tier = ?")
        params.append(_tier(tier, lang))
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = await _municipalities(path, where, params)
    filed = await _filed(path)
    return MunicipalitySearch(
        query=query,
        year=chosen.year,
        total=len(rows),
        municipalities=[_municipality(row, lang) for row in rows[:limit]],
        provenance=_provenance(
            "MunicipalitySearch",
            chosen.url,
            cached,
            lang,
            as_of=chosen.last_updated,
            coverage=_coverage(chosen.year, filed, years[0].year, lang),
            limits=truncation_note_lang(
                lang,
                returned=min(limit, len(rows)),
                total=len(rows),
                unit="municipalities",
                unit_fr="municipalités",
            ),
        ),
    )


def _tier(tier: str, lang: str) -> str:
    wanted = tier.strip().upper()
    if wanted not in constants.TIER_NAMES:
        raise_localized(
            InvalidInput,
            f"tier {tier!r} is not one of UT (upper tier), LT (lower tier), ST (single tier).",
            f"tier {tier!r} n'est pas UT (palier supérieur), LT (palier inférieur) ou ST "
            "(palier unique).",
            lang,
        )
    return wanted


async def _resolve(path: Path, municipality: str, year: int, lang: str) -> Municipality:
    wanted = municipality.strip()
    if not wanted:
        raise_localized(
            InvalidInput,
            "municipality must be a MUNID or a name.",
            "municipality doit être un MUNID ou un nom.",
            lang,
        )
    if wanted.isdigit():
        rows = await _municipalities(path, "WHERE munid = ?", [wanted.lstrip("0") or "0"])
    else:
        folded = wanted.lower()
        rows = await _municipalities(
            path,
            f"WHERE {_fold_sql('municipality')} = strip_accents(?) "
            f"OR {_fold_sql('municipality')} LIKE strip_accents(?) || ' %'",
            [folded, folded],
        )
        if not rows:
            rows = await _municipalities(
                path,
                f"WHERE {_fold_sql('municipality')} LIKE '%' || strip_accents(?) || '%'",
                [folded],
            )
    if not rows:
        raise_localized(
            NotFound,
            f"on_fir: no {year} return for {municipality!r}. Find the MUNID with "
            "on_fir_search_municipalities; the municipality may not have filed yet.",
            f"on_fir : aucune déclaration {year} pour {municipality!r}. Trouvez le MUNID avec "
            "on_fir_search_municipalities ; la municipalité n'a peut-être pas encore déposé.",
            lang,
        )
    if len(rows) > 1:
        names = [f"{row[1]} ({row[0]})" for row in rows]
        raise_localized(
            InvalidInput,
            f"on_fir: {municipality!r} matches {len(rows)} municipalities: "
            f"{format_choices(names)}. Pass the MUNID.",
            f"on_fir : {municipality!r} correspond à {len(rows)} municipalités : "
            f"{format_choices(names, 'fr')}. Indiquez le MUNID.",
            lang,
        )
    return _municipality(rows[0], lang)


def _schedule_filter(schedule: str, lang: str) -> tuple[str, str, str]:
    """(SQL clause, its parameter, the code as shown) for a schedule argument.

    A bare number matches every part of the schedule: 26 is filed as 26A and
    26B, 51 as 51A and 51B, 74 as 74A to 74E, 80 as 80A, 80C and 80D.
    """
    code = schedule.strip().upper()
    if re.fullmatch(r"[0-9]{1,2}", code):
        code = code.zfill(2)
        return "schedule LIKE ?", code + "_", code
    if not _SCHEDULE.fullmatch(code):
        raise_localized(
            InvalidInput,
            f"schedule {schedule!r} is not a schedule code such as '40', '40X' or '26A'.",
            f"schedule {schedule!r} n'est pas un code d'annexe comme '40', '40X' ou '26A'.",
            lang,
        )
    return "schedule = ?", code, code


async def search_lines(
    query: str,
    year: int | None = None,
    schedule: str | None = None,
    limit: int = constants.DEFAULT_SEARCH_LIMIT,
    *,
    lang: str = "en",
) -> LineSearch:
    limit = max(1, min(limit, constants.MAX_SEARCH_LIMIT))
    words = _words(query)
    if not words and not schedule:
        raise_localized(
            InvalidInput,
            "Give a query (words in the line or column label) or a schedule.",
            "Indiquez une requête (mots du libellé de ligne ou de colonne) ou une annexe.",
            lang,
        )
    chosen, path, years, cached = await _year_file(year, lang)
    label = _fold_sql(
        "concat_ws(' ', schedule_desc, sub_schedule, line_desc, column_desc, slc, line)"
    )
    clauses = [f"{label} LIKE '%' || strip_accents(?) || '%'" for _ in words]
    params: list[Any] = list(words)
    if schedule:
        clause, param, _ = _schedule_filter(schedule, lang)
        clauses.append(clause)
        params.append(param)
    sql = (
        "SELECT slc, schedule, any_value(schedule_desc), any_value(sub_schedule), any_value(line), "
        "any_value(line_desc), any_value(col), any_value(column_desc), any_value(datatype), "
        "count(DISTINCT munid) FILTER (WHERE amount IS NOT NULL OR value_text IS NOT NULL) "
        f"FROM fir WHERE {' AND '.join(clauses)} GROUP BY slc, schedule ORDER BY slc"
    )
    rows = await _run(path, sql, params)
    filed = await _filed(path)
    return LineSearch(
        query=query,
        year=chosen.year,
        total=len(rows),
        lines=[
            Line(
                slc=slc,
                schedule=code,
                schedule_name=name,
                sub_schedule=sub,
                line=line,
                line_desc=line_desc,
                column=col,
                column_desc=column_desc,
                datatype=datatype,
                municipalities=int(count),
            )
            for slc, code, name, sub, line, line_desc, col, column_desc, datatype, count in rows[
                :limit
            ]
        ],
        provenance=_provenance(
            "LineSearch",
            chosen.url,
            cached,
            lang,
            as_of=chosen.last_updated,
            coverage=_coverage(chosen.year, filed, years[0].year, lang),
            limits=truncation_note_lang(
                lang,
                returned=min(limit, len(rows)),
                total=len(rows),
                unit="data points",
                unit_fr="points de données",
                how_to_get_more="add words or a schedule to narrow the search",
                how_to_get_more_fr="ajoutez des mots ou une annexe pour préciser la recherche",
            ),
        ),
    )


async def get_schedule(
    municipality: str,
    schedule: str,
    year: int | None = None,
    line: str | None = None,
    *,
    lang: str = "en",
) -> ScheduleResult:
    clause, param, code = _schedule_filter(schedule, lang)
    chosen, path, _years, cached = await _year_file(year, lang)
    found = await _resolve(path, municipality, chosen.year, lang)
    clauses = ["munid = ?", clause, "(amount IS NOT NULL OR value_text IS NOT NULL)"]
    params: list[Any] = [found.munid, param]
    if line:
        clauses.append("line = ?")
        params.append(line.strip().upper().removeprefix("L").zfill(4))
    rows = await _run(
        path,
        "SELECT slc, sub_schedule, line, line_desc, col, column_desc, datatype, amount, "
        f"value_text, schedule_desc FROM fir WHERE {' AND '.join(clauses)} ORDER BY slc",
        params,
    )
    if not rows:
        schedules = await _run(
            path, "SELECT DISTINCT schedule FROM fir WHERE munid = ? ORDER BY 1", [found.munid]
        )
        raise_localized(
            NotFound,
            f"on_fir: {found.name} reported nothing on schedule {code}"
            f"{f' line {line}' if line else ''} for {chosen.year}. Schedules it filed: "
            f"{format_choices([s[0] for s in schedules])}.",
            f"on_fir : {found.name} n'a rien déclaré à l'annexe {code}"
            f"{f' ligne {line}' if line else ''} pour {chosen.year}. Annexes déposées : "
            f"{format_choices([s[0] for s in schedules], 'fr')}.",
            lang,
        )
    cap = constants.MAX_SCHEDULE_ROWS
    return ScheduleResult(
        municipality=found,
        year=chosen.year,
        schedule=code,
        schedule_name=rows[0][9],
        total=len(rows),
        values=[
            ScheduleValue(
                slc=slc,
                sub_schedule=sub,
                line=line_code,
                line_desc=line_desc,
                column=col,
                column_desc=column_desc,
                datatype=datatype,
                amount=amount,
                text=text,
            )
            for slc, sub, line_code, line_desc, col, column_desc, datatype, amount, text, _ in rows[
                :cap
            ]
        ],
        provenance=_provenance(
            "ScheduleResult",
            chosen.url,
            cached,
            lang,
            as_of=found.last_updated or chosen.last_updated,
            limits=truncation_note_lang(
                lang,
                returned=min(cap, len(rows)),
                total=len(rows),
                unit="data points",
                unit_fr="points de données",
                how_to_get_more="pass line to read one line",
                how_to_get_more_fr="indiquez line pour lire une seule ligne",
            ),
        ),
    )


async def compare(
    slc: str,
    years: list[int] | None = None,
    municipalities: list[str] | None = None,
    tier: str | None = None,
    per_capita: bool = False,
    limit: int = constants.DEFAULT_COMPARE_LIMIT,
    *,
    lang: str = "en",
) -> ComparisonResult:
    code = slc.strip()
    if not code.lower().startswith("slc."):
        code = "slc." + code
    code = "slc." + code[4:].upper()
    if not _SLC.fullmatch(code):
        raise_localized(
            InvalidInput,
            f"slc {slc!r} is not a FIR data point code such as 'slc.40X.L0420.C01.11'. Find one "
            "with on_fir_search_lines or on_fir_get_schedule.",
            f"slc {slc!r} n'est pas un code de point de données du RIF comme "
            "'slc.40X.L0420.C01.11'. Trouvez-en un avec on_fir_search_lines ou "
            "on_fir_get_schedule.",
            lang,
        )
    limit = max(1, min(limit, constants.MAX_COMPARE_LIMIT))
    wanted_years = sorted(set(years or []), reverse=True)
    if len(wanted_years) > constants.MAX_COMPARE_YEARS:
        raise_localized(
            InvalidInput,
            f"Compare at most {constants.MAX_COMPARE_YEARS} years per call "
            f"({len(wanted_years)} given).",
            f"Comparez au plus {constants.MAX_COMPARE_YEARS} années par appel "
            f"({len(wanted_years)} indiquées).",
            lang,
        )
    if municipalities and len(municipalities) > constants.MAX_COMPARE_MUNICIPALITIES:
        raise_localized(
            InvalidInput,
            f"Name at most {constants.MAX_COMPARE_MUNICIPALITIES} municipalities per call, or "
            "leave municipalities out to rank all of them.",
            f"Nommez au plus {constants.MAX_COMPARE_MUNICIPALITIES} municipalités par appel, ou "
            "omettez municipalities pour les classer toutes.",
            lang,
        )
    index, cached = await list_years(lang)
    chosen = [_pick_year(index, year, lang) for year in wanted_years] or [_default_year(index)]
    paths = [await store.local_year(y.year, y.url, y.last_updated) for y in chosen]

    munids: list[str] = []
    for name in municipalities or []:
        # A name resolves against the newest chosen year that has it.
        found: Municipality | None = None
        for item, path in zip(chosen, paths, strict=True):
            try:
                found = await _resolve(path, name, item.year, lang)
                break
            except NotFound:
                continue
        if found is None:
            raise_localized(
                NotFound,
                f"on_fir: {name!r} has no return in "
                f"{', '.join(str(y.year) for y in chosen)}. Check the name or MUNID with "
                "on_fir_search_municipalities.",
                f"on_fir : {name!r} n'a pas de déclaration en "
                f"{', '.join(str(y.year) for y in chosen)}. Vérifiez le nom ou le MUNID avec "
                "on_fir_search_municipalities.",
                lang,
            )
        munids.append(found.munid)

    clauses = ["v.slc = ?", "(v.amount IS NOT NULL OR v.value_text IS NOT NULL)"]
    params: list[Any] = [constants.POPULATION_SLC, code]
    if munids:
        clauses.append(f"v.munid IN ({', '.join('?' for _ in munids)})")
        params += munids
    if tier:
        clauses.append("v.tier = ?")
        params.append(_tier(tier, lang))
    if munids:
        order = "v.municipality, v.year DESC"
    elif per_capita:
        order = "v.year DESC, per_capita DESC NULLS LAST, v.amount DESC NULLS LAST"
    else:
        order = "v.year DESC, v.amount DESC NULLS LAST"
    sql = f"""
        WITH pop AS (SELECT year, munid, amount AS population FROM fir WHERE slc = ?)
        SELECT v.year, v.munid, v.municipality, v.tier, v.amount, v.value_text, p.population,
               CASE WHEN p.population > 0 THEN v.amount / p.population END AS per_capita,
               v.schedule_desc, v.line_desc, v.column_desc, v.datatype
        FROM fir v LEFT JOIN pop p ON p.year = v.year AND p.munid = v.munid
        WHERE {" AND ".join(clauses)}
        ORDER BY {order}
    """
    rows = await _run(paths, sql, params)
    if not rows:
        raise_localized(
            NotFound,
            f"on_fir: no municipality reported {code} in "
            f"{', '.join(str(y.year) for y in chosen)}"
            f"{' for the municipalities named' if munids else ''}. Check the code with "
            "on_fir_search_lines for that year: line numbers change between FIR templates.",
            f"on_fir : aucune municipalité n'a déclaré {code} en "
            f"{', '.join(str(y.year) for y in chosen)}"
            f"{' pour les municipalités nommées' if munids else ''}. Vérifiez le code avec "
            "on_fir_search_lines pour cette année : les numéros de ligne changent d'un gabarit "
            "du RIF à l'autre.",
            lang,
        )
    labels: dict[int, tuple[str | None, str | None]] = {}
    for row in rows:
        labels.setdefault(row[0], (row[9], row[10]))
    newest = labels[max(labels)]
    changes = [
        f"{year}: {line_desc} / {column_desc}"
        for year, (line_desc, column_desc) in sorted(labels.items(), reverse=True)
        if (line_desc, column_desc) != newest
    ]
    filed_parts = []
    for item, path in zip(chosen, paths, strict=True):
        filed = await _filed(path)
        filed_parts.append(_coverage(item.year, filed, index[0].year, lang))
    first = rows[0]
    return ComparisonResult(
        slc=code,
        schedule_name=first[8],
        line_desc=newest[0],
        column_desc=newest[1],
        datatype=first[11],
        label_changes=changes,
        years=[y.year for y in chosen],
        per_capita=per_capita,
        total=len(rows),
        rows=[
            ComparisonRow(
                year=year,
                munid=munid,
                municipality=name,
                tier=row_tier,
                amount=amount,
                text=text,
                population=population,
                per_capita=per_capita_value if per_capita else None,
            )
            for year, munid, name, row_tier, amount, text, population, per_capita_value, *_ in rows[
                :limit
            ]
        ],
        provenance=_provenance(
            "ComparisonResult",
            chosen[0].url if len(chosen) == 1 else constants.INDEX_URL,
            cached,
            lang,
            as_of=max((y.last_updated for y in chosen if y.last_updated), default=None),
            coverage=" ".join(filed_parts),
            limits=truncation_note_lang(
                lang,
                returned=min(limit, len(rows)),
                total=len(rows),
                unit="rows",
                unit_fr="lignes",
                how_to_get_more="raise limit (up to 500) or filter by tier or municipalities",
                how_to_get_more_fr=(
                    "augmentez limit (jusqu'à 500) ou filtrez par tier ou municipalities"
                ),
            ),
        ),
    )
