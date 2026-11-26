"""Build a multi-source plan for a plain-language question.

No network: the plan comes from the curated topic and place maps in
topics.py and places.py. search_tools finds one tool by keywords; this
finds the several sources a question needs and says how they fit.
"""

from __future__ import annotations

import re
import unicodedata
from functools import cache

from maplestats_mcp import config, gis_profile
from maplestats_mcp.catalogue import tool_enabled
from maplestats_mcp.modules.planner import blocked, calls, cues
from maplestats_mcp.modules.planner.places import (
    CITIES,
    CITY_PROVINCES,
    CITY_SHADOWS,
    PROVINCE_ALIASES,
    PROVINCE_CODES,
    PROVINCES,
    SHARED_CITY_NAMES,
)
from maplestats_mcp.modules.planner.schemas import PlaceMatch, QueryPlan, StepOut, TopicMatch
from maplestats_mcp.modules.planner.topics import (
    CROSS_BORDER_TERMS,
    FALLBACK_STEPS,
    FOREIGN_CODES,
    FOREIGN_PLACES,
    TOPICS,
    UK_COVERED_TERMS,
    UK_PLACES,
    US_COVERED_TERMS,
    US_PLACES,
    PlanStep,
    Topic,
)
from maplestats_mcp.modules.planner.topics_fr import (
    GUIDANCE_FR,
    LIMITS_FR,
    out_of_scope_fr,
    to_french,
)
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput
from maplestats_mcp.shared.fitness import notes_for
from maplestats_mcp.shared.i18n import normalize_lang

_MAX_TOPICS = 4
_GUIDANCE = (
    (
        "Run the steps in order within each topic; each result's provenance gives the URL and "
        "date to cite."
    ),
    (
        "Fetch the figures with these tools and report the reference period they return. Do "
        "not stop at a table number and answer from a web search or memory: those often hold "
        "older or revised values. For the latest figure, ask for the latest periods (latest_n, "
        "recent, last_n_observations), not a date range: your sense of today's date may be out "
        "of date."
    ),
    (
        "Before combining sources, align geography (province, CMA, city), period (calendar vs "
        "fiscal year, month vs quarter) and units, and say where they differ."
    ),
    ("Cite each figure's source; do not merge numbers from different sources into one series."),
    "If a step finds nothing, use search_tools with its purpose as the query.",
    (
        "check_answer re-reads the StatCan and Bank of Canada figures you will cite, "
        "given the question, and returns only the problems."
    ),
    (
        "For a ratio, a ranking of places, compound annual growth or a count of changes "
        "(rate moves) across those series, call calc_ratio, calc_rank, calc_cagr or "
        "calc_count_changes rather than doing the arithmetic."
    ),
)
# A step whose purpose names the place asked about ("Alberta fires...") moves
# ahead of national steps; "BC" is how purposes name British Columbia.
_PLACE_WORDS = {"British Columbia": ("British Columbia", "BC ")}

# Tools that serve one city's portal, and the places a question must name for them
# to belong in its plan (the city or its province). An Edmonton and Calgary rent
# question was planned with RentSafeTO and Toronto's short-term rentals, and an
# Ottawa restaurant question started with Toronto's DineSafe (2026-11-15, issue
# #265). A question that names no place keeps them.
_CITY_TOOLS = {
    "toronto_": ("Toronto", "Ontario"),
    "calgary_": ("Calgary", "Alberta"),
    "eps_": ("Edmonton", "Alberta"),
    "ets_": ("Edmonton", "Alberta"),
    "epcor_": ("Edmonton", "Alberta"),
    "opendatasoft_vancouver_": ("Vancouver", "British Columbia"),
}

# Tools that serve one province only, and the province a question must name, or name
# a city of, for them to belong in its plan: "transit alerts in Calgary" listed BC
# Transit and DriveBC (2026-11-15, issue #275). Unlike a city tool above, one of
# these is dropped only when every place the question names has a known province
# and none is theirs; a place whose province is unknown keeps them.
_PROVINCE_TOOLS = {
    "bc_transit_": "British Columbia",
    "drivebc_": "British Columbia",
    "bc_env_": "British Columbia",
    "bc_lobbyists_": "British Columbia",
    "ab_wildfire_": "Alberta",
    "aer_": "Alberta",
    "bcer_": "British Columbia",
}
_PROVINCE_LABELS = frozenset(label for label, _ in PROVINCES.values())


