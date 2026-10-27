"""Fitness-for-use rules (shared/fitness_rules.py) and their matcher (shared/fitness.py).

The rules are only worth attaching to tool results if they are right, so these
tests pin what was checked: every product id a rule names is in VERIFIED_TABLES,
each looked up live with WDS getCubeMetadata on 2026-10-27 (title shown), and
every rule cites an official page.
"""

from __future__ import annotations

import json
import re
from urllib.parse import urlparse

import pytest

from maplestats_mcp.catalogue import CATALOGUE_PATH
from maplestats_mcp.modules.planner import resources
from maplestats_mcp.modules.planner.client import plan
from maplestats_mcp.shared.fitness import notes_for, product_ids_in, rules_for
from maplestats_mcp.shared.fitness_rules import RULES
from maplestats_mcp.shared.i18n import NBSP

# productId -> title, from getCubeMetadata on 2026-10-27. A new id in a rule
# must be checked live the same way and added here.
VERIFIED_TABLES = {
    11100066: "Market Basket Measure (MBM) thresholds for the reference family by MBM region, "
    "component and base year",
    11100090: "Poverty and low-income statistics by disability status",
    11100093: "Poverty and low-income statistics by selected demographic characteristics",
    11100104: "Market Basket Measure thresholds by MBM region and family size, in current dollars",
    11100135: "Low income statistics by age, gender and economic family type",
    11100136: "Low income statistics by economic family type",
    11100232: "Low income measure (LIM) thresholds by income source and household size",
    14100201: "Employment by industry, monthly, unadjusted for seasonality (SEPH)",
    14100220: "Employment and average weekly earnings for all employees by industry, monthly, SA",
    14100222: "Employment, average hourly and weekly earnings ... industrial aggregate, monthly, SA",
    14100223: "Employment and average weekly earnings ... by province and territory, monthly, SA",
    14100287: "Labour force characteristics, monthly, seasonally adjusted and trend-cycle",
    14100288: "Employment by class of worker, monthly, seasonally adjusted and unadjusted",
    14100296: "Labour force characteristics by occupation, monthly, unadjusted, inactive (NOC 2016)",
    14100355: "Employment by industry, monthly, SA and unadjusted, and trend-cycle, last 5 months",
    14100416: "Labour force characteristics by occupation, annual",
    14100421: "Labour force characteristics by occupation, monthly, unadjusted for seasonality",
    18100004: "Consumer Price Index, monthly, not seasonally adjusted",
    18100006: "Consumer Price Index, monthly, seasonally adjusted",
    18100256: "CPI statistics, measures of core inflation - Bank of Canada definitions",
    18100259: "Historical (real-time) releases of CPI statistics, measures of core inflation",
    36100104: "Gross domestic product, expenditure-based, Canada, quarterly",
    36100434: "Gross domestic product (GDP) at basic prices, by industry, monthly",
    98100001: "Population and dwelling counts: Canada, provinces and territories",
    98100002: "Population and dwelling counts: Canada and census subdivisions (municipalities)",
}

OFFICIAL_HOSTS = ("statcan.gc.ca", "bankofcanada.ca", "cmhc-schl.gc.ca")


def _keys(tool: str, arguments: dict) -> set[str]:
    return {rule.key for rule in rules_for(tool, arguments)}


def test_every_product_id_was_verified_live():
    named = {pid for rule in RULES for pid in rule.product_ids}
    assert named <= set(VERIFIED_TABLES), sorted(named - set(VERIFIED_TABLES))


def test_rule_keys_are_unique():
    keys = [rule.key for rule in RULES]
    assert len(keys) == len(set(keys))


@pytest.mark.parametrize("rule", RULES, ids=lambda rule: rule.key)
def test_rule_has_both_languages_and_an_official_source(rule):
    for text in (rule.title_en, rule.title_fr, rule.note_en, rule.note_fr, rule.checked):
        assert text.strip()
    assert rule.note_fr != rule.note_en
    assert rule.title_fr != rule.title_en
    # The French is written for a francophone reader, not copied.
    assert re.search(r"\b(le|la|les|des|une|pour|dans)\b", rule.note_fr)
    assert rule.sources
    for url in rule.sources:
        parsed = urlparse(url)
        assert parsed.scheme == "https", url
        assert parsed.hostname and parsed.hostname.endswith(OFFICIAL_HOSTS), url
    assert rule.tool_prefixes or rule.product_ids


def test_every_tool_prefix_names_a_real_tool():
    catalogue = json.loads(CATALOGUE_PATH.read_text(encoding="utf-8"))
    tools = {tool["name"] for module in catalogue["modules"].values() for tool in module["tools"]}
    for rule in RULES:
        for prefix in rule.tool_prefixes:
            assert any(name.startswith(prefix) for name in tools), (rule.key, prefix)


