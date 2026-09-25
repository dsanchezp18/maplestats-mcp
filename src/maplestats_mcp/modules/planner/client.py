"""Build a multi-source plan for a plain-language question.

No network: the plan comes from the curated topic and place maps in
topics.py and places.py. search_tools finds one tool by keywords; this
finds the several sources a question needs and says how they fit.
"""

from __future__ import annotations

import re
import unicodedata

from maplestats_mcp.modules.planner.places import CITIES, PROVINCE_ALIASES, PROVINCES
from maplestats_mcp.modules.planner.schemas import PlaceMatch, QueryPlan, StepOut, TopicMatch
from maplestats_mcp.modules.planner.topics import FALLBACK_STEPS, TOPICS, PlanStep
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


def _normalize(text: str) -> str:
    stripped = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^a-z0-9'\- ]", " ", stripped.lower()).split())


def _matches(term: str, text: str, words: set[str]) -> bool:
    if " " in term or "'" in term or "-" in term:
        return f" {term}" in f" {text}"
    # Longer stems ("affordab", "demograph") match word prefixes; short
    # terms match whole words or plurals only, so "car" never hits "career".
    if len(term) >= 6:
        return any(word.startswith(term) for word in words)
    return term in words or f"{term}s" in words


def _steps(steps: tuple[PlanStep, ...]) -> list[StepOut]:
    return [StepOut(tool=step.tool, purpose=step.purpose) for step in steps]


def plan(question: str) -> QueryPlan:
    if not question.strip():
        raise InvalidInput("question must not be empty.")
    text = _normalize(question)
    words = set(text.replace("-", " ").split()) | set(text.split())

    scored = []
    for topic in TOPICS:
        hits = [term for term in topic.terms if _matches(term, text, words)]
        if hits:
            scored.append((len(hits), topic, hits))
    scored.sort(key=lambda item: item[0], reverse=True)
    topics = [
        TopicMatch(
            topic=topic.key,
            label=topic.label,
            matched_terms=hits,
            steps=_steps(topic.steps),
            caveats=list(topic.caveats),
        )
        for _, topic, hits in scored[:_MAX_TOPICS]
    ]

    places: list[PlaceMatch] = []
    seen: set[str] = set()
    for alias, (label, steps) in CITIES.items():
        if f" {alias} " in f" {text} " and label not in seen:
            seen.add(label)
            places.append(PlaceMatch(place=label, kind="city", steps=_steps(steps)))
    province_keys = {key for key in PROVINCES if f" {key} " in f" {text} "}
    province_keys |= {
        target for alias, target in PROVINCE_ALIASES.items() if f" {alias} " in f" {text} "
    }
    # "Quebec" alone is the province; "Quebec City" was taken as the city above.
    if "quebec" in province_keys and "Quebec City" in seen and text.count("quebec") == 1:
        province_keys.discard("quebec")
    for key in sorted(province_keys):
        label, steps = PROVINCES[key]
        places.append(PlaceMatch(place=label, kind="province", steps=_steps(steps)))

    return QueryPlan(
        question=question,
        topics=topics,
        places=places,
        fallback_steps=[] if topics else _steps(FALLBACK_STEPS),
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
