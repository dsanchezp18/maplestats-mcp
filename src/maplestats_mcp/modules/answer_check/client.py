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
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from maplestats_mcp.modules.answer_check.schemas import AnswerCheck, AnswerProblem, CitedFigure
from maplestats_mcp.modules.boc import client as boc
from maplestats_mcp.modules.planner.client import normalize, places_named
from maplestats_mcp.modules.planner.places import PROVINCE_ALIASES, PROVINCE_CODES, PROVINCES
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
from maplestats_mcp.shared.fitness_rules import RULES
from maplestats_mcp.shared.i18n import normalize_lang, pick
from maplestats_mcp.shared.json_utils import list_or_empty
from maplestats_mcp.shared.transform import (
    parse_period,
    period_end,
    period_label,
    period_start,
    shift_months,
)

MAX_FIGURES = 20
_SOFT = (NotFound, UpstreamError, UpstreamUnavailable, DataLocked, InvalidInput)


def _words(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


# Scale words by language: a French "billion" is 10^12 (a milliard is 10^9),
# so "2,06 billions de dollars" is 2.06 trillion. Every word in the unit counts
# ("milliers de milliards" is 10^12). A bare "m" is metres, not millions: only
# "M$" and "$M" are taken as the symbol. "milliard" is 10^9 in either language.
_MILLIONS_SYMBOL = re.compile(r"(?<![A-Za-z])M\$|\$M(?![A-Za-z])")
_SCALE_WORDS: dict[str, tuple[tuple[re.Pattern[str], float], ...]] = {
    "en": (
        (_words(r"\btrillions?\b"), 1e12),
        (_words(r"\bbillions?\b|\bbn\b|\bmilliards?\b"), 1e9),
        (_words(r"\bmillions?\b"), 1e6),
        (_words(r"\bthousands?\b|\bk\b"), 1e3),
    ),
    "fr": (
        (_words(r"\bbillions?\b"), 1e12),
        (_words(r"\bmilliards?\b|\bG\$|\bMds?\$?"), 1e9),
        (_words(r"\bmillions?\b"), 1e6),
        (_words(r"\bmilliers?\b|\bmille\b|\bk\b"), 1e3),
    ),
}
# A scale word is not a licence to round: "2 million" must not match 2.4 million.
_MAX_RELATIVE_TOLERANCE = 0.05
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
# A figure written as a percent or a change. Read against a series that is an
# index or a level (CPI 2002=100, dollars, persons), it is a change of that
# series, not its value: until 2026-11-03 a 3.1% Quebec inflation rate was told
# to "Use 167.7", the index level.
_PERCENT_UNIT = re.compile(
    r"%|per ?cent|percentage|pourcentage|pour ?cent|\bpct\b|change|variation|growth|"
    r"croissance|glissement|year[- ]over[- ]year|12[- ]month|12 mois|sur un an|"
    r"\binflation|\btaux\b",
    re.IGNORECASE,
)
_LEVEL_UNIT = re.compile(r"index|indice|dollar|\$|person|number|nombre|tonne", re.IGNORECASE)
_CHANGE_QUESTION = re.compile(
    r"inflation|\bchange|\bgrowth|\bgr[eo]w|increase|decrease|\brose\b|\bfell\b|"
    r"year[- ]over[- ]year|12[- ]month|per ?cent|percentage|%|variation|hausse|baisse|"
    r"croissance|augment|diminu|glissement|sur un an|pourcentage|pour ?cent",
    re.IGNORECASE,
)
_PERCENT_SERIES = re.compile(r"percent|pourcent|%|\brate\b|\btaux\b", re.IGNORECASE)

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
# Tables whose missing geographies no other table publishes, for questions
# matching the pattern: only these lead to the "not published" ladder (PUMF,
# custom tabulation, RTRA, RDC). Any other missing place is first looked for in
# other tables. 11-10-0090 (poverty by disability status) is Canada only.
_KNOWN_UNPUBLISHED: dict[int, re.Pattern[str]] = {
    11100090: re.compile(r"disab|incapacit|handicap", re.IGNORECASE),
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


def _number(raw: float | str, lang: str) -> tuple[float, float]:
    """(value, precision) of a cited number: 170 -> (170, 1), "2.060" -> (2.06, 0.001).

    Zeros before the decimal point are significant: 170 is rounded to the unit
    (until 2026-11-03 it counted as rounded to the ten, so 1000 matched 1400).
    Text keeps the written precision ("6.50"), which a JSON number loses.
    """
    if isinstance(raw, str):
        text = re.sub(r"[\s  $%]", "", raw)
        if "," in text and "." in text:
            # The separator written last is the decimal one: 1,234.5 or 1.234,5.
            thousands = "," if text.rfind(",") < text.rfind(".") else "."
            text = text.replace(thousands, "")
        if "," in text and (lang == "fr" or not re.fullmatch(r"-?\d{1,3}(,\d{3})+", text)):
            text = text.replace(",", ".")
        text = text.replace(",", "")
        try:
            number = Decimal(text)
        except ArithmeticError as exc:
            raise ValueError(raw) from exc
        if not number.is_finite():
            raise ValueError(raw)
        exponent = number.as_tuple().exponent
        return float(number), 10.0 ** min(0, int(exponent)) if isinstance(exponent, int) else 1.0
    if float(raw).is_integer():
        return float(raw), 1.0
    exponent = Decimal(repr(float(raw))).as_tuple().exponent
    return float(raw), 10.0 ** int(exponent) if isinstance(exponent, int) else 1.0


def _tolerance(cited: float, precision: float, word: float | None) -> float:
    """Half the cited precision, in full units; capped when a scale word is used."""
    tolerance = precision / 2
    if word is not None:
        tolerance = min(tolerance, _MAX_RELATIVE_TOLERANCE * abs(cited))
    return tolerance * (word or 1)


def _close(cited: float, published: float, tolerance: float) -> bool:
    return abs(cited - published) <= tolerance + 1e-9 * max(1.0, abs(published))


def _scale_word(unit: str | None, lang: str) -> float | None:
    if not unit:
        return None
    factor = 1e6 if _MILLIONS_SYMBOL.search(unit) else 1.0
    for pattern, scale in _SCALE_WORDS[normalize_lang(lang)]:
        if pattern.search(unit):
            factor *= scale
    return None if factor == 1.0 else factor


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


def _tokens(text: str) -> list[str]:
    """Whole words of a place name, accents, case and punctuation dropped."""
    return re.findall(r"[a-z0-9]+", normalize(re.sub(r"\([^)]*\)", " ", text)))


def _place_tokens(place: str) -> list[str]:
    """'London (Ontario)' -> london, 'Quebec City' -> quebec, 'Victoria, BC' -> victoria."""
    words = _tokens(place.split(",")[0])
    return words[:-1] if len(words) > 1 and words[-1] == "city" else words


def _contains(words: list[str], part: list[str]) -> bool:
    size = len(part)
    return any(words[i : i + size] == part for i in range(len(words) - size + 1))


_REGION_NAMES = frozenset(tuple(_tokens(label)) for label, _ in PROVINCES.values()) | frozenset(
    {("canada",)}
)


def _geo_match(place: str, member_name: str, kind: str = "place") -> bool:
    """Whether a Geography member is the place, matched on whole words.

    Until 2026-11-03 this was a prefix and substring test, so "Victoria" matched
    "Victoriaville, Quebec", "London" matched "Londonderry", and the province
    "Quebec" matched the CMA "Québec, Quebec". A province or Canada now matches
    only a member that is that name alone; a city matches whole words of the
    member's name before its comma ("Ottawa" in "Ottawa-Gatineau, Ontario part"),
    never a member that is a province ("Quebec City" is not "Quebec").
    """
    label = _place_tokens(place)
    if not label:
        return False
    whole = _tokens(member_name)
    if kind in ("province", "country"):
        return "," not in member_name and whole == label
    if "," not in member_name and tuple(whole) in _REGION_NAMES:
        return False
    return _contains(_tokens(member_name.split(",")[0]), label)


def _geo_exact(place: str, member_name: str) -> bool:
    return _tokens(member_name.split(",")[0]) == _place_tokens(place)


def _province_forms(label: str) -> set[str]:
    """Every way a question can write a province: name, aliases, two-letter code."""
    keys = {key for key, (name, _) in PROVINCES.items() if name == label}
    forms = set(keys)
    forms |= {alias for alias, key in PROVINCE_ALIASES.items() if key in keys}
    forms |= {code.lower() for code, key in PROVINCE_CODES.items() if key in keys}
    return {" ".join(_tokens(form)) for form in forms if _tokens(form)}


def _asked_places(question: str) -> list[tuple[str, str]]:
    """(place, kind) the question names; Canada only when it names no province or city.

    "Canadian workers in Alberta" asks about Alberta: until 2026-11-03 the word
    "Canadian" added Canada, so a Canada series passed for it.

    A province written right after a city ("Victoria, BC", "London (Ontario)")
    only says which city is meant: it is dropped, so a British Columbia figure
    no longer passes for a Victoria question (until 2026-11-03 it did). A
    province asked about on its own ("Ontario and Toronto") is kept.
    """
    named = [(p.place, p.kind) for p in places_named(question)]
    text = " ".join(_tokens(question))
    cities = [" ".join(_place_tokens(place)) for place, kind in named if kind == "city"]
    places = []
    for place, kind in named:
        if kind == "province" and cities:
            forms = "|".join(re.escape(form) for form in sorted(_province_forms(place)))
            qualified = forms and any(
                re.search(rf"\b{re.escape(city)}(?: city)? (?:{forms})\b", text) for city in cities
            )
            if qualified:
                continue
        places.append((place, kind))
    if not places and _CANADA.search(_AGENCY.sub(" ", question)):
        places.append(("Canada", "country"))
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


def _place_kind(place: str) -> str:
    named = places_named(place)
    if named:
        return named[0].kind
    return "country" if _CANADA.search(place) else "place"


def _pointer_tables(product_id: int, place: str, kind: str) -> list[tuple[str, list[str]]]:
    """Fitness rules naming other tables of the same subject that cover `kind` places.

    14-10-0287 (LFS by province) has no Toronto member; the rule
    lfs-subprovincial-moving-averages names 14-10-0459 and 14-10-0460, which do.
    """
    subject = str(product_id)[:4]
    words = {
        "city": ("metropolitan", "economic region"),
        "province": ("province", "provincial"),
    }.get(kind, ())
    found = []
    for rule in RULES:
        if product_id in rule.product_ids:
            continue
        tables = [p for p in rule.product_ids if str(p)[:4] == subject]
        note = rule.note_en.lower()
        if tables and (place.lower() in note or any(w in note for w in words)):
            found.append((rule.key, [_table(p) for p in tables]))
    return found


def _elsewhere(ctx: _Ctx, place: str, kind: str, lang: str) -> str:
    """Where to look for a place the cited table lacks: other tables first."""
    assert ctx.cube is not None and ctx.product_id is not None
    title = str(ctx.cube.get("cubeTitleFr" if lang == "fr" else "cubeTitleEn") or "")
    subject = re.split(r" by |, | selon | par ", title, maxsplit=1)[0].strip() or title
    geo_word = {
        "city": pick(lang, " census metropolitan area", " région métropolitaine de recensement"),
        "province": " province",
    }.get(kind, "")
    query = f"{subject}{geo_word}".strip()
    pointers = "; ".join(
        f"{', '.join(tables)} ({pick(lang, 'rule', 'règle')} {key})"
        for key, tables in _pointer_tables(ctx.product_id, place, kind)
    )
    also = pick(lang, f" Known: {pointers}.", f" Connus : {pointers}.") if pointers else ""
    return pick(
        lang,
        f"Find a table that has {place}: wds_search_cubes '{query}', then its "
        f"Geography members (wds_get_cube_metadata).{also} Say it is not published only if "
        "no table has it.",
        f"Cherchez un tableau qui a {place} : wds_search_cubes « {query} », puis ses "
        f"membres Géographie (wds_get_cube_metadata).{also} Dites qu'il n'est pas publié "
        "seulement si aucun tableau ne l'a.",
    )


async def _check_geography(ctx: _Ctx, question: str, lang: str) -> list[AnswerProblem]:
    """Each figure against its own place: its `geography`, else the places asked.

    A figure labelled Canada in a question about Ontario and Toronto is a Canada
    figure, not a wrong Toronto one (until 2026-11-03 the question's first place
    was applied to every figure).
    """
    geo = _geography(ctx)
    if geo is None or ctx.cube is None or ctx.product_id is None or ctx.coordinate is None:
        return []
    dim, member = geo
    series_geo = str(member.get("memberNameEn") or "")
    labelled = ctx.figure.geography
    wanted = [(labelled, _place_kind(labelled))] if labelled else _asked_places(question)
    if not wanted or any(_geo_match(place, series_geo, kind) for place, kind in wanted):
        return []
    shown_geo = auto_notes.member_name(member, lang)
    table_members = list_or_empty(dim, "member")
    table = _table(ctx.product_id)
    found: list[tuple[str, str, dict]] = []
    missing: list[tuple[str, str]] = []
    for place, kind in wanted:
        # An exact name first: "Victoria" is "Victoria, British Columbia", whatever
        # order the table lists its members in.
        matching = [m for m in table_members if _geo_match(place, str(m["memberNameEn"]), kind)]
        target = next(
            (m for m in matching if _geo_exact(place, str(m["memberNameEn"]))),
            matching[0] if matching else None,
        )
        if target is None:
            missing.append((place, kind))
        else:
            coordinate = _swap(
                ctx.coordinate, int(dim["dimensionPositionId"]), int(target["memberId"])
            )
            found.append((place, coordinate, target))
    known = _KNOWN_UNPUBLISHED.get(ctx.product_id)
    if not found and known is not None and known.search(question):
        geos = [auto_notes.member_name(m, lang) for m in table_members]
        return [await _not_published(ctx, missing[0][0], geos, question, lang)]
    names = ", ".join(place for place, _ in wanted)
    problem = (
        pick(
            lang,
            f"The series is for {shown_geo}, but the figure is labelled {labelled}.",
            f"La série porte sur {shown_geo}, mais le chiffre est présenté pour {labelled}.",
        )
        if labelled
        else pick(
            lang,
            f"The series is for {shown_geo}, but the question asks about {names}.",
            f"La série porte sur {shown_geo}, mais la question vise {names}.",
        )
    )
    if missing:
        absent = ", ".join(place for place, _ in missing)
        problem += pick(
            lang,
            f" Table {table} has no {absent} member.",
            f" Le tableau {table} n'a pas de membre {absent}.",
        )
    fixes = [
        pick(
            lang,
            f"Use table {table}, coordinate {coordinate} ({auto_notes.member_name(t, lang)}).",
            f"Utilisez le tableau {table}, coordonnée {coordinate} "
            f"({auto_notes.member_name(t, lang)}).",
        )
        for _, coordinate, t in found
    ]
    fixes += [_elsewhere(ctx, place, kind, lang) for place, kind in missing]
    return [_problem(ctx.index, "geography", problem, " ".join(fixes))]


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
                "La série n'est pas désaisonnalisée ; le chiffre principal est d'ordinaire "
                "celui de la série désaisonnalisée.",
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
    subject: tuple[str, str] | None = None,
) -> list[AnswerProblem]:
    """Compare a cited value with the published one; [] when they agree.

    `subject` (en, fr) replaces "The published value for <period>" in the message,
    for a value computed from several periods (a year's average).
    """
    assert figure.value is not None
    cited, precision = _number(figure.value, lang)
    word = _scale_word(figure.unit, lang)
    tolerance = _tolerance(cited, precision, word)
    full = published * multiplier
    if word is not None:
        if _close(cited * word, full, tolerance):
            return []
        cited_full = cited * word
    else:
        if _close(cited, full, tolerance):
            return []
        if multiplier != 1 and _close(cited, published, tolerance):
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
        if _close(cited_full * factor, full, tolerance * factor):
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
        if _close(cited_full, other_full, tolerance):
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
    en, fr = subject or (f"The published value for {period}", f"La valeur publiée pour {period}")
    return [
        _problem(
            index,
            "value",
            pick(
                lang,
                f"{en} is {shown}, not {_fmt(cited)}.",
                f"{fr} est {shown}, pas {_fmt(cited)}.",
            ),
            pick(
                lang,
                f"Use {shown}, or check the series and period.",
                f"Utilisez {shown}, ou vérifiez la série et la période.",
            ),
        )
    ]


def _flag_problems(
    index: int, rows: list[ObservationRow], label: str, frequency: Any, lang: str
) -> list[AnswerProblem]:
    """E, F and x flags of every row the cited period covers (a year of months too).

    One row is named by the cited `label`; several by their own periods.
    """

    def named(flagged: list[ObservationRow]) -> str:
        if len(rows) == 1:
            return label
        shown = [auto_notes.format_period(r.ref_period, frequency) for r in flagged]
        more = len(shown) - 3
        return ", ".join(shown[:3]) + (
            pick(lang, f" and {more} more", f" et {more} autres") if more > 0 else ""
        )

    suppressed = [r for r in rows if r.security_level_code == auto_notes.SECURITY_SUPPRESSED]
    unreliable = [
        r for r in rows if r.status_code == auto_notes.STATUS_TOO_UNRELIABLE and r not in suppressed
    ]
    caution = [
        r
        for r in rows
        if r.status_code == auto_notes.STATUS_USE_WITH_CAUTION
        and r not in suppressed
        and r not in unreliable
    ]
    problems: list[AnswerProblem] = []
    for flagged, what in (
        (suppressed, pick(lang, "suppressed for confidentiality (x)", "confidentiel (x)")),
        (unreliable, pick(lang, "too unreliable to be published (F)", "trop peu fiable (F)")),
    ):
        if flagged:
            problems.append(
                _problem(
                    index,
                    "quality_flag",
                    pick(lang, f"{named(flagged)}: {what}.", f"{named(flagged)} : {what}.")
                    if len(rows) > 1
                    else pick(lang, f"{label} is {what}.", f"{label} est {what}."),
                    pick(
                        lang,
                        "Do not report a figure: say it is not published and offer a broader "
                        "group or another period.",
                        "Ne donnez aucun chiffre : dites qu'il n'est pas publié et proposez un "
                        "groupe plus large ou une autre période.",
                    ),
                )
            )
    if caution:
        problems.append(
            _problem(
                index,
                "quality_flag",
                pick(
                    lang,
                    f"StatCan flags {named(caution)} 'use with caution' (E).",
                    f"Statistique Canada marque {named(caution)} « à utiliser avec prudence » (E).",
                ),
                pick(lang, "Report it with that caveat.", "Citez-le avec cette mise en garde."),
            )
        )
    return problems


def _coarse_value(
    index: int,
    figure: CitedFigure,
    values: list[ObservationRow],
    label: str,
    frequency: Any,
    scale: str | None,
    lang: str,
) -> list[AnswerProblem]:
    """A value cited for a year (or quarter) of a finer series: its average or total
    matches; one period's value is named as that period; else the average is given."""
    assert figure.value is not None
    cited = _fmt(_number(figure.value, lang)[0])
    numbers = [r.value for r in values if r.value is not None]
    multiplier = values[-1].scale_multiplier
    average, total = sum(numbers) / len(numbers), sum(numbers)

    def matches(published: float) -> bool:
        return not _value_problems(index, figure, published, multiplier, None, label, None, lang)

    if matches(average) or matches(total):
        return []
    # Half up, as StatCan rounds: 1930.2 / 12 = 160.85 is shown 160.9.
    shown_average = float(
        Decimal(str(round(average, 9))).quantize(
            Decimal(1).scaleb(-values[-1].decimals), rounding=ROUND_HALF_UP
        )
    )
    one = next((r for r in values if r.value is not None and matches(r.value)), None)
    if one is not None:
        period = auto_notes.format_period(one.ref_period, frequency)
        mean = _fmt(shown_average * multiplier)
        return [
            _problem(
                index,
                "period",
                pick(
                    lang,
                    f"{cited} is the value for {period}; the {label} average is {mean}.",
                    f"{cited} est la valeur de {period} ; la moyenne de {label} est {mean}.",
                ),
                pick(
                    lang,
                    f"Cite it as {period}, or use {mean} as the {label} average.",
                    f"Citez-la pour {period}, ou utilisez {mean} comme moyenne de {label}.",
                ),
            )
        ]
    word = _scale_word(figure.unit, lang) or 1
    low, high = (_fmt(v * multiplier / word) for v in (min(numbers), max(numbers)))
    count = len(numbers)
    found = _value_problems(
        index,
        figure,
        shown_average,
        multiplier,
        scale,
        label,
        None,
        lang,
        subject=(
            f"The {label} average of the {count} published values ({low} to {high})",
            f"La moyenne de {label} des {count} valeurs publiées ({low} à {high})",
        ),
    )
    for problem in found:
        if problem.check == "value":
            problem.fix += pick(
                lang,
                f" Say it is the average of {count} values, or cite one period.",
                f" Précisez que c'est la moyenne de {count} valeurs, ou citez une période.",
            )
    return found


def _newer(
    index: int,
    period: str,
    latest: tuple[str, float | None],
    question: str,
    lang: str,
    key: str | None = None,
) -> AnswerProblem | None:
    """`key` is the latest period at the cited granularity (2026 for 2026-09)."""
    latest_period, latest_value = latest
    # A question that names the cited year asks for that period on purpose.
    if period[:4] in question:
        return None
    # Compared as dates: as text, a quarter "2026-Q3" sorted after the month
    # "2026-07" ('Q' > '0') and was reported as newer.
    try:
        if parse_period(key or latest_period)[0] <= parse_period(period)[0]:
            return None
    except ValueError:
        if (key or latest_period) <= period:
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


async def _series_infos(ids: list[int]) -> dict[int, dict[str, Any]]:
    """Series info for every id; one bad id must not lose the others.

    WDS answers HTTP 500 for a whole getSeriesInfoFromVector batch when one id
    does not exist (999999999999, checked live 2026-11-03), so a failed batch is
    retried one id at a time and the ids that fail are left out (each gets a
    `series` problem). Only when every id fails is it an outage, raised as such.
    """
    if not ids:
        return {}
    try:
        return await context.series_info_raw(ids)
    except _SOFT:
        if len(ids) == 1:
            raise
    found: dict[int, dict[str, Any]] = {}
    failure: Exception | None = None
    for vector_id in ids:
        try:
            found.update(await context.series_info_raw([vector_id]))
        except _SOFT as exc:
            failure = exc
    if not found and failure is not None:
        raise failure
    return found


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
    infos = await _series_infos(ids)
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


def _percent_mode(figure: CitedFigure, series_unit: str | None, question: str) -> str | None:
    """'unit' when the figure is written as a percent or a change, 'question' when
    it has no unit and the question asks for a change; None when the figure is
    a level, or the series itself is in percent (an unemployment rate)."""
    if figure.value is None or (series_unit and _PERCENT_SERIES.search(series_unit)):
        return None
    said = (figure.unit or "").strip()
    if said:
        return "unit" if _PERCENT_UNIT.search(said) and not _LEVEL_UNIT.search(said) else None
    return "question" if _CHANGE_QUESTION.search(question) else None


def _percent_text(value: float, precision: float, lang: str) -> str:
    places = max(1, -int(Decimal(str(precision)).adjusted())) if precision < 1 else 1
    shown = Decimal(str(round(value, 9))).quantize(Decimal(1).scaleb(-places), ROUND_HALF_UP)
    return pick(lang, f"{shown}%", f"{str(shown).replace('.', ',')} %")


async def _percent_change(
    ctx: _Ctx,
    start: date,
    ppy: int | None,
    cited_period: str,
    current: list[ObservationRow],
    unit: str | None,
    level_ok: bool,
    lang: str,
    notes: list[str],
) -> list[AnswerProblem]:
    """A percent figure read against an index or level series: compared with the
    series' change over 12 months and over one period, never with its level.

    `current` holds the rows of the cited period (one month, or the twelve of a
    cited year, whose average is compared with the year before's). `level_ok`
    accepts the level too, when nothing says the figure is a percent.
    """
    figure = ctx.figure
    assert figure.value is not None and ctx.vector_id is not None
    cited, precision = _number(figure.value, lang)
    numbers = [r.value for r in current if r.value is not None]
    if not numbers:
        return []
    multiplier = current[-1].scale_multiplier
    if level_ok and any(
        not _value_problems(ctx.index, figure, v, multiplier, None, cited_period, None, lang)
        for v in [*numbers, sum(numbers) / len(numbers)]
    ):
        return []
    what = (
        pick(lang, "an index", "un indice")
        if unit and re.search(r"=\s*100|index|indice", unit, re.IGNORECASE)
        else pick(lang, "a level", "un niveau")
    )
    shown_unit = f" ({unit})" if unit else ""
    if ppy is None and len(current) == 1 and ctx.cube is not None:
        # A day cited for a monthly or quarterly series ("2026-09-01") is its period.
        ppy = {6: 12, 9: 4, 12: 1}.get(int(ctx.cube.get("frequencyCode") or 0))
    if ppy not in (1, 2, 4, 12):
        notes.append(
            pick(
                lang,
                f"Figure {ctx.index} not checked: it is a percent and the series is {what}; "
                f"its change is computed for monthly, quarterly or annual periods only.",
                f"Chiffre {ctx.index} non vérifié : c'est un pourcentage et la série est "
                f"{what} ; sa variation n'est calculée que pour des mois, trimestres ou années.",
            )
        )
        return []
    assert ppy is not None
    step = 12 // ppy
    try:
        history = await wds.get_data_from_vector_by_reference_period_range(
            [ctx.vector_id],
            shift_months(start, -12).isoformat(),
            (start - timedelta(days=1)).isoformat(),
        )
        earlier = [o for s in history.series for o in s.observations if o.value is not None]
    except _SOFT:
        earlier = []
    average = sum(numbers) / len(numbers)
    # (months back, label of that period, change in percent or None when not published)
    changes: list[tuple[int, str, float | None]] = []
    for back in (12,) if step == 12 else (12, step):
        lo = shift_months(start, -back)
        hi = shift_months(lo, step) - timedelta(days=1)
        before = [r.value for r in earlier if lo <= r.ref_period <= hi and r.value is not None]
        label = period_label(lo, ppy)
        if len(before) != len(numbers) or not sum(before):
            changes.append((back, label, None))
            continue
        changes.append((back, label, (average / (sum(before) / len(before)) - 1) * 100))
    known = [(back, label, change) for back, label, change in changes if change is not None]
    missing = [label for _, label, change in changes if change is None]
    if not known:
        shown_missing = ", ".join(missing)
        notes.append(
            pick(
                lang,
                f"Figure {ctx.index} not checked: it is a percent and the series is {what}"
                f"{shown_unit}, but {shown_missing} is not published, so its change to "
                f"{cited_period} cannot be computed.",
                f"Chiffre {ctx.index} non vérifié : c'est un pourcentage et la série est "
                f"{what}{shown_unit}, mais {shown_missing} n'est pas publié ; sa variation "
                f"en {cited_period} ne peut pas être calculée.",
            )
        )
        return []
    tolerance = precision / 2
    if any(_close(cited, change, tolerance) for _, _, change in known):
        return []
    if missing:
        notes.append(
            pick(
                lang,
                f"Figure {ctx.index}: {', '.join(missing)} is not published, so only the change "
                f"from {known[0][1]} was compared.",
                f"Chiffre {ctx.index} : {', '.join(missing)} n'est pas publié ; seule la "
                f"variation depuis {known[0][1]} a été comparée.",
            )
        )
    parts = [
        (
            _percent_text(change, precision, lang),
            pick(
                lang,
                f"{_percent_text(change, precision, lang)} from {label}"
                + (" (12 months)" if back == 12 and step != 12 else ""),
                f"{_percent_text(change, precision, lang)} depuis {label}"
                + (" (sur 12 mois)" if back == 12 and step != 12 else ""),
            ),
        )
        for back, label, change in known
        if change is not None
    ]
    said = _percent_text(cited, precision, lang)
    listed = pick(lang, " and ", " et ").join(text for _, text in parts)
    others = "".join(pick(lang, f" (or {v})", f" (ou {v})") for v, _ in parts[1:])
    return [
        _problem(
            ctx.index,
            "value",
            pick(
                lang,
                f"The series is {what}{shown_unit}, not a percent: its change to {cited_period} "
                f"is {listed}, not {said}.",
                f"La série est {what}{shown_unit}, pas un pourcentage : sa variation en "
                f"{cited_period} est de {listed}, pas {said}.",
            ),
            pick(
                lang,
                f"Use {parts[0][0]}{others}, whichever change the question asks for, or check "
                "the series and period.",
                f"Utilisez {parts[0][0]}{others}, selon la variation demandée, ou vérifiez la "
                "série et la période.",
            ),
        )
    ]


async def _check_statcan(
    ctxs: list[_Ctx], question: str, lang: str, notes: list[str]
) -> list[AnswerProblem]:
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
        # Figures with a period are still re-read below; one without a
        # period can only be compared with the latest value, so it gets a note.
        for c in live:
            if c.figure.period is None and c.figure.value is not None:
                notes.append(_not_reread(c.index, "Statistics Canada WDS", lang))
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
        series_unit = series_ctx.unit if series_ctx else None
        problems.extend(_check_unit(ctx, series_unit, lang))
        percent = _percent_mode(figure, series_unit, question)
        level_ok = percent == "question" or not series_unit
        if percent and latest is not None:
            # A percent is a change: a newer period is named without its level.
            latest = (latest[0], None)
        if figure.period is None:
            if percent and latest is not None and latest_row is not None:
                try:
                    _, latest_ppy = parse_period(latest[0])
                except ValueError:
                    latest_ppy = None
                problems.extend(
                    await _percent_change(
                        ctx,
                        latest_row.ref_period,
                        latest_ppy,
                        latest[0],
                        [latest_row],
                        series_unit,
                        level_ok,
                        lang,
                        notes,
                    )
                )
            elif (
                figure.value is not None and latest_row is not None and latest_row.value is not None
            ):
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
        # A year cited for a monthly series covers twelve rows: it is labelled,
        # compared (with their average) and checked for flags as the year, not
        # as its first or last month (until 2026-11-03 "2024" read as "2024-01"
        # and only December's value and flags were checked).
        cited_ppy = parse_period(figure.period)[1]
        coarse = cited_ppy is not None and auto_notes.format_period(
            rows[0].ref_period, frequency
        ) != period_label(start, cited_ppy)
        cited_period = (
            period_label(start, cited_ppy)
            if coarse and cited_ppy is not None
            else auto_notes.format_period(start, frequency)
        )
        flags = _flag_problems(ctx.index, rows, cited_period, frequency, lang)
        problems.extend(flags)
        values = [r for r in rows if r.value is not None]
        scale = series_ctx.scale if series_ctx else None
        if values and figure.value is not None:
            if percent:
                problems.extend(
                    await _percent_change(
                        ctx,
                        start,
                        cited_ppy,
                        cited_period,
                        values,
                        series_unit,
                        level_ok,
                        lang,
                        notes,
                    )
                )
            elif coarse:
                problems.extend(
                    _coarse_value(ctx.index, figure, values, cited_period, frequency, scale, lang)
                )
            elif not any(
                not _value_problems(
                    ctx.index, figure, r.value, r.scale_multiplier, None, cited_period, None, lang
                )
                for r in values
                if r.value is not None
            ):
                last_row = values[-1]
                assert last_row.value is not None
                problems.extend(
                    _value_problems(
                        ctx.index,
                        figure,
                        last_row.value,
                        last_row.scale_multiplier,
                        scale,
                        cited_period,
                        latest,
                        lang,
                    )
                )
        elif not values and not flags:
            status = rows[-1].status or ".."
            problems.append(
                _problem(
                    ctx.index,
                    "period",
                    pick(
                        lang,
                        f"No value is published for {cited_period} ({status}).",
                        f"Aucune valeur n'est publiée pour {cited_period} ({status}).",
                    ),
                    pick(
                        lang,
                        "Say so rather than giving a figure.",
                        "Dites-le plutôt que de donner un chiffre.",
                    ),
                )
            )
        if latest is not None and latest_row is not None and figure.value is not None:
            # Newer at the cited granularity: 2026-09 is not newer than "2026".
            key = (
                period_label(period_start(latest_row.ref_period, cited_ppy), cited_ppy)
                if coarse and cited_ppy is not None
                else latest[0]
            )
            newer = _newer(ctx.index, cited_period, latest, question, lang, key)
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


def _not_reread(index: int, source: str, lang: str) -> str:
    return pick(
        lang,
        f"Figure {index} not re-read: {source} did not answer, so its value is unchecked.",
        f"Chiffre {index} non relu : {source} n'a pas répondu, sa valeur n'est donc pas vérifiée.",
    )


async def _check_boc(
    index: int, figure: CitedFigure, question: str, lang: str, notes: list[str]
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
    if figure.value is None:
        return []
    if figure.period is None:
        # No period cited: the answer presents the value as current, so it is
        # compared with the latest observation, as the StatCan path does.
        if latest is None or latest[1] is None:
            notes.append(_not_reread(index, "Bank of Canada Valet", lang))
            return []
        return _value_problems(index, figure, latest[1], 1, None, latest[0], None, lang)
    try:
        start, end = _window(figure.period)
    except ValueError:
        return [
            _problem(
                index,
                "period",
                pick(
                    lang,
                    f"Period {figure.period!r} is not 2024, 2024-09, 2024-Q3 or 2024-09-01.",
                    f"La période {figure.period!r} n'est pas 2024, 2024-09, 2024-Q3 ou 2024-09-01.",
                ),
                pick(
                    lang, "Give the period in one of those forms.", "Utilisez l'une de ces formes."
                ),
            )
        ]
    try:
        window = await boc.get_observations(
            [name], start_date=start.isoformat(), end_date=end.isoformat(), lang=lang
        )
    except _SOFT:
        notes.append(_not_reread(index, "Bank of Canada Valet", lang))
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
    notes: list[str] = []
    statcan: list[_Ctx] = []
    checked = 0
    for index, figure in enumerate(figures):
        if figure.value is not None:
            try:
                _number(figure.value, lang)
            except ValueError:
                problems.append(
                    _problem(
                        index,
                        "value",
                        pick(
                            lang,
                            f"{figure.value!r} is not a number.",
                            f"{figure.value!r} n'est pas un nombre.",
                        ),
                        pick(
                            lang,
                            "Pass the number as written, e.g. 6.5 or '2.06'.",
                            "Passez le nombre tel qu'écrit, p. ex. 6.5 ou '2.06'.",
                        ),
                    )
                )
                continue
        if figure.vector_id is not None or (figure.product_id and figure.coordinate):
            statcan.append(_Ctx(index, figure))
        elif figure.boc_series:
            problems.extend(await _check_boc(index, figure, question, lang, notes))
            checked += 1
        else:
            # A figure from another source (CMHC, a provincial agency) is not a
            # mistake to fix: it is outside what this tool re-reads.
            notes.append(
                pick(
                    lang,
                    f"Figure {index} not checked: check_answer covers StatCan and Bank of "
                    "Canada figures.",
                    f"Chiffre {index} non vérifié : check_answer couvre les chiffres de "
                    "Statistique Canada et de la Banque du Canada.",
                )
            )
    if statcan:
        problems.extend(await _check_statcan(statcan, question, lang, notes))
        problems.extend(_check_combinations(statcan, summed, lang))
        checked += sum(1 for c in statcan if c.vector_id is not None)
    problems.sort(key=lambda p: (p.figure is None, p.figure or 0))
    return AnswerCheck(
        problems=problems,
        checked=checked,
        notes=notes,
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