def test_match_by_tool_prefix():
    assert _keys("statcan_census_profile_get_data", {}) == {
        "census-random-rounding",
        "census-geography-vintage",
    }
    # The archive (2001-2016) is excluded from the 2021 rounding note only.
    assert _keys("statcan_census_profile_archive_get_download_link", {}) == {
        "census-geography-vintage"
    }
    assert _keys("statcan_pumf_tabulate", {}) == {"pumf-weights-and-release"}
    assert _keys("cmhc_get_table_data", {}) == {"cmhc-rental-market-reliability"}
    assert _keys("cmhc_list_categories", {}) == set()


@pytest.mark.parametrize(
    "arguments",
    [
        {"product_id": 14100287},
        {"product_id": "14100287"},
        {"product_id": "14-10-0287"},
        {"product_id": "14-10-0287-01"},
        {"product_id": "1410028701"},
        {"product_id": 1410028701},
        {"productId": 14100287},
        {"product_ids": [18100004, "14100287"]},
        {"query": "LFS table 14-10-0287-01, seasonally adjusted"},
        {"filters": {"table": "14-10-0287"}},
    ],
)
def test_match_by_product_id_in_any_spelling(arguments):
    assert 14100287 in product_ids_in(arguments)
    keys = _keys("wds_get_cube_metadata", arguments)
    assert {"lfs-vs-seph", "lfs-sampling-variability"} <= keys


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"vector_id": 41690973},  # 8 digits, but a vector: not mappable without a call
        {"query": "14100287"},  # a bare number outside a product-id argument
        {"date": "10-10-2023"},  # a date has the dashed shape
        {"product_id": 99999999},  # not a WDS table shape
        {"product_id": 17100009},  # a real table no rule names
        {"product_id": True},
    ],
)
def test_no_match_returns_empty(arguments):
    assert notes_for("wds_get_data_from_vectors", arguments, "en") == []


def test_unrelated_tool_returns_empty():
    assert notes_for("eccc_get_weather", {"station": "Ottawa"}, "fr") == []
    assert notes_for("", {}, "en") == []


def test_notes_follow_lang_with_french_spacing():
    english = notes_for("wds_get_cube_metadata", {"product_id": 36100434}, "en")
    french = notes_for("wds_get_cube_metadata", {"product_id": 36100434}, "fr-CA")
    assert len(english) == len(french) == 2  # GDP and classification rules
    assert english[0].startswith("Monthly GDP by industry")
    assert french[0].startswith("Le PIB mensuel par industrie")
    assert f"{NBSP}:" in french[0] or f"{NBSP};" in french[0]
    assert " :" not in french[0] and " ;" not in french[0]


def test_notes_are_in_rule_order_without_duplicates():
    notes = notes_for(
        "wds_get_cube_metadata",
        {"product_id": 14100201, "query": "14-10-0201 and 14-10-0220"},
        "en",
    )
    assert len(notes) == len(set(notes))
    order = [rule.key for rule in rules_for("x", {"product_id": 14100201})]
    assert order == ["lfs-vs-seph", "seph-january-2026-level-shift", "classification-versions"]


def test_docs_resource_lists_every_rule_in_both_languages():
    english = resources.planner_fitness_rules_doc()
    french = resources.planner_fitness_rules_doc_fr()
    for rule in RULES:
        assert rule.title_en in english
        assert rule.sources[0] in english
        assert rule.sources[0] in french
    assert "docs://planner/fr/regles-d-usage" in english
    assert "docs://planner/fitness-rules" in french
    assert "Tableaux" in french and "Tables" in english


def test_plan_adds_matching_notes_to_caveats():
    housing = plan("How have rents moved in Calgary since 2020?")
    caveats = housing.topics[0].caveats
    assert any(note.startswith("CMHC marks each Rental Market Survey") for note in caveats)
    # The topic's own caveat stays first: the notes are added after it.
    assert not caveats[0].startswith("CMHC marks")

    french = plan("How have rents moved in Calgary since 2020?", "fr")
    assert any(note.startswith("La SCHL attribue") for note in french.topics[0].caveats)


def test_plan_adds_notes_for_a_table_named_in_the_question():
    result = plan("What does table 36-10-0434 say about GDP growth?")
    caveats = [note for topic in result.topics for note in topic.caveats]
    assert any(note.startswith("Monthly GDP by industry") for note in caveats)


def test_plan_does_not_repeat_a_note_across_topics():
    result = plan("rents, housing starts and census shelter costs in Toronto and Calgary")
    caveats = [note for topic in result.topics for note in topic.caveats]
    fitness = {note for rule in RULES for note in (rule.note_en,)}
    added = [note for note in caveats if note in fitness]
    assert len(added) == len(set(added))
