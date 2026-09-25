"""Tests for the plan_query planner.

Lives in tests/, not modules/planner/__tests__/: it imports the server,
and the server's FileSystemProvider imports every file under modules/.
"""

from __future__ import annotations

import pytest

from maplestats_mcp.modules.arcgis_hub.constants import PORTALS as ARCGIS_PORTALS
from maplestats_mcp.modules.ckan.constants import PORTALS as CKAN_PORTALS
from maplestats_mcp.modules.planner import client
from maplestats_mcp.modules.planner.places import CITIES, PROVINCES
from maplestats_mcp.modules.planner.topics import FALLBACK_STEPS, TOPICS
from maplestats_mcp.modules.socrata.constants import PORTALS as SOCRATA_PORTALS
from maplestats_mcp.server import mcp
from maplestats_mcp.shared.errors import InvalidInput


def _all_steps():
    for topic in TOPICS:
        yield from topic.steps
    yield from FALLBACK_STEPS
    for _, steps in (*PROVINCES.values(), *CITIES.values()):
        yield from steps


async def test_every_planned_tool_is_registered():
    registered = {tool.name for tool in await mcp._list_tools()}
    missing = sorted({step.tool for step in _all_steps()} - registered)
    assert not missing, f"plan names unregistered tools: {missing}"


def test_every_planned_portal_exists():
    portals = {
        "ckan_search_datasets": CKAN_PORTALS,
        "arcgis_hub_search_datasets": ARCGIS_PORTALS,
        "socrata_search_datasets": SOCRATA_PORTALS,
    }
    for step in _all_steps():
        if step.tool in portals and "portal='" in step.purpose:
            key = step.purpose.split("portal='", 1)[1].split("'", 1)[0]
            assert key in portals[step.tool], (step.tool, key)


def test_cross_source_question_gets_topics_and_place():
    result = client.plan("How have rents and mortgage rates changed in Calgary since 2020?")
    assert result.topics[0].topic == "housing"
    assert [p.place for p in result.places] == ["Calgary"]
    assert result.places[0].steps[0].tool == "socrata_search_datasets"
    assert not result.fallback_steps


def test_french_question_and_accents():
    result = client.plan("Quel est le taux de chômage et le loyer moyen à Montréal ?")
    keys = {t.topic for t in result.topics}
    assert {"labour", "housing"} <= keys
    assert [p.place for p in result.places] == ["Montreal"]


def test_quebec_city_versus_province():
    city = client.plan("crime in Quebec City")
    assert [p.place for p in city.places] == ["Quebec City"]
    province = client.plan("hospital wait times in Quebec")
    assert [p.place for p in province.places] == ["Quebec"]


def test_short_terms_do_not_match_inside_words():
    # "car" must not match "career", nor "age" "average".
    result = client.plan("career average")
    assert "transport" not in {t.topic for t in result.topics}


def test_no_topic_falls_back():
    result = client.plan("zebra migration")
    assert not result.topics and result.fallback_steps


def test_empty_question():
    with pytest.raises(InvalidInput):
        client.plan("  ")