def _normalize(text: str) -> str:
    # Map the characters the ASCII step would drop: a typographic apostrophe
    # ("compte d’épargne") must read as "'", and "œufs" as "oeufs".
    for char, plain in (("’", "'"), ("‘", "'"), ("œ", "oe"), ("Œ", "oe"), ("æ", "ae")):
        text = text.replace(char, plain)
    stripped = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^a-z0-9'\- ]", " ", stripped.lower()).split())


@cache
def _pattern(term: str) -> re.Pattern[str]:
    # A term is a whole word or phrase, plus an English or French plural on its
    # last word; "car" never meets "career". A trailing "*" marks a stem
    # ("affordab*"). The left edge allows an apostrophe or hyphen, so French
    # elisions ("l'influenza", "d'oeufs") still meet "influenza" and "oeuf".
    if term.endswith("*"):
        return re.compile(rf"(?<![a-z0-9]){re.escape(term[:-1])}")
    if term.endswith("y") and not term.endswith(("ay", "ey", "oy", "uy")):
        body = rf"{re.escape(term[:-1])}(?:y|ies)"
    else:
        body = rf"{re.escape(term)}(?:s|es)?"
    return re.compile(rf"(?<![a-z0-9]){body}(?![a-z0-9])")


def _matches(term: str, text: str) -> bool:
    return _pattern(term).search(text) is not None


def _pattern_hits(topic: Topic, text: str) -> list[str]:
    # A pattern's named groups hold the word it was looking for, which is what the
    # plan reports ("reconcile", not "reconcile my workbook of 300 vector").
    hits = []
    for pattern in topic.patterns:
        found = re.search(pattern, text)
        if found:
            hits.append(next((group for group in found.groupdict().values() if group), found[0]))
    return hits


def _blank(text: str, phrases: tuple[str, ...]) -> str:
    for phrase in phrases:
        text = _pattern(phrase).sub(" | ", text)
    return text


def _place_score(step: PlanStep, labels: list[str]) -> int:
    for label in labels:
        for word in _PLACE_WORDS.get(label, (label,)):
            if word in step.purpose:
                return 1
    return 0


def _ordered(topic: Topic, text: str, labels: list[str]) -> list[StepOut]:
    # Steps the question's own words point at come first (an earthquake
    # question starts with the earthquake tool), then steps for the place it
    # names; the sort is stable, so a chain of steps keeps its order.
    def score(step: PlanStep) -> int:
        term_hit = any(_matches(term, text) for term in step.terms) or any(
            re.search(pattern, text) for pattern in step.patterns
        )
        return 2 * term_hit + _place_score(step, labels)

    steps = sorted(topic.steps, key=score, reverse=True)
    relevant = [step for step in steps if _available(step) and _for_places(step, labels)]
    # A topic never loses all its steps to the side-trip cues.
    lean = [step for step in relevant if _side_trip_cued(step, text)]
    return [_step_out(step) for step in lean or relevant]


def _step_out(step: PlanStep) -> StepOut:
    return StepOut(tool=step.tool, purpose=step.purpose, call=calls.call_for(step))


def _for_places(step: PlanStep, labels: list[str]) -> bool:
    """False for a step that serves other places or provinces than the ones the question names.

    A question that names no place keeps every step but the one-province dashboards
    (cues.PROVINCE_ONLY_TOOLS), which are for a question about that province.
    """
    for prefix, province in cues.PROVINCE_ONLY_TOOLS.items():
        if step.tool.startswith(prefix):
            return province in {_province_of(label) for label in labels}
    if not labels:
        return True
    if step.places and not _serves(step.places, labels):
        return False
    for prefix, places in _CITY_TOOLS.items():
        if step.tool.startswith(prefix):
            return any(label in places for label in labels)
    for prefix, province in _PROVINCE_TOOLS.items():
        if step.tool.startswith(prefix):
            provinces = {_province_of(label) for label in labels}
            return None in provinces or province in provinces
    return True


