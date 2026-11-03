"""Re-read the figures an answer cites and say what is wrong with them.

Every check reuses an existing cached client: WDS series info, data and cube
metadata (statcan/wds), Bank of Canada observations (boc), the planner's place
names and the hand-written fitness rules. Only problems are returned, each one
sentence with a one-sentence fix, so a clean answer costs a few bytes.

Values are compared the way a person rounds: a cited value matches when
rounding the published one to the cited precision gives it (2.06 trillion
matches 2,056,453 millions; 170 matches 169.8 and 170.0). A cited value equal
to the unscaled table value of a series published in thousands or millions is a
missed scale factor unless the unit says so.

The "not published" route was checked on 2026-11-03: Statistical Information
Services "offers ... custom data tables tailored to user needs"
(statcan.gc.ca/en/reference/refcentre/index, infostats@statcan.gc.ca); RTRA is
an annual organizational subscription ($10,000 a year, statcan.gc.ca/en/
microdata/rtra/fees) whose users submit SAS programs and never see the
microdata; RDC users become deemed employees (security clearance, oath) on an
approved project (statcan.gc.ca/en/microdata/data-centres). The CIS public use
microdata file (72M0003X, 2022 file) has PROV, MBSCF18 and FWEIGHT but no
disability variable and no bootstrap weights (checked with statcan_pumf tools
on 2026-11-03), so it cannot give a provincial disability poverty rate.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from maplestats_mcp.modules.answer_check.schemas import AnswerCheck, AnswerProblem, CitedFigure
from maplestats_mcp.modules.boc import client as boc
from maplestats_mcp.modules.planner.client import normalize, places_named
from maplestats_mcp.modules.statcan.wds import auto_notes, context
from maplestats_mcp.modules.statcan.wds import client as wds
from maplestats_mcp.modules.statcan.wds.schemas import ObservationRow
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import (
    DataLocked,
    InvalidInput,
    NotFound,
    UpstreamError,
    UpstreamUnavailable,
)
from maplestats_mcp.shared.fitness import rules_for
from maplestats_mcp.shared.i18n import normalize_lang, pick
from maplestats_mcp.shared.json_utils import list_or_empty
from maplestats_mcp.shared.transform import parse_period, period_end

MAX_FIGURES = 20
_SOFT = (NotFound, UpstreamError, UpstreamUnavailable, DataLocked, InvalidInput)
_SCALE_WORDS = (
    (re.compile(r"\btrillions?\b|\bbillions? de milliards?\b", re.IGNORECASE), 1e12),
    (re.compile(r"\bbillions?\b|\bmilliards?\b|\bbn\b", re.IGNORECASE), 1e9),
    (re.compile(r"\bmillions?\b|\bm\b", re.IGNORECASE), 1e6),
    (re.compile(r"\bthousands?\b|\bmilliers?\b|\bmille\b|\bk\b", re.IGNORECASE), 1e3),
)
_FACTORS = (1e3, 1e6, 1e9, 1e-3, 1e-6, 1e-9, 100.0, 0.01)
# Questions that ask for unadjusted data or a change a year apart, where an
# unadjusted series is the right one.
_UNADJUSTED_OK = re.compile(
    r"unadjusted|not seasonally|non[- ]?d[ée]saisonnalis|raw|year[- ]over[- ]year|"
    r"12[- ]month|same month|glissement annuel|sur un an|annual|annuel",
    re.IGNORECASE,
)
_CANADA = re.compile(
    r"\b(?:canada|national|nationally|canadian|canadien(?:ne)?s?|pays)\b", re.IGNORECASE
)
_AGENCY = re.compile(r"(?:statistics|statistique|bank of|banque du) canada", re.IGNORECASE)
_CURRENT = re.compile(r"current|nominal|courant", re.IGNORECASE)
_REAL = re.compile(r"constant|chained|real\b|r[ée]el|encha[iî]n", re.IGNORECASE)
_DOLLAR = re.compile(r"\$|dollar", re.IGNORECASE)
_WDS_URL = "https://www150.statcan.gc.ca/t1/wds/rest/"

# Public use microdata files known, from their codebooks, to lack what a
# question needs: survey code -> (question words, file, what is missing).
_PUMF_GAPS: dict[str, tuple[re.Pattern[str], str, str, str]] = {
    "5200": (
        re.compile(r"disab|incapacit|handicap", re.IGNORECASE),
        "72M0003X",
        "has no disability variable",
        "n'a aucune variable d'incapacité",
    ),
}


class _Ctx:
    """What one StatCan figure resolved to."""

    def __init__(self, index: int, figure: CitedFigure) -> None:
        self.index = index
        self.figure = figure
        self.vector_id: int | None = figure.vector_id
        self.product_id: int | None = None
        self.coordinate: str | None = None
        self.info: dict[str, Any] | None = None
        self.cube: dict[str, Any] | None = None
        self.members: list[tuple[dict, dict]] = []


def _precision(value: float) -> float:
    exponent = Decimal(repr(value)).normalize().as_tuple().exponent
    return 10.0 ** int(exponent) if isinstance(exponent, int) else 1.0


def _close(cited: float, published: float, precision: float) -> bool:
    return abs(cited - published) <= precision / 2 + 1e-9 * max(1.0, abs(published))


def _scale_word(unit: str | None) -> float | None:
    if not unit:
        return None
    for pattern, factor in _SCALE_WORDS:
        if pattern.search(unit):
            return factor
    return None


def _fmt(value: float) -> str:
    if abs(value) >= 1000:
        return f"{value:,.4f}".rstrip("0").rstrip(".")
    return f"{value:.10g}"


def _window(period: str) -> tuple[date, date]:
    start, ppy = parse_period(period)
    if ppy is not None:
        return start, period_end(start, ppy)
    # A day, or an ISO week (2026-W12): a week covers seven days.
    return start, start + timedelta(days=6 if "W" in period.upper() else 0)


def _problem(index: int | None, check: str, problem: str, fix: str) -> AnswerProblem:
    return AnswerProblem(figure=index, check=check, problem=problem, fix=fix)  # type: ignore[arg-type]


def _table(product_id: int) -> str:
    return context.table_number(product_id)[:-3]


def _geo_head(name: str) -> str:
    return normalize(name.split(",")[0])


def _geo_match(place: str, member_name: str) -> bool:
    label = normalize(place).removesuffix(" city")
    head = _geo_head(member_name)
    return bool(label) and (label == head or head.startswith(label) or label in head)


def _asked_places(question: str) -> list[str]:
    places = [p.place for p in places_named(question)]
    if _CANADA.search(_AGENCY.sub(" ", question)):
        places.append("Canada")
    return places


def _geography(ctx: _Ctx) -> tuple[dict, dict] | None:
    return next(
        (
            (d, m)
            for d, m in ctx.members
            if str(d.get("dimensionNameEn", "")).startswith("Geograph")
        ),
        None,
    )


def _swap(coordinate: str, position: int, member_id: int) -> str:
    ids = coordinate.split(".")
    ids[position - 1] = str(member_id)
    while len(ids) > 1 and ids[-1] == "0":
        ids.pop()
    return ".".join(ids)


async def _survey_names(cube: dict[str, Any], lang: str) -> list[str]:
    codes = [str(c) for c in list_or_empty(cube, "surveyCode")]
    try:
        sets, _ = await wds._code_sets_raw()
    except _SOFT:
        return []
    suffix = "Fr" if lang == "fr" else "En"
    return [
        str(s.get(f"survey{suffix}") or s.get("surveyEn"))
        for s in list_or_empty(sets, "survey")
        if str(s.get("surveyCode")) in codes
    ]


async def _not_published(
    ctx: _Ctx, place: str, geos: list[str], question: str, lang: str
) -> AnswerProblem:
    assert ctx.cube is not None and ctx.product_id is not None
    table = _table(ctx.product_id)
    shown = ", ".join(geos[:3]) + (", ..." if len(geos) > 3 else "")
    surveys = await _survey_names(ctx.cube, lang)
    survey = surveys[0] if surveys else pick(lang, "the survey", "l'enquête")
    gap = next(
        (
            gap
            for code in (str(c) for c in list_or_empty(ctx.cube, "surveyCode"))
            if (gap := _PUMF_GAPS.get(code)) and gap[0].search(question)
        ),
        None,
    )
    if gap:
        pumf_en = f"The {survey} public microdata file ({gap[1]}) {gap[2]}, so it cannot give it."
        pumf_fr = (
            f"Le fichier de microdonnées à grande diffusion ({survey}, {gap[1]}) {gap[3]} ; "
            "il ne peut pas le donner."
        )
    else:
        pumf_en = (
            f"A {survey} public microdata file may: check every variable with "
            "statcan_pumf_get_codebook, then report it as your own weighted estimate."
        )
        pumf_fr = (
            f"Un fichier de microdonnées à grande diffusion ({survey}) le peut peut-être : "
            "vérifiez chaque variable avec statcan_pumf_get_codebook, puis présentez-le comme "
            "votre propre estimation pondérée."
        )
    return _problem(
        ctx.index,
        "not_published",
        pick(
            lang,
            f"Table {table} is published for {shown} only: there is no {place} figure.",
            f"Le tableau {table} n'est publié que pour : {shown} ; il n'y a pas de chiffre "
            f"pour {place}.",
        ),
        pick(
            lang,
            f"Say it is not published and label the figure you give as {geos[0]}. {pumf_en} "
            "Otherwise a custom tabulation from Statistics Canada (infostats@statcan.gc.ca), "
            "RTRA (paid organizational subscription) or an RDC (approved project, security "
            "clearance); none is public and MapleStats cannot run them. "
            "statcan_surveys_search_rtra_datasets and statcan_surveys_search_rdc_holdings "
            f"show whether the {survey} is held.",
            f"Dites qu'il n'est pas publié et précisez la géographie du chiffre donné "
            f"({geos[0]}). {pumf_fr} Sinon : une totalisation personnalisée de Statistique "
            "Canada (infostats@statcan.gc.ca), l'ADTR (abonnement payant d'un organisme) ou "
            "un CDR (projet approuvé, cote de sécurité) ; aucun n'est public et MapleStats ne "
            "peut pas les exécuter. statcan_surveys_search_rtra_datasets et "
            f"statcan_surveys_search_rdc_holdings indiquent si l'enquête « {survey} » y figure.",
        ),
    )


async def _check_geography(ctx: _Ctx, question: str, lang: str) -> list[AnswerProblem]:
    geo = _geography(ctx)
    if geo is None or ctx.cube is None or ctx.product_id is None or ctx.coordinate is None:
        return []
    dim, member = geo
    series_geo = str(member.get("memberNameEn") or "")
    asked = _asked_places(question)
    if ctx.figure.geography:
        asked = asked or [ctx.figure.geography]
    if not asked or any(_geo_match(place, series_geo) for place in asked):
        return []
    place = asked[0]
    shown_geo = auto_notes.member_name(member, lang)
    table_members = list_or_empty(dim, "member")
    target = next((m for m in table_members if _geo_match(place, str(m["memberNameEn"]))), None)
    if target is None:
        geos = [auto_notes.member_name(m, lang) for m in table_members]
        return [await _not_published(ctx, place, geos, question, lang)]
    coordinate = _swap(ctx.coordinate, int(dim["dimensionPositionId"]), int(target["memberId"]))
    table = _table(ctx.product_id)
    return [
        _problem(
            ctx.index,
            "geography",
            pick(
                lang,
                f"The series is for {shown_geo}, but the question asks about {place}.",
                f"La série porte sur {shown_geo}, mais la question vise {place}.",
            ),
            pick(
                lang,
                f"Use table {table}, coordinate {coordinate} "
                f"({auto_notes.member_name(target, lang)}).",
                f"Utilisez le tableau {table}, coordonnée {coordinate} "
                f"({auto_notes.member_name(target, lang)}).",
            ),
        )
    ]


def _check_adjustment(ctx: _Ctx, question: str, lang: str) -> list[AnswerProblem]:
    if ctx.cube is None or ctx.coordinate is None or ctx.product_id is None:
        return []
    if ctx.cube.get("frequencyCode") not in (6, 9, 7, 20, 19) or _UNADJUSTED_OK.search(question):
        return []
    sibling = auto_notes.adjusted_sibling(ctx.members)
    if sibling is None:
        return []
    dim, _, other = sibling
    coordinate = _swap(ctx.coordinate, int(dim["dimensionPositionId"]), int(other["memberId"]))
    name = auto_notes.member_name(other, lang)
    return [
        _problem(
            ctx.index,
            "seasonal_adjustment",
            pick(
                lang,
                "The series is unadjusted; the headline figure is usually the seasonally "
                "adjusted one.",
                "La série n'est pas désaisonnalisée ; le chiffre de référence est d'ordinaire "
                "la série désaisonnalisée.",
            ),
            pick(
                lang,
                f"Use coordinate {coordinate} ({name}) of table {_table(ctx.product_id)}, or "
                "say the figure is unadjusted.",
                f"Utilisez la coordonnée {coordinate} ({name}) du tableau "
                f"{_table(ctx.product_id)}, ou précisez que le chiffre est non désaisonnalisé.",
            ),
        )
    ]


def _check_unit(ctx: _Ctx, unit_text: str | None, lang: str) -> list[AnswerProblem]:
    said = ctx.figure.unit
    if not said:
        return []
    basis = auto_notes.price_basis(ctx.members)
    unit = unit_text or ""
    if basis and _CURRENT.search(said):
        actual = f"chained ({basis[1]}) dollars" if basis[0] == "chained" else str(basis[1])
        return [
            _problem(
                ctx.index,
                "unit",
                pick(
                    lang,
                    f"The series is in {actual} (real), not current dollars.",
                    f"La série est en dollars réels ({actual}), pas en dollars courants.",
                ),
                pick(lang, f"Say {actual}.", f"Écrivez « {actual} »."),
            )
        ]
    if not basis and unit.lower() == "dollars" and _REAL.search(said):
        return [
            _problem(
                ctx.index,
                "unit",
                pick(
                    lang,
                    "The series is in current dollars, not inflation-adjusted dollars.",
                    "La série est en dollars courants, pas en dollars corrigés de l'inflation.",
                ),
                pick(lang, "Say current dollars.", "Écrivez « dollars courants »."),
            )
        ]
    if "=100" in unit.replace(" ", "") and _DOLLAR.search(said):
        return [
            _problem(
                ctx.index,
                "unit",
                pick(
                    lang,
                    f"The series is an index ({unit}), not dollars.",
                    f"La série est un indice ({unit}), pas des dollars.",
                ),
                pick(
                    lang,
                    "Report index points or a percent change.",
                    "Donnez des points d'indice ou une variation en pourcentage.",
                ),
            )
        ]
    return []


def _value_problems(
    index: int,
    figure: CitedFigure,
    published: float,
    multiplier: float,
    scale: str | None,
    period: str,
    latest: tuple[str, float | None] | None,
    lang: str,
) -> list[AnswerProblem]:
    """Compare a cited value with the published one; [] when they agree."""
    assert figure.value is not None
    cited = figure.value
    word = _scale_word(figure.unit)
    precision = _precision(cited)
    full = published * multiplier
    if word is not None:
        if _close(cited * word, full, precision * word):
            return []
        cited_full = cited * word
    else:
        if _close(cited, full, precision):
            return []
        if multiplier != 1 and _close(cited, published, precision):
            scale_text = scale or f"x{_fmt(multiplier)}"
            return [
                _problem(
                    index,
                    "scale",
                    pick(
                        lang,
                        f"{_fmt(published)} is in {scale_text}: the full figure is {_fmt(full)}.",
                        f"{_fmt(published)} est en {scale_text} : le chiffre entier est "
                        f"{_fmt(full)}.",
                    ),
                    pick(
                        lang,
                        f"Write {_fmt(full)}, or say '{scale_text}' with the figure.",
                        f"Écrivez {_fmt(full)}, ou précisez « {scale_text} ».",
                    ),
                )
            ]
        cited_full = cited
    for factor in _FACTORS:
        if _close(cited_full * factor, full, precision * (word or 1) * factor):
            return [
                _problem(
                    index,
                    "scale",
                    pick(
                        lang,
                        f"The value is off by a factor of {_fmt(1 / factor)}: the published "
                        f"figure is {_fmt(full)}.",
                        f"La valeur est décalée d'un facteur {_fmt(1 / factor)} : le chiffre "
                        f"publié est {_fmt(full)}.",
                    ),
                    pick(
                        lang,
                        "Check the scale (thousands, millions) and the unit.",
                        "Vérifiez l'échelle (milliers, millions) et l'unité.",
                    ),
                )
            ]
    if latest is not None and latest[1] is not None and latest[0] != period:
        other_full = latest[1] * multiplier
        if _close(cited_full, other_full, precision * (word or 1)):
            return [
                _problem(
                    index,
                    "period",
                    pick(
                        lang,
                        f"{_fmt(cited)} is the value for {latest[0]}, not {period}.",
                        f"{_fmt(cited)} est la valeur de {latest[0]}, pas de {period}.",
                    ),
                    pick(
                        lang,
                        f"Cite it as {latest[0]}, or use {_fmt(full)} for {period}.",
                        f"Citez-la pour {latest[0]}, ou utilisez {_fmt(full)} pour {period}.",
                    ),
                )
            ]
    # In the answer's own scale ("561,381 millions"), so the fix can be pasted.
    shown = _fmt(full / word) + f" ({figure.unit})" if word else _fmt(full)
    return [
        _problem(
            index,
            "value",
            pick(
                lang,
                f"The published value for {period} is {shown}, not {_fmt(cited)}.",
                f"La valeur publiée pour {period} est {shown}, pas {_fmt(cited)}.",
            ),
            pick(
                lang,
                f"Use {shown}, or check the series and period.",
                f"Utilisez {shown}, ou vérifiez la série et la période.",
            ),
        )
    ]


def _flag_problem(index: int, row: ObservationRow, period: str, lang: str) -> AnswerProblem | None:
    if row.security_level_code == auto_notes.SECURITY_SUPPRESSED or (
        row.status_code == auto_notes.STATUS_TOO_UNRELIABLE
    ):
        what = (
            pick(lang, "suppressed for confidentiality (x)", "confidentiel (x)")
            if row.security_level_code == auto_notes.SECURITY_SUPPRESSED
            else pick(lang, "too unreliable to be published (F)", "trop peu fiable (F)")
        )
        return _problem(
            index,
            "quality_flag",
            pick(lang, f"{period} is {what}.", f"{period} est {what}."),
            pick(
                lang,
                "Do not report a figure: say it is not published and offer a broader group "
                "or another period.",
                "Ne donnez aucun chiffre : dites qu'il n'est pas publié et proposez un groupe "
                "plus large ou une autre période.",
            ),
        )
    if row.status_code == auto_notes.STATUS_USE_WITH_CAUTION:
        return _problem(
            index,
            "quality_flag",
            pick(
                lang,
                f"StatCan flags {period} 'use with caution' (E).",
                f"Statistique Canada marque {period} « à utiliser avec prudence » (E).",
            ),
            pick(lang, "Report it with that caveat.", "Citez-le avec cette mise en garde."),
        )
    return None


def _newer(
    index: int, period: str, latest: tuple[str, float | None], question: str, lang: str
) -> AnswerProblem | None:
    latest_period, latest_value = latest
    # A question that names the cited year asks for that period on purpose.
    if latest_period <= period or period[:4] in question:
        return None
    value = "" if latest_value is None else f" ({_fmt(latest_value)})"
    return _problem(
        index,
        "newer_period",
        pick(
            lang,
            f"A newer period is published: {latest_period}{value}.",
            f"Une période plus récente est publiée : {latest_period}{value}.",
        ),
        pick(
            lang,
            f"Report {latest_period}, or say why {period} is used.",
            f"Donnez {latest_period}, ou expliquez pourquoi {period} est retenu.",
        ),
    )


async def _resolve(ctxs: list[_Ctx], lang: str) -> list[AnswerProblem]:
    problems: list[AnswerProblem] = []
    for ctx in ctxs:
        figure = ctx.figure
        if ctx.vector_id is None and figure.product_id and figure.coordinate:
            try:
                info = await wds.get_series_info_from_cube_pid_coord(
                    figure.product_id, figure.coordinate
                )
            except _SOFT as exc:
                problems.append(
                    _problem(
                        ctx.index,
                        "series",
                        str(exc).split(" Fix:")[0],
                        pick(lang, "Cite a published series.", "Citez une série publiée."),
                    )
                )
                continue
            ctx.vector_id = info.vector_id
    ids = sorted({c.vector_id for c in ctxs if c.vector_id is not None})
    infos = await context.series_info_raw(ids) if ids else {}
    for ctx in ctxs:
        if ctx.vector_id is None:
            continue
        info = infos.get(ctx.vector_id)
        if info is None:
            problems.append(
                _problem(
                    ctx.index,
                    "series",
                    pick(
                        lang,
                        f"Vector {ctx.vector_id} is not a StatCan series.",
                        f"Le vecteur {ctx.vector_id} n'est pas une série de Statistique Canada.",
                    ),
                    pick(
                        lang,
                        "Check the vector id (wds_get_series_info).",
                        "Vérifiez le numéro de vecteur (wds_get_series_info).",
                    ),
                )
            )
            ctx.vector_id = None
            continue
        ctx.info = info
        ctx.product_id = int(info["productId"])
        ctx.coordinate = str(info["coordinate"])
        try:
            ctx.cube, _ = await wds.cube_metadata_raw(ctx.product_id)
        except _SOFT:
            ctx.cube = None
        if ctx.cube is not None:
            ctx.members = auto_notes.series_members(ctx.cube, ctx.coordinate)
    return problems


async def _check_statcan(ctxs: list[_Ctx], question: str, lang: str) -> list[AnswerProblem]:
    problems = await _resolve(ctxs, lang)
    live = [c for c in ctxs if c.vector_id is not None]
    if not live:
        return problems
    ids = sorted({c.vector_id for c in live if c.vector_id is not None})
    latest_rows: dict[int, ObservationRow] = {}
    try:
        latest_set = await wds.get_data_from_vectors_and_latest_n_periods(ids, 1)
        for series in latest_set.series:
            if series.observations:
                latest_rows[series.vector_id] = series.observations[-1]
    except _SOFT:
        pass
    described, _ = await context.describe_vectors(ids, set())
    for ctx in live:
        assert ctx.vector_id is not None
        figure = ctx.figure
        frequency = ctx.cube.get("frequencyCode") if ctx.cube else None
        series_ctx = described.get(ctx.vector_id)
        latest_row = latest_rows.get(ctx.vector_id)
        latest = (
            (auto_notes.format_period(latest_row.ref_period, frequency), latest_row.value)
            if latest_row
            else None
        )
        problems.extend(await _check_geography(ctx, question, lang))
        problems.extend(_check_adjustment(ctx, question, lang))
        problems.extend(_check_unit(ctx, series_ctx.unit if series_ctx else None, lang))
        if figure.period is None:
            if figure.value is not None and latest_row is not None and latest_row.value is not None:
                problems.extend(
                    _value_problems(
                        ctx.index,
                        figure,
                        latest_row.value,
                        latest_row.scale_multiplier,
                        series_ctx.scale if series_ctx else None,
                        latest[0] if latest else "",
                        None,
                        lang,
                    )
                )
            continue
        try:
            start, end = _window(figure.period)
        except ValueError:
            problems.append(
                _problem(
                    ctx.index,
                    "period",
                    pick(
                        lang,
                        f"Period {figure.period!r} is not 2024, 2024-09, 2024-Q3 or 2024-09-01.",
                        f"La période {figure.period!r} n'est pas 2024, 2024-09, 2024-Q3 ou "
                        "2024-09-01.",
                    ),
                    pick(
                        lang,
                        "Give the period in one of those forms.",
                        "Utilisez l'une de ces formes.",
                    ),
                )
            )
            continue
        cited_period = auto_notes.format_period(start, frequency)
        try:
            window = await wds.get_data_from_vector_by_reference_period_range(
                [ctx.vector_id], start.isoformat(), end.isoformat()
            )
            rows = [o for s in window.series for o in s.observations]
        except _SOFT:
            rows = []
        if not rows:
            last = latest[0] if latest else "?"
            problems.append(
                _problem(
                    ctx.index,
                    "period",
                    pick(
                        lang,
                        f"No value is published for {figure.period}; the latest is {last}.",
                        f"Aucune valeur n'est publiée pour {figure.period} ; la dernière est "
                        f"{last}.",
                    ),
                    pick(lang, "Check the period.", "Vérifiez la période."),
                )
            )
            continue
        row = rows[-1]
        flag = _flag_problem(ctx.index, row, cited_period, lang)
        if flag is not None:
            problems.append(flag)
        if figure.value is not None and row.value is not None:
            candidates = [r for r in rows if r.value is not None]
            if not any(
                not _value_problems(
                    ctx.index,
                    figure,
                    r.value,
                    r.scale_multiplier,
                    None,
                    cited_period,
                    None,
                    lang,
                )
                for r in candidates
                if r.value is not None
            ):
                problems.extend(
                    _value_problems(
                        ctx.index,
                        figure,
                        row.value,
                        row.scale_multiplier,
                        series_ctx.scale if series_ctx else None,
                        cited_period,
                        latest,
                        lang,
                    )
                )
        elif row.value is None and flag is None:
            problems.append(
                _problem(
                    ctx.index,
                    "period",
                    pick(
                        lang,
                        f"No value is published for {cited_period} ({row.status or '..'}).",
                        f"Aucune valeur n'est publiée pour {cited_period} ({row.status or '..'}).",
                    ),
                    pick(
                        lang,
                        "Say so rather than giving a figure.",
                        "Dites-le plutôt que de donner un chiffre.",
                    ),
                )
            )
        if latest is not None and figure.value is not None:
            newer = _newer(ctx.index, cited_period, latest, question, lang)
            if newer is not None:
                problems.append(newer)
    return problems


def _check_combinations(ctxs: Sequence[_Ctx], summed: bool, lang: str) -> list[AnswerProblem]:
    problems: list[AnswerProblem] = []
    tables: dict[int, list[_Ctx]] = {}
    for ctx in ctxs:
        if ctx.product_id is not None:
            tables.setdefault(ctx.product_id, []).append(ctx)
    if summed:
        for pid, group in tables.items():
            if len(group) < 2:
                continue
            chained = any(
                (b := auto_notes.price_basis(c.members)) and b[0] == "chained" for c in group
            )
            footnote = any(
                auto_notes.not_additive(text)
                for c in group[:1]
                if c.cube is not None
                for text in auto_notes.footnotes_for(c.cube, c.members)
            )
            if chained or footnote:
                problems.append(
                    _problem(
                        None,
                        "sum",
                        pick(
                            lang,
                            f"Components of table {_table(pid)} do not add up to its totals"
                            + (" (chained dollars)." if chained else "."),
                            f"Les composantes du tableau {_table(pid)} ne s'additionnent pas "
                            "pour donner ses totaux"
                            + (" (dollars enchaînés)." if chained else "."),
                        ),
                        pick(
                            lang,
                            "Cite the published total instead of a sum.",
                            "Citez le total publié plutôt qu'une somme.",
                        ),
                    )
                )
    if len(tables) >= 2:
        for rule in rules_for("check_answer", {"product_ids": sorted(tables)}):
            cited = sorted(set(rule.product_ids) & set(tables))
            if len(cited) < 2:
                continue
            names = ", ".join(_table(pid) for pid in cited)
            title = rule.title_fr if normalize_lang(lang) == "fr" else rule.title_en
            problems.append(
                _problem(
                    None,
                    "fitness_rule",
                    pick(lang, f"{names}: {title}.", f"{names} : {title}."),
                    pick(
                        lang,
                        f"Read the '{rule.key}' caveat in the data calls' provenance.caveats "
                        "before comparing levels.",
                        f"Lisez la mise en garde « {rule.key} » dans provenance.caveats des "
                        "appels de données avant de comparer des niveaux.",
                    ),
                )
            )
    return problems


async def _check_boc(
    index: int, figure: CitedFigure, question: str, lang: str
) -> list[AnswerProblem]:
    name = str(figure.boc_series)
    try:
        latest_result = await boc.get_observations([name], recent=1, lang=lang)
    except _SOFT as exc:
        return [
            _problem(
                index,
                "series",
                str(exc).split(" Fix:")[0],
                pick(
                    lang,
                    "Check the series name (boc_search_series).",
                    "Vérifiez le nom de la série (boc_search_series).",
                ),
            )
        ]
    latest_obs = next(
        (o for o in reversed(latest_result.observations) if o.values.get(name) is not None), None
    )
    latest = (latest_obs.ref_date.isoformat(), latest_obs.values.get(name)) if latest_obs else None
    if figure.period is None or figure.value is None:
        return []
    try:
        start, end = _window(figure.period)
    except ValueError:
        return []
    try:
        window = await boc.get_observations(
            [name], start_date=start.isoformat(), end_date=end.isoformat(), lang=lang
        )
    except _SOFT:
        return []
    values = [o.values.get(name) for o in window.observations]
    values = [v for v in values if v is not None]
    problems: list[AnswerProblem] = []
    if not values:
        problems.append(
            _problem(
                index,
                "period",
                pick(
                    lang,
                    f"No value is published for {figure.period}.",
                    f"Aucune valeur n'est publiée pour {figure.period}.",
                ),
                pick(lang, "Check the period.", "Vérifiez la période."),
            )
        )
    elif not any(
        not _value_problems(index, figure, v, 1, None, figure.period, None, lang) for v in values
    ):
        problems.extend(
            _value_problems(index, figure, values[-1], 1, None, figure.period, None, lang)
        )
    if latest is not None:
        last_day = latest[0]
        if last_day > end.isoformat() and figure.period[:4] not in question:
            problems.append(
                _problem(
                    index,
                    "newer_period",
                    pick(
                        lang,
                        f"A newer value is published: {last_day} ({_fmt(latest[1] or 0)}).",
                        f"Une valeur plus récente est publiée : {last_day} ({_fmt(latest[1] or 0)}).",
                    ),
                    pick(
                        lang,
                        f"Report {last_day}, or say why {figure.period} is used.",
                        f"Donnez {last_day}, ou expliquez pourquoi {figure.period} est retenu.",
                    ),
                )
            )
    return problems


async def check_answer(
    question: str, figures: list[CitedFigure], summed: bool, lang: str
) -> AnswerCheck:
    lang = normalize_lang(lang)
    wds.use_lang(lang)
    if not question.strip():
        raise InvalidInput(
            pick(lang, "question must not be empty.", "question ne doit pas être vide.")
        )
    if not figures or len(figures) > MAX_FIGURES:
        raise InvalidInput(
            pick(
                lang,
                f"figures needs 1 to {MAX_FIGURES} figures. Fix: pass each figure the answer "
                "reports, with its source id.",
                f"figures doit contenir de 1 à {MAX_FIGURES} chiffres. Correctif : passez "
                "chaque chiffre de la réponse avec l'identifiant de sa source.",
            )
        )
    problems: list[AnswerProblem] = []
    statcan: list[_Ctx] = []
    checked = 0
    for index, figure in enumerate(figures):
        if figure.vector_id is not None or (figure.product_id and figure.coordinate):
            statcan.append(_Ctx(index, figure))
        elif figure.boc_series:
            problems.extend(await _check_boc(index, figure, question, lang))
            checked += 1
        else:
            problems.append(
                _problem(
                    index,
                    "series",
                    pick(
                        lang,
                        "The figure has no source id.",
                        "Le chiffre n'a pas d'identifiant de source.",
                    ),
                    pick(
                        lang,
                        "Pass vector_id, product_id with coordinate, or boc_series.",
                        "Passez vector_id, product_id avec coordinate, ou boc_series.",
                    ),
                )
            )
    if statcan:
        problems.extend(await _check_statcan(statcan, question, lang))
        problems.extend(_check_combinations(statcan, summed, lang))
        checked += sum(1 for c in statcan if c.vector_id is not None)
    problems.sort(key=lambda p: (p.figure is None, p.figure or 0))
    return AnswerCheck(
        problems=problems,
        checked=checked,
        provenance=make_provenance(
            source="statcan-wds" if statcan else "boc",
            url=_WDS_URL if statcan else "https://www.bankofcanada.ca/valet/",
            cached=False,
            schema_name="answer_check.AnswerCheck",
            coverage=pick(
                lang,
                "Re-read from the sources just now; only problems are listed.",
                "Relu aux sources à l'instant ; seuls les problèmes sont listés.",
            ),
            lang=lang,
        ),
    )
