"""Bank of Canada surveys and projections, resolved from Valet's groups.

The Business Outlook Survey (BOS), the Canadian Survey of Consumer
Expectations (CSCE), the Monetary Policy Report (MPR) projection tables and
the staff economic projections are all in Valet, but among ~2,500 chart
groups whose names carry a quarter or report month. These functions find the
right groups and series themselves, newest first, so a question like "what do
businesses expect for inflation" does not need a group name. What was
confirmed live on 2026-11-07 (English and French domains):

- BOS headline questions are the stable group `bos` (balances of opinion and
  shares of firms, one row per survey quarter dated its first day: 2026-07-01
  is the 2026Q3 survey, published October 2026), plus the series PC1 (the BOS
  indicator), BOS_ACTIVITY_INDICATOR and BOS_PRICE_INDICATOR (new in 2026Q2)
  and COSTS/COSTSHIGHER/COSTSLOWER (labour costs). Discontinued questions
  (PASTSALES, removed in 2023) still answer `recent=1` with their last date,
  so rows are kept only for the newest survey quarter.
- CSCE headline series are the data-page charts CES_C1 (inflation
  expectations at 1, 2 and 5 years and current perceptions), CES_C3 (wages),
  CES_C4 (job probabilities), CES_C5 (income and spending), CES_C6 (interest
  rates) and CES_C9 (economic outlook), dated like the BOS.
- Each release has a group named for its quarter: BOS_2026Q3 ("October 2026
  Business Outlook Survey", with its page link) and CSCE_2026Q3; older CSCE
  releases used the prefix CES_. The chart groups of a release share its name
  as prefix (BOS_2026Q3_C1, ...). Valet gives the month, never the day.
- MPR tables are MPR_<YYYY>M<MM>_SQP_CAN (quarterly projection for Canada),
  _AARGG_CAN (contributions to annual GDP growth) and _GEG (global growth),
  from 2024M04; 2025M04 has none of them (a scenario-based report). The
  global table's shares of world GDP are dated the report's quarter, not a
  projection year.
- Staff projections are groups SWP-<VAR> holding one series per vintage,
  SWP-<VAR><YYYYQn> (vintages 1970Q4 to 2019Q4: released yearly with a
  five-year lag). Observations are dated each quarter's last day; by the
  Bank's own rule (bankofcanada.ca/rates/staff-economic-projections) those
  before the vintage quarter are history and those from it on are forecasts.
  Rates and the output gap are fractions (0.0175 is 1.75%).

Every call goes through client.py (cache, rate limit, typed errors, French
domain), so nothing here talks to Valet directly.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Coroutine
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, NoReturn

from maplestats_mcp.modules.boc import client
from maplestats_mcp.modules.boc.schemas import (
    GroupObservationsResult,
    GroupSummary,
    MprProjectionResult,
    ObservationsResult,
    ProjectionRow,
    ReleaseInfo,
    SeriesInfoBrief,
    StaffProjectionResult,
    StaffProjectionRow,
    StaffVariable,
    SurveyResult,
    SurveyRow,
)
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, NotFound
from maplestats_mcp.shared.i18n import french_spacing

RECENT_LISTED = 8

_MONTHS = {
    "january": 1, "janvier": 1, "february": 2, "fevrier": 2, "février": 2, "march": 3,
    "mars": 3, "april": 4, "avril": 4, "may": 5, "mai": 5, "june": 6, "juin": 6,
    "july": 7, "juillet": 7, "august": 8, "aout": 8, "août": 8, "september": 9,
    "septembre": 9, "october": 10, "octobre": 10, "november": 11, "novembre": 11,
    "december": 12, "decembre": 12, "décembre": 12,
}  # fmt: skip


# --- Periods -------------------------------------------------------------


def quarter_of(day: date) -> str:
    return f"{day.year}Q{(day.month - 1) // 3 + 1}"


def _quarter_start(quarter: str) -> date:
    return date(int(quarter[:4]), 3 * int(quarter[-1]) - 2, 1)


def _quarter_end(quarter: str) -> date:
    return _quarter_start(_shift_quarters(quarter, 1)) - timedelta(days=1)


def _shift_quarters(quarter: str, n: int) -> str:
    index = int(quarter[:4]) * 4 + int(quarter[-1]) - 1 + n
    return f"{index // 4}Q{index % 4 + 1}"


def parse_quarter(text: str, lang: str = "en") -> str:
    """'2026Q3', '2026-Q3', 'Q3 2026', '2026T3' (French) or a date in it -> 2026Q3."""
    cleaned = text.strip().upper()
    for pattern, year_first in (
        (r"(\d{4})\s*[-_ ]?\s*[QT]([1-4])", True),
        (r"[QT]([1-4])\s*[-_ ]?\s*(\d{4})", False),
    ):
        match = re.fullmatch(pattern, cleaned)
        if match:
            year, q = match.groups() if year_first else match.groups()[::-1]
            return f"{year}Q{q}"
    match = re.fullmatch(r"(\d{4})-(\d{2})(?:-\d{2})?", cleaned)
    if match and 1 <= int(match.group(2)) <= 12:
        return quarter_of(date(int(match.group(1)), int(match.group(2)), 1))
    client._raise(
        InvalidInput,
        f"quarter {text!r} is not a quarter; use the form 2026Q3 (or a date such as 2026-07-01).",
        f"quarter {text!r} n'est pas un trimestre ; utilisez la forme 2026Q3 (ou 2026T3, ou une "
        "date comme 2026-07-01).",
        lang,
    )


def parse_report(text: str, lang: str = "en") -> str:
    """'2026M10', '2026-10', 'October 2026', 'octobre 2026' or a date -> 2026M10."""
    cleaned = text.strip().lower()
    match = re.fullmatch(r"(\d{4})\s*[-m ]\s*(\d{1,2})(?:-\d{2})?", cleaned)
    if match:
        year, month = int(match.group(1)), int(match.group(2))
    else:
        match = re.fullmatch(r"([a-zéû]+)\s+(\d{4})", cleaned)
        month = _MONTHS.get(match.group(1), 0) if match else 0
        year = int(match.group(2)) if match else 0
    if not 1 <= month <= 12:
        client._raise(
            InvalidInput,
            f"report {text!r} is not a report month; use the form 2026M10, 2026-10 or "
            "'October 2026'.",
            f"report {text!r} n'est pas un mois de publication ; utilisez la forme 2026M10, "
            "2026-10 ou « octobre 2026 ».",
            lang,
        )
    return f"{year}M{month:02d}"


def _released(name_month: str | None, label: str) -> str | None:
    """YYYY-MM from a report name (2026M10) or a label ('October 2026 ...')."""
    if name_month:
        return f"{name_month[:4]}-{name_month[-2:]}"
    match = re.search(r"([A-Za-zÀ-ÿ]+)\s+(\d{4})", label)
    month = _MONTHS.get(match.group(1).lower()) if match else None
    return f"{match.group(2)}-{month:02d}" if match and month else None


def _as_of(day: date | None) -> datetime | None:
    return datetime.combine(day, time(), tzinfo=UTC) if day else None


# --- Releases --------------------------------------------------------------


async def _release(
    name: str, groups: list[GroupSummary], month: str | None, lang: str
) -> ReleaseInfo:
    detail = await client.get_group(name, lang=lang)
    charts = [g for g in groups if g.name.startswith(f"{name}_")]
    return ReleaseInfo(
        group=name,
        label=detail.label,
        link=detail.link,
        released=_released(month, detail.label),
        chart_groups=sorted(charts, key=lambda g: g.name),
    )


# --- BOS and CSCE ------------------------------------------------------------

# Balances of opinion in the BOS: share of firms answering "higher" minus "lower".
_BOS_BALANCES = frozenset(
    {"PASTSALES", "FUTURESALES", "FSI", "INVESTMACHEQUIP", "EMPLOY", "LSI", "INPUTS",
     "OUTPUTS", "CREDIT", "COSTS"}
)  # fmt: skip
_BOS_INDICATORS = frozenset({"PC1", "BOS_ACTIVITY_INDICATOR", "BOS_PRICE_INDICATOR"})

_SURVEYS: dict[str, dict[str, Any]] = {
    "bos": {
        "groups": ("bos",),
        "series": (
            "PC1",
            "BOS_ACTIVITY_INDICATOR",
            "BOS_PRICE_INDICATOR",
            "COSTS",
            "COSTSHIGHER",
            "COSTSLOWER",
        ),
        "prefixes": ("BOS_",),
    },
    "csce": {
        "groups": (),
        "series": (
            "CES_C1_SHORT_TERM",
            "CES_C1_MID_TERM",
            "CES_C1_LONG_TERM",
            "CES_C1_PERCEPTIONS",
            "CES_C6_ONE_YEAR",
            "CES_C6_TWO_YEAR",
            "CES_C6_FIVE_YEAR",
            "CES_C3_NEXT_12",
            "CES_C3_PAST_12",
            "CES_C5_INCOME",
            "CES_C5_SPENDING",
            "CES_C4_LOSE_JOB",
            "CES_C4_LEAVE_JOB",
            "CES_C4_FIND_JOB",
            "CES_C9_SIGDECL",
            "CES_C9_SMLDECL",
            "CES_C9_STABLE",
            "CES_C9_MODGRTH",
            "CES_C9_STRGRTH",
        ),
        "prefixes": ("CSCE_", "CES_"),
    },
}

_UNITS = {
    "balance": ("balance of opinion (percentage points)", "solde des opinions (points de %)"),
    "firms": ("percent of firms", "pourcentage des entreprises"),
    "indicator": (
        "indicator of standardized answers (0 = survey average)",
        "indicateur de réponses standardisées (0 = moyenne de l'enquête)",
    ),
    "percent": ("percent", "pourcentage"),
    "probability": ("percent chance", "probabilité en pourcentage"),
    "respondents": ("percent of respondents", "pourcentage des répondants"),
}


def _survey_unit(survey: str, code: str, lang: str) -> str:
    if survey == "bos":
        kind = (
            "indicator"
            if code in _BOS_INDICATORS
            else "balance"
            if code in _BOS_BALANCES
            else "firms"
        )
    elif code.startswith("CES_C4"):
        kind = "probability"
    elif code.startswith("CES_C9"):
        kind = "respondents"
    else:
        kind = "percent"
    en, fr = _UNITS[kind]
    return french_spacing(fr) if lang == "fr" else en


def _survey_label(survey: str, info: SeriesInfoBrief, lang: str) -> tuple[str, str | None]:
    """BOS labels alone say only 'Balance of Opinion'; their description starts
    with the topic ('Future sales growth - Over the next 12 months ...')."""
    description = info.description.strip() or None
    if survey == "bos" and description and " - " in description:
        topic, question = description.split(" - ", 1)
        label = f"{topic.strip()}: {info.label.strip()}"
        return (french_spacing(label) if lang == "fr" else label), question.strip()
    return info.label.strip(), description


def _release_quarters(groups: list[GroupSummary], prefixes: tuple[str, ...]) -> dict[str, str]:
    """Quarter -> release group name, the first prefix winning a tie."""
    found: dict[str, str] = {}
    for prefix in reversed(prefixes):
        for group in groups:
            match = re.fullmatch(rf"{prefix}(\d{{4}})Q([1-4])", group.name)
            if match:
                found[f"{match.group(1)}Q{match.group(2)}"] = group.name
    return found


async def get_survey(survey: str, quarter: str | None = None, lang: str = "en") -> SurveyResult:
    """The headline answers of one BOS or CSCE quarter, the newest by default."""
    spec = _SURVEYS[survey]
    wanted = parse_quarter(quarter, lang) if quarter else None
    # One survey quarter by date range, or each series' newest value (`recent`
    # counts per series in Valet, so a dropped question answers with an old date).
    start = _quarter_start(wanted).isoformat() if wanted else None
    end = _quarter_end(wanted).isoformat() if wanted else None
    recent_n = None if wanted else 1
    calls: list[Coroutine[Any, Any, ObservationsResult | GroupObservationsResult]] = [
        client.get_group_observations(g, start_date=start, end_date=end, recent=recent_n, lang=lang)
        for g in spec["groups"]
    ]
    calls.append(
        client.get_observations(
            list(spec["series"]), start_date=start, end_date=end, recent=recent_n, lang=lang
        )
    )
    answers, inventory = await asyncio.gather(asyncio.gather(*calls), client.list_groups(lang))
    points: list[tuple[str, SeriesInfoBrief, date, float | None]] = []
    seen: set[str] = set()
    for answer in answers:
        for code, info in answer.series.items():
            if code in seen:
                continue
            seen.add(code)
            for row in answer.observations:
                if code in row.values:
                    points.append((code, info, row.ref_date, row.values[code]))
    releases = _release_quarters(inventory.groups, spec["prefixes"])
    recent = sorted(releases, reverse=True)[:RECENT_LISTED]
    dates = [d for _, _, d, _ in points]
    if not dates:
        _raise_no_survey(survey, wanted, recent, lang)
    target = quarter_of(max(dates)) if not wanted else wanted
    rows = []
    for code, info, day, value in points:
        if quarter_of(day) != target:
            continue
        label, question = _survey_label(survey, info, lang)
        rows.append(
            SurveyRow(
                series=code,
                label=label,
                question=question,
                period=target,
                ref_date=day,
                value=value,
                unit=_survey_unit(survey, code, lang),
            )
        )
    if not rows:
        _raise_no_survey(survey, wanted, recent, lang)
    release = (
        await _release(releases[target], inventory.groups, None, lang)
        if target in releases
        else None
    )
    urls = [a.provenance.url for a in answers]
    return SurveyResult(
        survey=survey,
        quarter=target,
        release=release,
        rows=rows,
        recent_quarters=recent,
        provenance=make_provenance(
            source="boc",
            url=urls[0],
            cached=all(a.provenance.cached for a in answers),
            as_of=_as_of(max(r.ref_date for r in rows)),
            schema_name="boc.SurveyResult",
            coverage=_survey_coverage(survey, urls, lang),
            lang=lang,
        ),
    )


def _survey_coverage(survey: str, urls: list[str], lang: str) -> str:
    if lang == "fr":
        what = (
            "Questions principales de l'Enquête sur les perspectives des entreprises"
            if survey == "bos"
            else "Questions principales de l'Enquête canadienne sur les attentes des consommateurs"
        )
        return french_spacing(
            f"{what}, un trimestre ; requêtes : {' ; '.join(urls)}. Les ventilations (région, "
            "taille, secteur ou groupe démographique) sont dans les groupes de "
            "release.chart_groups et boc_search_groups."
        )
    what = (
        "Business Outlook Survey headline questions"
        if survey == "bos"
        else "Canadian Survey of Consumer Expectations headline questions"
    )
    return (
        f"{what}, one quarter; requests: {'; '.join(urls)}. Breakdowns (region, firm size, "
        "sector or demographic group) are in release.chart_groups and boc_search_groups."
    )


def _raise_no_survey(survey: str, wanted: str | None, recent: list[str], lang: str) -> NoReturn:
    name = "BOS" if survey == "bos" else "CSCE"
    listed = ", ".join(recent) or "none"
    client._raise(
        NotFound,
        f"No {name} results for {wanted or 'the latest quarter'} in Valet. Quarters with a "
        f"release: {listed}.",
        f"Aucun résultat {'EPE' if survey == 'bos' else 'ECAC'} pour "
        f"{wanted or 'le dernier trimestre'} dans Valet. Trimestres publiés : {listed}.",
        lang,
    )


# --- Monetary Policy Report --------------------------------------------------

_MPR_TABLES = {"SQP_CAN": "summary", "AARGG_CAN": "gdp_contributions", "GEG": "global"}


def _mpr_reports(groups: list[GroupSummary]) -> dict[str, list[str]]:
    reports: dict[str, list[str]] = {}
    for group in groups:
        match = re.fullmatch(r"MPR_(\d{4}M\d{2})_(SQP_CAN|AARGG_CAN|GEG)", group.name)
        if match:
            reports.setdefault(match.group(1), []).append(match.group(2))
    return reports


def _mpr_unit(code: str, lang: str) -> str:
    if code.endswith("_CTG"):
        en, fr = "percentage points (contribution to growth)", "points de % (contribution)"
    elif code.endswith("_SHR"):
        en, fr = "percent of world GDP", "pourcentage du PIB mondial"
    else:
        en, fr = "percent", "pourcentage"
    return french_spacing(fr) if lang == "fr" else en


def _mpr_period(table: str, code: str, day: date) -> str | None:
    if code.endswith("_SHR"):
        return None
    return quarter_of(day) if table == "summary" else str(day.year)


async def get_mpr_projection(report: str | None = None, lang: str = "en") -> MprProjectionResult:
    """The projection tables of one Monetary Policy Report, the newest by default."""
    wanted = parse_report(report, lang) if report else None
    inventory = await client.list_groups(lang)
    reports = _mpr_reports(inventory.groups)
    recent = sorted(reports, reverse=True)[:RECENT_LISTED]
    chosen = wanted or (recent[0] if recent else None)
    if not chosen or chosen not in reports:
        listed = ", ".join(recent) or "none"
        client._raise(
            NotFound,
            f"No projection tables for the {chosen or 'latest'} Monetary Policy Report in "
            f"Valet. Reports with tables: {listed}.",
            f"Aucun tableau de projection pour le Rapport sur la politique monétaire "
            f"{chosen or 'le plus récent'} dans Valet. Rapports avec tableaux : {listed}.",
            lang,
        )
    tables = sorted(reports[chosen], key=list(_MPR_TABLES).index)
    answers = await asyncio.gather(
        *(client.get_group_observations(f"MPR_{chosen}_{t}", lang=lang) for t in tables)
    )
    rows = []
    for suffix, answer in zip(tables, answers, strict=True):
        table = _MPR_TABLES[suffix]
        for code, info in answer.series.items():
            for row in answer.observations:
                if code not in row.values:
                    continue
                rows.append(
                    ProjectionRow(
                        table=table,
                        series=code,
                        label=info.label.strip(),
                        period=_mpr_period(table, code, row.ref_date),
                        ref_date=row.ref_date,
                        value=row.values[code],
                        unit=_mpr_unit(code, lang),
                    )
                )
    names = {g.name for g in inventory.groups}
    release_group = f"MPR_{chosen}" if f"MPR_{chosen}" in names else f"MPR_{chosen}_{tables[0]}"
    release = await _release(release_group, inventory.groups, chosen, lang)
    missing = [_MPR_TABLES[t] for t in _MPR_TABLES if t not in tables]
    urls = [a.provenance.url for a in answers]
    return MprProjectionResult(
        report=chosen,
        release=release,
        rows=rows,
        recent_reports=recent,
        provenance=make_provenance(
            source="boc",
            url=urls[0],
            cached=all(a.provenance.cached for a in answers),
            schema_name="boc.MprProjectionResult",
            coverage=_mpr_coverage(urls, lang),
            limits=_mpr_limits(chosen, missing, lang),
            lang=lang,
        ),
    )


def _mpr_coverage(urls: list[str], lang: str) -> str:
    if lang == "fr":
        return french_spacing(
            f"Tableaux de projection du Rapport ; requêtes : {' ; '.join(urls)}. Les valeurs "
            "des trimestres et années passés sont des estimations au moment du Rapport, non "
            "des données révisées."
        )
    return (
        f"The Report's projection tables; requests: {'; '.join(urls)}. Values for past "
        "quarters and years are the estimates at the time of the Report, not revised data."
    )


def _mpr_limits(report: str, missing: list[str], lang: str) -> str | None:
    if not missing:
        return None
    if lang == "fr":
        return french_spacing(
            f"Le Rapport {report} n'a pas dans Valet les tableaux : {', '.join(missing)}."
        )
    return f"Valet has no {', '.join(missing)} table for the {report} Report."


# --- Staff economic projections ---------------------------------------------

_RATE = (
    "fraction per year (0.0175 is 1.75%)",
    "fraction par année (0,0175 correspond à 1,75 %)",
)
_REAL = (
    "millions of dollars at annual rates, in the base-year prices of the vintage",
    "millions de dollars aux taux annuels, aux prix de l'année de base du millésime",
)
_NOMINAL = ("millions of dollars at annual rates", "millions de dollars aux taux annuels")
_INDEX = ("index, as published in the vintage", "indice, tel que publié dans le millésime")

STAFF_VARIABLES: dict[str, tuple[str, str]] = {
    "GDP": _REAL,
    "GDPN": _NOMINAL,
    "PGDP": _INDEX,
    "GNEN": _NOMINAL,
    "PGNE": _INDEX,
    "C": _REAL,
    "PC": _INDEX,
    "I": _REAL,
    "IINVT": _REAL,
    "IRES": _REAL,
    "G": _REAL,
    "X": _REAL,
    "M": _REAL,
    "CIRINV": _REAL,
    "PCIRINV": _INDEX,
    "LYGAP": (
        "fraction of potential output (-0.0045 is -0.45%)",
        "fraction de la production potentielle (-0,0045 correspond à -0,45 %)",
    ),
    "PCPI": _INDEX,
    "PCPIX": _INDEX,
    "URATE": (
        "fraction of the labour force (0.058 is 5.8%)",
        "fraction de la population active (0,058 correspond à 5,8 %)",
    ),
    "USCANPFX": ("US dollars per Canadian dollar", "dollars américains par dollar canadien"),
    "R1N": _RATE,
    "R20N": _RATE,
}
DEFAULT_STAFF_VARIABLES = ("GDP", "PCPI", "PCPIX", "URATE", "LYGAP", "R1N")
HISTORY_QUARTERS_MAX = 200


async def get_staff_projections(
    variables: list[str] | None = None,
    vintage: str | None = None,
    history_quarters: int = 4,
    lang: str = "en",
) -> StaffProjectionResult:
    """One vintage of the staff projection for some variables, the newest by default."""
    codes = [v.strip().upper() for v in (variables or DEFAULT_STAFF_VARIABLES)]
    unknown = [c for c in codes if c not in STAFF_VARIABLES]
    if unknown or not codes:
        known = ", ".join(STAFF_VARIABLES)
        client._raise(
            InvalidInput,
            f"Unknown staff projection variable(s) {unknown}; use one or more of {known}.",
            f"Variable(s) de projection inconnue(s) {unknown} ; utilisez {known}.",
            lang,
        )
    if not 0 <= history_quarters <= HISTORY_QUARTERS_MAX:
        client._raise(
            InvalidInput,
            f"history_quarters must be between 0 and {HISTORY_QUARTERS_MAX}, got "
            f"{history_quarters}.",
            f"history_quarters doit être compris entre 0 et {HISTORY_QUARTERS_MAX} ; valeur "
            f"reçue : {history_quarters}.",
            lang,
        )
    codes = list(dict.fromkeys(codes))
    wanted = parse_quarter(vintage, lang) if vintage else None
    details = await asyncio.gather(*(client.get_group(f"SWP-{c}", lang=lang) for c in codes))
    vintages: dict[str, list[str]] = {}
    for code, detail in zip(codes, details, strict=True):
        pattern = re.compile(rf"SWP-{re.escape(code)}(\d{{4}}Q[1-4])")
        vintages[code] = sorted(
            m.group(1) for s in detail.series if (m := pattern.fullmatch(s.name))
        )
    chosen = wanted or max((v[-1] for v in vintages.values() if v), default=None)
    having = [c for c in codes if chosen in vintages[c]]
    if not chosen or not having:
        ranges = "; ".join(f"{c} {v[0]}-{v[-1]}" if v else f"{c} none" for c, v in vintages.items())
        client._raise(
            NotFound,
            f"No staff projection vintage {chosen} for {', '.join(codes)}. Vintages: {ranges}.",
            f"Aucun millésime {chosen} de projection du personnel pour {', '.join(codes)}. "
            f"Millésimes : {ranges}.",
            lang,
        )
    start = _quarter_start(_shift_quarters(chosen, -history_quarters))
    answer: ObservationsResult = await client.get_observations(
        [f"SWP-{c}{chosen}" for c in having], start_date=start.isoformat(), lang=lang
    )
    series_variable = {f"SWP-{c}{chosen}": c for c in having}
    rows = [
        StaffProjectionRow(
            variable=series_variable[name],
            series=name,
            period=quarter_of(row.ref_date),
            ref_date=row.ref_date,
            value=row.values[name],
            projected=quarter_of(row.ref_date) >= chosen,
        )
        for name in series_variable
        for row in answer.observations
        if name in row.values
    ]
    info = [
        StaffVariable(
            code=c,
            label=detail.label,
            unit=french_spacing(STAFF_VARIABLES[c][1]) if lang == "fr" else STAFF_VARIABLES[c][0],
            first_vintage=vintages[c][0],
            last_vintage=vintages[c][-1],
        )
        for c, detail in zip(codes, details, strict=True)
        if c in having
    ]
    return StaffProjectionResult(
        vintage=chosen,
        variables=info,
        rows=rows,
        provenance=make_provenance(
            source="boc",
            url=answer.provenance.url,
            cached=answer.provenance.cached,
            schema_name="boc.StaffProjectionResult",
            coverage=_staff_coverage(lang),
            limits=_staff_limits(chosen, [c for c in codes if c not in having], answer, lang),
            lang=lang,
        ),
    )


def _staff_coverage(lang: str) -> str:
    if lang == "fr":
        return french_spacing(
            "Projections économiques du personnel de la Banque, publiées une fois par année "
            "avec un décalage de cinq ans : les observations antérieures au millésime sont "
            "les données historiques connues alors, celles à partir du millésime sont des "
            "prévisions (projected=true). Ce ne sont pas les projections du Rapport sur la "
            "politique monétaire."
        )
    return (
        "Bank staff economic projections, released once a year with a five-year lag: "
        "observations before the vintage quarter are the historical data known then, those "
        "from it on are forecasts (projected=true). These are not the Monetary Policy "
        "Report's projections."
    )


def _staff_limits(
    vintage: str, without: list[str], answer: ObservationsResult, lang: str
) -> str | None:
    notes = [answer.provenance.limits] if answer.provenance.limits else []
    if without:
        notes.append(
            french_spacing(f"Pas de millésime {vintage} pour : {', '.join(without)}.")
            if lang == "fr"
            else f"No {vintage} vintage for: {', '.join(without)}."
        )
    return " ".join(notes) or None