def _serves(places: tuple[str, ...], labels: list[str]) -> bool:
    """Whether a step that reads data for `places` answers a question naming `labels`.

    A place the step lists answers itself. A province it lists (a province-wide table)
    answers a question about any city of that province; a province named answers a step
    for a city of it. A question about Ottawa is not answered by a step for Toronto.
    """
    for label in labels:
        province = _province_of(label)
        if label in places:
            return True
        if label not in _PROVINCE_LABELS and province in places:
            return True
        if label in _PROVINCE_LABELS and any(CITY_PROVINCES.get(p) == label for p in places):
            return True
    return False


def _side_trip_cued(step: PlanStep, text: str) -> bool:
    """False for a source most questions do not need, when the question does not ask for it.

    The cues are the step's own terms and patterns plus cues.SIDE_TRIPS' words, so a step
    that names its own cues keeps them (the census archive's "2011", the boundary maps'
    "boundaries").
    """
    side_trip = next(
        (words for prefix, words in cues.SIDE_TRIPS.items() if step.tool.startswith(prefix)), None
    )
    if side_trip is None or not (side_trip or step.terms or step.patterns):
        return True
    return any(_matches(term, text) for term in (*side_trip, *step.terms)) or any(
        re.search(pattern, text) for pattern in step.patterns
    )


def _place_cued(step: PlanStep, text: str) -> bool:
    """False for a place's side source (Edmonton Transit) the question does not touch."""
    return not step.cues or any(_matches(term, text) for term in step.cues)


def _province_of(label: str) -> str | None:
    """The province a place label is in; None when it is not known."""
    if label in _PROVINCE_LABELS:
        return label
    return CITY_PROVINCES.get(label)


def _available(step: PlanStep) -> bool:
    """False for a tool a setting has switched off on this server (statcan_pumf_tabulate on
    the Render backup, the PURE geospatial class under MAPLE_GIS=0), so a plan never sends
    the model to a tool call_tool will refuse. Every step kind comes through here: a topic's
    (`_ordered`), a place's and the fallback's (`_steps`)."""
    return tool_enabled(step.tool)


def _without_hidden_names(plan_out: QueryPlan) -> QueryPlan:
    """Under MAPLE_GIS=0, cut the words that point at a hidden tool.

    A step already went with its tool. What is left is prose written when the tool
    existed: a caveat that says to use it, a "(from nrcan_geo_locate)" in a purpose. It runs
    after the French is chosen, so a French plan loses the same words as an English one.
    """

    def steps(items: list[StepOut]) -> list[StepOut]:
        return [
            step.model_copy(update={"purpose": gis_profile.without_pointers(step.purpose)})
            for step in items
        ]

    for topic in plan_out.topics:
        topic.steps = steps(topic.steps)
        topic.caveats = [c for c in topic.caveats if not gis_profile.names_hidden_tool(c)]
    for place in plan_out.places:
        place.steps = steps(place.steps)
    plan_out.fallback_steps = steps(plan_out.fallback_steps)
    return plan_out


def _steps(steps: tuple[PlanStep, ...], text: str = "", topical: bool = False) -> list[StepOut]:
    """A place's or the fallback's steps; once a topic matched, only those the question touches."""
    return [
        _step_out(step)
        for step in steps
        if _available(step) and (not topical or _place_cued(step, text))
    ]


def _places(
    question: str, text: str, foreign: str | None = None, topical: bool = False
) -> list[PlaceMatch]:
    # An English possessive ("Alberta's population") must still name the place.
    text = re.sub(r"(\w)'s\b", r"\1", text)
    places: list[PlaceMatch] = []
    seen: set[str] = set()
    for alias, (label, steps) in CITIES.items():
        if foreign and alias in SHARED_CITY_NAMES:
            continue
        city_text = _blank(text, CITY_SHADOWS.get(alias, ()))
        if f" {alias} " in f" {city_text} " and label not in seen:
            seen.add(label)
            places.append(PlaceMatch(place=label, kind="city", steps=_steps(steps, text, topical)))
    province_keys = {key for key in PROVINCES if f" {key} " in f" {text} "}
    province_keys |= {
        target for alias, target in PROVINCE_ALIASES.items() if f" {alias} " in f" {text} "
    }
    # Codes count only in capitals as typed: "QC" and "NL", not French "nu". Dotted
    # forms ("B.C.", "N.B.") are the same codes: in a data question "N.B." is New
    # Brunswick far more often than a Latin nota bene.
    capitals = set(re.findall(r"\b[A-Z]{2}\b", question.replace(".", "")))
    province_keys |= {target for code, target in PROVINCE_CODES.items() if code in capitals}
    # "Quebec" alone is the province; "Quebec City" was taken as the city above.
    if "quebec" in province_keys and "Quebec City" in seen and text.count("quebec") == 1:
        province_keys.discard("quebec")
    for key in sorted(province_keys):
        label, steps = PROVINCES[key]
        places.append(PlaceMatch(place=label, kind="province", steps=_steps(steps, text, topical)))
    return places


