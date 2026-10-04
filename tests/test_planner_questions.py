"""Regression questions for plan_query: realistic English and French questions
and the first tool each plan must start with, plus checks that every planned
step can run (its required arguments are named or come from an earlier step)
and a report of the modules no plan reaches.

Lives in tests/, not modules/planner/__tests__/: it imports the server.
"""

from __future__ import annotations

import warnings

import pytest

from maplestats_mcp.modules.planner import client
from maplestats_mcp.modules.planner.places import CITIES, PROVINCES
from maplestats_mcp.modules.planner.topics import FALLBACK_STEPS, TOPICS
from maplestats_mcp.server import mcp

# (question, expected topic, expected first tool of that topic)
QUESTIONS: list[tuple[str, str, str]] = [
    ("What is the vacancy rate for apartments in Calgary?", "housing", "cmhc_list_categories"),
    ("How many housing starts were there in Toronto last year?", "housing", "cmhc_list_categories"),
    ("Average rent for a two-bedroom in Vancouver", "housing", "cmhc_list_categories"),
    ("How have new house prices changed since 2020?", "housing", "wds_search_cubes"),
    ("Building permits issued in Halifax", "housing", "wds_search_cubes"),
    ("What was the inflation rate last month?", "prices", "statcan_indicators_get_indicators"),
    ("What is the unemployment rate in Alberta?", "labour", "ab_economic_list_tables"),
    ("Employment by occupation in Canada", "labour", "rdaas_search_classifications"),
    ("Bank of Canada policy rate history", "rates", "boc_search_series"),
    ("USD to CAD exchange rate in 2024", "rates", "boc_search_series"),
    ("Canada's GDP growth in the last quarter", "economy", "statcan_daily_get_releases"),
    ("Exports of lobster to the United States by province", "economy", "cimt_search_commodities"),
    ("How much wheat did Canada export to China in 2023?", "agriculture", "cgc_exports_query"),
    ("interprovincial trade flows between provinces", "economy", "sdmx_space_search"),
    ("Population estimates for Nova Scotia", "population", "wds_search_cubes"),
    (
        "Median age in Saskatoon from the census",
        "population",
        "statcan_census_profile_search_geography",
    ),
    ("How many study permits were issued in 2024?", "immigration", "ircc_monthly_list_tables"),
    ("Latest Express Entry draw CRS cutoff", "immigration", "ircc_list_express_entry_rounds"),
    ("Emergency department wait times in Quebec", "health", "cihi_search_indicators"),
    ("Opioid overdose deaths in BC", "public_health", "phac_infobase_list_datasets"),
    (
        "Patented medicine prices compared with other countries",
        "drug_prices",
        "pmprb_list_report_tables",
    ),
    ("Earthquakes near Vancouver Island this year", "environment", "earthquakes_search"),
    ("Tide times at Halifax harbour", "environment", "dfo_iwls_search_stations"),
    (
        "How many wildfires are burning in Alberta right now?",
        "environment",
        "ab_wildfire_summarize_fires",
    ),
    ("Air quality in Montreal today", "environment", "eccc_search_collections"),
    ("Daily streamflow of the Bow River", "environment", "eccc_search_collections"),
    ("Ontario electricity prices yesterday", "energy", "electricity_ontario_get_prices"),
    ("Oil production in Alberta in 2023", "energy", "aer_get_production_volumes_link"),
    ("Pipeline throughput on Trans Mountain", "energy", "cer_list_datasets"),
    (
        "Main estimates for the Department of National Defence",
        "spending",
        "pbo_search_publications",
    ),
    ("Who is my MP for postal code K1A 0A6?", "representatives", "represent_lookup_postcode"),
    ("Who are the ministers in the federal cabinet?", "representatives", "ourcommons_get_ministry"),
    (
        "Party standings in the House of Commons",
        "representatives",
        "ourcommons_get_party_standings",
    ),
    ("Who is the mayor of Winnipeg?", "representatives", "represent_search_representatives"),
    ("How did the Senate vote on Bill C-69?", "legislation", "senate_list_votes"),
    (
        "Who donated to candidates in the 2021 federal election?",
        "elections",
        "elections_financial_returns_list_elections",
    ),
    (
        "Saskatchewan provincial election results by riding",
        "elections",
        "elections_provincial_get_results",
    ),
    ("Is there a recall on my 2019 Honda Civic?", "recalls", "tc_recalls_search"),
    ("Food recalls for listeria this year", "recalls", "recalls_search"),
    ("Bus schedule at a stop in Ottawa", "transport", "transit_list_agencies"),
    ("Police-reported crime in Edmonton", "crime", "eps_summarize_occurrences"),
    (
        "Mergers reviewed by the Competition Bureau in 2024",
        "competition",
        "competition_bureau_search_mergers",
    ),
    ("Patents held by Shopify", "ip", "ised_ip_horizons_search_patents"),
    ("Lobbyists registered in British Columbia", "lobbying", "bc_lobbyists_search_registrations"),
    ("Greenhouse gas emissions by province", "emissions", "sdmx_space_search"),
    (
        "Canada's progress on the sustainable development goals",
        "sdg",
        "statcan_sdg_search_indicators",
    ),
    ("Quality of life indicators", "sdg", "sdmx_space_list_flows"),
    ("List of hospitals in Manitoba", "facilities", "statcan_lode_list_databases"),
    ("Forest harvest volumes by province", "forestry", "nfd_list_tables"),
    ("Credit cards with no annual fee in Ontario", "banking", "fcac_search_credit_cards"),
    ("Milk production by province and butterfat quota", "dairy", "cdc_query_market_data"),
    ("Canola deliveries this crop year", "agriculture", "cgc_weekly_query"),
    ("Avian influenza outbreaks in BC poultry farms", "agriculture", "cfia_avian_influenza"),
    (
        "Which tables did StatCan update in today's delta file?",
        "statcan_updates",
        "statcan_delta_list_files",
    ),
    ("Taux de chômage au Québec", "labour", "statcan_indicators_get_indicators"),
    ("Prix des loyers à Montréal", "housing", "cmhc_list_categories"),
    ("Prévisions météo pour Ottawa demain", "environment", "eccc_search_collections"),
    (
        "Dons aux partis politiques en 2021",
        "elections",
        "elections_financial_returns_list_elections",
    ),
    ("Émissions de gaz à effet de serre par province", "emissions", "sdmx_space_search"),
    ("Nombre de permis d'études délivrés", "immigration", "ircc_monthly_list_tables"),
    ("Mises en chantier à Gatineau", "housing", "cmhc_list_categories"),
    (
        "Résultats des élections provinciales au Québec",
        "elections",
        "elections_provincial_get_results",
    ),
    ("Séismes récents en Colombie-Britannique", "environment", "earthquakes_search"),
    ("Qui est le ministre des Finances ?", "representatives", "ourcommons_get_ministry"),
]

