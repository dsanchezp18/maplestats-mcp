"""Build a multi-source plan for a plain-language question.

No network: the plan comes from the curated topic and place maps in
topics.py and places.py. search_tools finds one tool by keywords; this
finds the several sources a question needs and says how they fit.
"""

from __future__ import annotations

import re
import unicodedata
from functools import cache

from maplestats_mcp.modules.planner.places import (
    CITIES,
    CITY_SHADOWS,
    PROVINCE_ALIASES,
    PROVINCE_CODES,
    PROVINCES,
)
from maplestats_mcp.modules.planner.schemas import PlaceMatch, QueryPlan, StepOut, TopicMatch
from maplestats_mcp.modules.planner.topics import (
    CROSS_BORDER_TERMS,
    FALLBACK_STEPS,
    FOREIGN_CODES,
    FOREIGN_PLACES,
    TOPICS,
    PlanStep,
    Topic,
)
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput

_MAX_TOPICS = 4
_GUIDANCE = (
    (
        "Run the steps in order within each topic; each result's provenance gives the source "
        "URL and date to cite."
    ),
    (
        "Before combining sources, align geography (province, CMA, city), period (calendar vs "
        "fiscal year, month vs quarter) and units, and say where they differ."
    ),
    (
        "Report each figure with its source; do not merge numbers from different sources "
        "into one series."
    ),
    "If a step finds nothing, use search_tools with the step's purpose as the query.",
)
# A step whose purpose names the place asked about ("Alberta fires...") moves
# ahead of national steps; "BC" is how purposes name British Columbia.
_PLACE_WORDS = {"British Columbia": ("British Columbia", "BC ")}


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
        term_hit = any(_matches(term, text) for term in step.terms)
        return 2 * term_hit + _place_score(step, labels)

    steps = sorted(topic.steps, key=score, reverse=True)
    return [StepOut(tool=step.tool, purpose=step.purpose) for step in steps]


def _steps(steps: tuple[PlanStep, ...]) -> list[StepOut]:
    return [StepOut(tool=step.tool, purpose=step.purpose) for step in steps]


def _places(question: str, text: str) -> list[PlaceMatch]:
    # An English possessive ("Alberta's population") must still name the place.
    text = re.sub(r"(\w)'s\b", r"\1", text)
    places: list[PlaceMatch] = []
    seen: set[str] = set()
    for alias, (label, steps) in CITIES.items():
        city_text = _blank(text, CITY_SHADOWS.get(alias, ()))
        if f" {alias} " in f" {city_text} " and label not in seen:
            seen.add(label)
            places.append(PlaceMatch(place=label, kind="city", steps=_steps(steps)))
    province_keys = {key for key in PROVINCES if f" {key} " in f" {text} "}
    province_keys |= {
        target for alias, target in PROVINCE_ALIASES.items() if f" {alias} " in f" {text} "
    }
    # Codes count only in capitals as typed: "QC" and "NL", not French "nu".
    capitals = set(re.findall(r"\b[A-Z]{2}\b", question.replace(".", "")))
    province_keys |= {target for code, target in PROVINCE_CODES.items() if code in capitals}
    # "Quebec" alone is the province; "Quebec City" was taken as the city above.
    if "quebec" in province_keys and "Quebec City" in seen and text.count("quebec") == 1:
        province_keys.discard("quebec")
    for key in sorted(province_keys):
        label, steps = PROVINCES[key]
        places.append(PlaceMatch(place=label, kind="province", steps=_steps(steps)))
    return places


def _foreign_place(question: str, text: str) -> str | None:
    for place in FOREIGN_PLACES:
        if _matches(place, text):
            return place.rstrip("*")
    capitals = set(re.findall(r"\b[A-Z]{2,3}\b", question.replace(".", "")))
    return next((code for code in FOREIGN_CODES if code in capitals), None)


def plan(question: str) -> QueryPlan:
    if not question.strip():
        raise InvalidInput("question must not be empty.")
    text = _normalize(question)
    places = _places(question, text)
    labels = [place.place for place in places]

    out_of_scope = None
    foreign = _foreign_place(question, text)
    crosses = any(_matches(term, text) for term in CROSS_BORDER_TERMS)
    if foreign and not places and not crosses:
        out_of_scope = (
            f"The question is about {foreign}, outside Canada; this server holds Canadian "
            "public data only, so no plan is given. Name a Canadian place, or ask about "
            "trade, exchange rates or migration between Canada and that country."
        )

    scored = []
    if out_of_scope is None:
        for topic in TOPICS:
            topic_text = _blank(text, topic.shadows)
            hits = [term.rstrip("*") for term in topic.terms if _matches(term, topic_text)]
            if hits:
                scored.append((len(hits), topic, hits, topic_text))
    scored.sort(key=lambda item: item[0], reverse=True)
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

    return QueryPlan(
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
            limits="curated topic and place map; not every tool is listed, use search_tools "
            "for anything the plan does not cover",
        ),
    )