def places_named(question: str) -> list[PlaceMatch]:
    """The Canadian provinces and cities a question names (check_answer reads them)."""
    text = _normalize(question)
    return _places(question, text, _foreign_place(question, text))


def normalize(text: str) -> str:
    """Lower case, accents and punctuation stripped, as the planner matches text."""
    return _normalize(text)


def _foreign_place(question: str, text: str) -> str | None:
    for place in FOREIGN_PLACES:
        if _matches(place, text):
            return place.rstrip("*")
    capitals = set(re.findall(r"\b[A-Z]{2,3}\b", question.replace(".", "")))
    return next((code for code in FOREIGN_CODES if code in capitals), None)


def _french(plan_out: QueryPlan) -> QueryPlan:
    # Translate after planning: step order and place scoring read the English
    # purposes, so the plan is the same in both languages, only worded in French.
    def steps(items: list[StepOut]) -> list[StepOut]:
        return [step.model_copy(update={"purpose": to_french(step.purpose)}) for step in items]

    for topic in plan_out.topics:
        topic.label = to_french(topic.label)
        topic.steps = steps(topic.steps)
        topic.caveats = [to_french(caveat) for caveat in topic.caveats]
    for place in plan_out.places:
        place.place = to_french(place.place, place=True)
        place.steps = steps(place.steps)
    plan_out.fallback_steps = steps(plan_out.fallback_steps)
    plan_out.guidance = list(GUIDANCE_FR)
    return plan_out


def _add_fitness_notes(plan_out: QueryPlan, lang: str) -> QueryPlan:
    # The fitness-for-use notes for the tools and tables a topic's steps name go
    # after its own caveats, already in the plan's language; a table number in
    # the question itself ("36-10-0434") is fetched by the first topic's steps,
    # so its notes go there. A note shared by several topics goes on the first
    # (best-matching) one only: the same paragraph four times would bury the
    # topic caveats.
    seen: set[str] = set()
    for rank, topic in enumerate(plan_out.topics):
        calls = [(step.tool, {"purpose": step.purpose}) for step in topic.steps]
        if rank == 0:
            calls.append(("", {"question": plan_out.question}))
        for tool, arguments in calls:
            for note in notes_for(tool, arguments, lang, in_plan=True):
                if note not in seen and note not in topic.caveats:
                    topic.caveats.append(note)
                seen.add(note)
    return plan_out


# French function words that English questions do not use. A question with two
# of them, outside hyphenated place names ("Rivière-du-Loup"), is French: a
# client that sends a French question without lang='fr' still gets a French
# plan (one did, and answered in English).
_FRENCH_WORDS = frozenset(
    {
        *("le", "la", "les", "des", "du", "de", "au", "aux", "un", "une", "est", "sont"),
        *("quel", "quelle", "quels", "quelles", "combien", "dans", "pour", "depuis"),
        *("avec", "entre", "qui", "que", "qu", "et", "ou", "sur", "à"),
    }
)


def looks_french(question: str) -> bool:
    """Whether a question is written in French (two French function words)."""
    words = set()
    for token in question.lower().replace("’", "'").split():
        if "-" in token:
            continue
        for part in re.split(r"'", token):
            part = part.strip('.,;:!?()«»"')
            if part in _FRENCH_WORDS:
                words.add(part)
    return len(words) >= 2