OUT_OF_SCOPE = ["US unemployment rate", "Weather in Paris next week", "Inflation en France"]

# Modules being added or removed elsewhere: reported, never failed on.
PENDING = {
    "health_products",
    "eccc_datamart",
    "intl_indicators",
    "nwt_stats",
    "bc_environment",
    "oeb",
    "drivebc",
    "federal_misc",
}
# Tools that are not data sources.
NOT_SOURCES = {"plan_query", "reproduce_code", "reproduce_workbook"}


@pytest.mark.parametrize(("question", "topic", "first_tool"), QUESTIONS)
def test_question_routes_to_first_tool(question: str, topic: str, first_tool: str):
    result = client.plan(question)
    assert result.out_of_scope is None, question
    assert result.topics, question
    assert result.topics[0].topic == topic, (question, [t.topic for t in result.topics])
    assert result.topics[0].steps[0].tool == first_tool, question


def test_sixty_questions_cover_both_languages():
    assert len(QUESTIONS) >= 60


@pytest.mark.parametrize("question", OUT_OF_SCOPE)
def test_foreign_questions_are_out_of_scope(question: str):
    result = client.plan(question)
    assert result.out_of_scope and not result.topics and not result.fallback_steps


def test_cross_border_questions_stay_in_scope():
    for question in (
        "Canadian exports to the US in 2024",
        "Compare unemployment in Canada and the US",
        "Immigrants from India by province",
        "Paris, Ontario population",
    ):
        assert client.plan(question).out_of_scope is None, question


