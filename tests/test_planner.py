"""Tests for the plan_query planner.

Lives in tests/, not modules/planner/__tests__/: it imports the server,
and the server's FileSystemProvider imports every file under modules/.
"""

from __future__ import annotations

import pytest

from maplestats_mcp.modules.arcgis_hub.constants import PORTALS as ARCGIS_PORTALS
from maplestats_mcp.modules.ckan.constants import PORTALS as CKAN_PORTALS
from maplestats_mcp.modules.planner import client, topics_fr
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


def test_dairy_questions_in_both_languages():
    english = client.plan("butterfat price and milk quota")
    assert english.topics[0].topic == "dairy"
    assert english.topics[0].steps[0].tool == "cdc_query_market_data"
    french = client.plan("prix du beurre et gestion de l'offre")
    assert "dairy" in {t.topic for t in french.topics}


def test_no_topic_falls_back():
    result = client.plan("zebra migration")
    assert not result.topics and result.fallback_steps


def test_empty_question():
    with pytest.raises(InvalidInput):
        client.plan("  ")


def test_agriculture_routes_to_grain_and_agency_catalogues():
    result = client.plan("How much canola did Saskatchewan farmers deliver this crop year?")
    top = result.topics[0]
    assert top.topic == "agriculture"
    assert top.steps[0].tool == "cgc_weekly_query"
    french = client.plan("exportations de blé vers la Chine")
    assert "agriculture" in {t.topic for t in french.topics}


def test_animal_disease_questions_reach_the_cfia_tools():
    for question in (
        "How many farms had avian influenza in British Columbia this year?",
        "chronic wasting disease detections in Saskatchewan elk herds",
        "maladies à déclaration obligatoire chez les animaux terrestres",
        "cas de grippe aviaire au Québec",
        "influenza aviaire dans les élevages de volailles",
    ):
        result = client.plan(question)
        topic = next((t for t in result.topics if t.topic == "agriculture"), None)
        assert topic is not None, question
        tools = [s.tool for s in topic.steps]
        assert {"cfia_reportable_diseases", "cfia_avian_influenza"} <= set(tools), question
        # CKAN stays for rabies, aquatic diseases and food testing.
        ckan = [s for s in topic.steps if s.tool == "ckan_search_datasets"]
        assert "cfia-acia" in ckan[-1].purpose and "rabies" in ckan[-1].purpose


def test_committee_questions_route_to_committee_tools():
    english = client.plan("Which witnesses appeared at the finance committee meeting last week?")
    assert english.topics[0].topic == "committees"
    tools = [s.tool for s in english.topics[0].steps]
    assert tools == ["ourcommons_list_members", "ourcommons_get_member_roles"]
    # Meetings and testimony have no tool; the caveat says so.
    assert "not covered" in english.topics[0].caveats[0]
    french = client.plan("Qui a témoigné devant le comité de la santé ?")
    assert french.topics[0].topic == "committees"
    assert {"temoign", "comite"} <= set(french.topics[0].matched_terms)
    huis_clos = client.plan("réunions à huis clos du comité permanent des finances")
    assert "committees" in {t.topic for t in huis_clos.topics}


def test_typographic_apostrophes_and_ligatures():
    # The typographic apostrophe used to be dropped: "d’épargne" became "depargne".
    assert client._normalize("Compte d’épargne") == "compte d'epargne"
    assert client._normalize("Producteurs d’Œufs") == "producteurs d'oeufs"
    savings = client.plan("Quel compte d’épargne offre le meilleur taux ?")
    assert "banking" in {t.topic for t in savings.topics}
    eggs = client.plan("production d’œufs au Canada")
    assert "agriculture" in {t.topic for t in eggs.topics}
    offre = client.plan("prix du lait et gestion de l’offre")
    dairy = next(t for t in offre.topics if t.topic == "dairy")
    assert "gestion de l'offre" in dairy.matched_terms


def test_french_banking_spellings():
    for question in (
        "frais d'un compte chèque sans frais",
        "comparer les cartes de crédit au Québec",
        "forfait bancaire à la caisse populaire",
    ):
        result = client.plan(question)
        assert result.topics[0].topic == "banking", question


def test_english_possessive_still_names_the_place():
    # "Alberta's" missed Alberta until 2026-09-27 (the cross-source demo question).
    result = client.plan("Did Alberta's population boom tighten its rental market?")
    assert [p.place for p in result.places] == ["Alberta"]
    assert {t.topic for t in result.topics} >= {"housing", "population"}


def test_rate_hikes_reach_the_rates_topic():
    result = client.plan("What did the Bank of Canada's rate hikes do to new housing prices?")
    assert result.topics[0].topic == "rates"
    french = client.plan("Qu'ont fait les hausses des taux de la Banque du Canada au logement?")
    assert "rates" in {t.topic for t in french.topics}


def test_every_planner_string_has_french():
    # A step, caveat or label added in English only would show in English in a
    # French plan; fr() covers it through FR or the "search with portal=" rule.
    missing = sorted(
        {step.purpose for step in _all_steps() if topics_fr.fr(step.purpose) is None}
        | {topic.label for topic in TOPICS if topics_fr.fr(topic.label) is None}
        | {c for topic in TOPICS for c in topic.caveats if topics_fr.fr(c) is None}
        | {
            label
            for label, _ in (*PROVINCES.values(), *CITIES.values())
            if topics_fr.fr(label, place=True) is None
        }
    )
    assert not missing, missing


@pytest.mark.parametrize(
    ("question", "topic", "place"),
    [
        ("Quel est le taux de chômage à Montréal ?", "labour", "Montréal"),
        ("Loyers et mises en chantier dans la ville de Québec", "housing", "Ville de Québec"),
        ("feux de forêt en Colombie-Britannique cet été", "environment", "Colombie-Britannique"),
        ("indice des prix à la consommation en Nouvelle-Écosse", "prices", "Nouvelle-Écosse"),
        ("résultats des élections provinciales au Québec", "elections", "Québec"),
    ],
)
def test_french_plan_is_in_french(question, topic, place):
    english = client.plan(question)
    result = client.plan(question, lang="fr")
    assert result.topics[0].topic == english.topics[0].topic
    assert topic in {t.topic for t in result.topics}
    assert place in [p.place for p in result.places]
    # Same tools in the same order; only the wording changes.
    assert [s.tool for t in result.topics for s in t.steps] == [
        s.tool for t in english.topics for s in t.steps
    ]
    for match in result.topics:
        assert match.label == topics_fr.to_french(
            next(t.label for t in TOPICS if t.key == match.topic)
        )
    assert result.guidance[0].startswith("Exécutez")
    assert "search_tools" in (result.provenance.limits or "")
    assert result.provenance.reproduce.startswith("Pour obtenir")


def test_french_portal_step_and_fallback_and_scope():
    toronto = client.plan("données ouvertes de Toronto", lang="fr")
    assert toronto.places[0].steps[0].purpose == "recherche avec portal='toronto'"
    nothing = client.plan("xyzzy", lang="fr")
    assert nothing.fallback_steps[0].purpose.startswith("produits de données")
    abroad = client.plan("taux de chômage en France", lang="fr")
    assert abroad.out_of_scope is not None
    assert abroad.out_of_scope.startswith("La question porte sur")
    with pytest.raises(InvalidInput, match="ne doit pas"):
        client.plan(" ", lang="fr")


def test_english_plan_unchanged_by_default():
    result = client.plan("rents in Montreal")
    assert result.places[0].place == "Montreal"
    assert result.guidance[0].startswith("Run the steps")