def plan(question: str, lang: str = "en") -> QueryPlan:
    french = normalize_lang(lang) == "fr"
    if not question.strip():
        raise InvalidInput(
            "La question ne doit pas être vide." if french else "question must not be empty."
        )
    text = _normalize(question)
    foreign = _foreign_place(question, text)
    places = _places(question, text, foreign)
    labels = [place.place for place in places]

    out_of_scope = None
    border = any(_matches(term, text) for term in CROSS_BORDER_TERMS)
    uk_covered = foreign in UK_PLACES and any(_matches(term, text) for term in UK_COVERED_TERMS)
    us_covered = foreign in US_PLACES and any(_matches(term, text) for term in US_COVERED_TERMS)
    crosses = border or uk_covered or us_covered
    if foreign and not places and not crosses:
        out_of_scope = (
            out_of_scope_fr(foreign)
            if french
            else (
                f"The question is about {foreign}, outside Canada; this server holds Canadian "
                "public data only, so no plan is given. Name a Canadian place, or ask about "
                "trade, exchange rates or migration between Canada and that country."
            )
        )

    # A question about the United Kingdom alone ("UK inflation") puts the ONS
    # plan first; "UK" is matched as typed, so it is no topic term.
    uk_question = uk_covered and not border and not places
    # Likewise the United States alone ("US 10-year Treasury yield") puts the
    # Fed plan first.
    us_question = us_covered and not border and not places
    scored = []
    if out_of_scope is None:
        for topic in TOPICS:
            # A topic whose every step is a hidden tool (places, under MAPLE_GIS=0) would
            # match a question and answer with no step.
            if not any(_available(step) for step in topic.steps):
                continue
            topic_text = _blank(text, topic.shadows)
            hits = [term.rstrip("*") for term in topic.terms if _matches(term, topic_text)]
            hits += _pattern_hits(topic, topic_text)
            own_country = (uk_question and topic.key == "united_kingdom") or (
                us_question and topic.key == "united_states"
            )
            if own_country and foreign not in hits:
                hits.insert(0, str(foreign))
            if hits:
                scored.append((len(hits), topic, hits, topic_text))
    if scored:
        # Once a topic matched, a place's side sources the question does not touch (Edmonton
        # Transit for a rent question) stay out; a question that names only a place keeps them.
        places = _places(question, text, foreign, topical=True)
    scored.sort(
        key=lambda item: (
            (uk_question and item[1].key == "united_kingdom")
            or (us_question and item[1].key == "united_states"),
            item[0],
        ),
        reverse=True,
    )
    topics = [
        TopicMatch(
            topic=topic.key,
            label=topic.label,
            matched_terms=hits,
            steps=_ordered(topic, topic_text, labels),
            caveats=list(topic.caveats),
        )
        for _, topic, hits, topic_text in scored[:_MAX_TOPICS]
    ]

    # A step two topics share (the census income table under both "population" and
    # "income") is listed once, under the topic that ranks first: the plan is read again
    # at every later step, and the same 700 characters twice were pure cost.
    shown: set[tuple[str, str]] = set()
    for match in topics:
        fresh = [step for step in match.steps if (step.tool, step.purpose) not in shown]
        shown.update((step.tool, step.purpose) for step in fresh)
        match.steps = fresh

    result = QueryPlan(
        question=question,
        topics=topics,
        places=places,
        fallback_steps=[] if topics or out_of_scope else _steps(FALLBACK_STEPS),
        out_of_scope=out_of_scope,
        guidance=list(_GUIDANCE),
        provenance=make_provenance(
            source="maplestats-planner",
            url="docs://catalogue",
            cached=False,
            schema_name="planner.QueryPlan",
            limits=LIMITS_FR
            if french
            else "curated topic and place map; not every tool is listed, use search_tools "
            "for anything the plan does not cover",
            lang="fr" if french else "en",
        ),
    )
    planned = _add_fitness_notes(_french(result) if french else result, lang)
    # Last, once the French is chosen: a step on a StatCan path that answered with its bot
    # check lately is marked and moved behind the working route (blocked.py); a no-op while no
    # path is known to be challenged.
    planned = blocked.mark_blocked(planned, french)
    return planned if config.get_gis_enabled() else _without_hidden_names(planned)