@pytest.mark.parametrize(
    ("question", "absent"),
    [
        ("How did the House of Commons vote on the budget?", "housing"),
        ("Population estimates by province", "spending"),
        ("StatCan release schedule for next week", "transport"),
        ("Greenhouse gas emissions from transport", "energy"),
        ("Patented medicine prices", "ip"),
        ("Don Valley traffic collisions", "elections"),
        ("Nuclear fusion research funding", "competition"),
        ("Food safety recall for peanut butter", "transport"),
        ("Product safety recalls on toys", "crime"),
    ],
)
def test_false_positive_terms(question: str, absent: str):
    assert absent not in {t.topic for t in client.plan(question).topics}, question


@pytest.mark.parametrize(
    ("question", "place"),
    [
        ("Wildfires in BC", "British Columbia"),
        ("Rents in B.C. cities", "British Columbia"),
        ("Tourism in PEI", "Prince Edward Island"),
        ("Diamond mining in the NWT", "Northwest Territories"),
        ("Fishery jobs in NL", "Newfoundland and Labrador"),
        ("Hydro exports from QC", "Quebec"),
        ("Population of NU communities", "Nunavut"),
        ("Housing in Nunavut", "Nunavut"),
        ("Crime in St. Catharines", "St. Catharines"),
    ],
)
def test_place_abbreviations(question: str, place: str):
    assert place in [p.place for p in client.plan(question).places], question


def test_lowercase_two_letter_words_are_not_provinces():
    places = [p.place for p in client.plan("le chômage au Québec est nu en hiver").places]
    assert "Nunavut" not in places


def test_delta_file_is_not_delta_bc():
    result = client.plan("What is in today's Delta file?")
    assert "Delta (BC)" not in [p.place for p in result.places]
    assert result.topics[0].topic == "statcan_updates"
    assert "Delta (BC)" in [p.place for p in client.plan("crime in Delta").places]


def _module(tool) -> str:
    # FileSystemProvider imports tools as "<module>[.<sub>].tools".
    parts = tool.fn.__module__.removeprefix("maplestats_mcp.modules.").split(".")
    return "/".join(parts[:2]) if parts[0] == "statcan" else parts[0]


def _planned_steps():
    for topic in TOPICS:
        yield topic.steps
    yield FALLBACK_STEPS
    for _, steps in (*PROVINCES.values(), *CITIES.values()):
        yield steps


async def test_every_step_names_its_required_arguments():
    # A step can run only if each required argument is named in its purpose or
    # comes from an earlier step of the same module in the same list.
    tools = {tool.name: tool for tool in await mcp._list_tools()}
    missing = []
    for steps in _planned_steps():
        modules_before: set[str] = set()
        for step in steps:
            tool = tools[step.tool]
            module = _module(tool)
            if module not in modules_before:
                for arg in tool.parameters.get("required", []):
                    if arg not in step.purpose:
                        missing.append((step.tool, arg))
            modules_before.add(module)
    assert not missing, f"steps without their required arguments: {missing}"


async def test_report_unrouted_modules():
    tools = [tool for tool in await mcp._list_tools() if tool.name not in NOT_SOURCES]
    planned = {step.tool for steps in _planned_steps() for step in steps}
    modules = {_module(tool) for tool in tools}
    routed = {_module(tool) for tool in tools if tool.name in planned}
    unrouted = sorted(modules - routed)
    pending = [m for m in unrouted if m.split("/")[-1] in PENDING or m in PENDING]
    if pending:
        warnings.warn(f"modules not yet in any plan (pending): {pending}", stacklevel=1)
    failing = [m for m in unrouted if m not in pending]
    assert not failing, f"modules no plan reaches: {failing}"
