"""Realistic English questions must find the right tool through search_tools.

Clients see only search_tools, call_tool and plan_query, so a tool whose
docstring lacks the words people actually type is effectively invisible.
These are phrased the way a user asks, not the way a tool is named;
the French counterpart is test_french_discovery.py. Several expectations
accept a reasonable neighbour (e.g. CPI from the Bank of Canada rather
than StatCan) because either answers the question.
"""

from __future__ import annotations

import re

import pytest
from fastmcp import Client

from maplestats_mcp.server import mcp

TOP_N = 3

CASES = [
    ("What is Canada's current unemployment rate?", "statcan_indicators_get_indicators"),
    ("latest CPI inflation Canada", "boc_search_series"),
    ("Find a StatCan table on GDP by industry", "wds_search_cubes"),
    ("get data for a StatCan vector", "wds_get_data_from_vectors"),
    ("Bank of Canada policy interest rate history", "boc_search_series"),
    ("USD to CAD exchange rate daily", "boc_get_series"),
    ("Bank of Canada observations for several series at once", "boc_get_observations"),
    ("average rent Toronto CMHC", "cmhc_get_table_data"),
    ("housing starts by city", "cmhc_list_categories"),
    ("Express Entry CRS cutoff latest draw", "ircc_list_express_entry_rounds"),
    ("weather alerts in Alberta", "eccc_query_items"),
    ("river water level hydrometric station", "eccc_query_items"),
    ("tide predictions Halifax harbour", "dfo_iwls_get_water_levels"),
    ("recent earthquakes in British Columbia", "earthquakes_search"),
    ("food recall allergen", "recalls_search"),
    ("vehicle recall Honda Civic 2018", "tc_recalls_search"),
    ("search federal open data datasets", "ckan_search_datasets"),
    ("Calgary open data building permits", "socrata_search_datasets"),
    ("Vancouver open data street trees", "opendatasoft_vancouver_search_datasets"),
    ("Ottawa open data GIS layer", "arcgis_hub_search_datasets"),
    ("federal government tenders construction", "canadabuys_search_tenders"),
    ("federal corporation lookup by name", "ised_corporations_get_corporation"),
    ("trademark search", "ised_cipo_search_trademarks"),
    ("bill status in the House of Commons", "parliament_search_bills"),
    ("what did MPs say about housing in the House", "parliament_search_hansard"),
    ("Senate votes", "senate_list_votes"),
    ("Canada Gazette proposed regulations", "gazette_get_issue"),
    ("hospital wait times indicator", "cihi_search_indicators"),
    ("Census 2021 population of a city", "statcan_census_profile_get_data"),
    ("public use microdata Labour Force Survey", "statcan_pumf_search"),
    ("cross-tabulate PUMF microdata", "statcan_pumf_tabulate"),
    ("generate R code to reproduce this query", "reproduce_code"),
    ("Alberta economic dashboard unemployment", "ab_economic_get_data"),
    ("Edmonton bus real-time arrivals", "ets_get_stop_predictions"),
    ("TTC scheduled departures at a stop", "transit_get_stop_departures"),
    ("bus route frequency headway by hour", "transit_get_route_summary"),
    ("Edmonton crime occurrences", "eps_list_occurrences"),
    ("Edmonton drinking water quality", "epcor_get_daily_water_quality"),
    ("Ontario electricity demand by hour", "electricity_ontario_get_hourly_demand"),
    ("Hydro-Quebec electricity demand right now", "electricity_quebec_get_demand"),
    ("Quebec electricity exports to New York", "electricity_quebec_get_trade"),
    ("Ontario generation mix nuclear wind gas", "electricity_ontario_get_supply_by_fuel"),
    ("wildfire burned area by year", "nrcan_nbac_query_fires"),
    ("patented medicine prices", "pmprb_search_patented_medicines"),
    ("Parliamentary Budget Officer cost estimate", "pbo_search_publications"),
    (
        "federal election candidate financial returns",
        "elections_financial_returns_search_candidates",
    ),
    ("compare bank account fees FCAC", "fcac_search_bank_accounts"),
    ("grain deliveries by province", "cgc_weekly_query"),
    ("milk class prices dairy", "cdc_get_component_prices"),
    ("animal disease cases CFIA", "cfia_disease_detections"),
    ("chronic disease prevalence public health", "phac_infobase_list_datasets"),
    ("federal departmental spending InfoBase", "gc_infobase_query"),
    ("energy use by sector NRCan", "nrcan_energy_use_list_tables"),
    ("pipeline throughput Canada Energy Regulator", "cer_list_datasets"),
    ("oil well licences issued Alberta today", "aer_get_well_licences_daily"),
    ("StatCan releases today The Daily", "statcan_daily_get_releases"),
    ("which StatCan tables changed today", "wds_get_changed_cube_list"),
    ("Quebec statistics institute tables", "isq_search_tables"),
    ("Newfoundland open data datasets", "nl_opendata_search_datasets"),
    ("BC geographic warehouse layers", "bcgw_query_layer"),
    ("research datasets Borealis Dataverse", "borealis_search_ivt"),
    ("geographic names lookup NRCan", "nrcan_geo_search_names"),
    ("NAICS industry classification code", "rdaas_search_classifications"),
    ("how much does a two-bedroom apartment cost in Montreal", "cmhc_get_table_data"),
    ("are people moving to Alberta, interprovincial migration", "wds_search_cubes"),
    ("mortgage rates five-year fixed", "boc_search_series"),
    ("how many immigrants became permanent residents last year", "ircc_monthly_list_tables"),
    ("study permit holders by country", "ircc_monthly_list_tables"),
    ("is it going to snow tomorrow in Winnipeg forecast", "eccc_query_items"),
    ("air quality health index Toronto", "eccc_query_items"),
    ("historical daily temperature climate station", "eccc_query_items"),
    ("which companies won federal contracts", "canadabuys_search_awards"),
    ("is this company incorporated federally", "ised_corporations_get_corporation"),
    ("spectrum licences held by Rogers", "ised_spectrum_query_licences"),
    ("patent search by keyword", "ised_ip_horizons_search_patents"),
    ("how did my MP vote on a bill", "parliament_get_vote"),
    ("median household income by census tract", "statcan_census_profile_search_characteristic"),
    ("population density by province", "statcan_census_profile_search_geography"),
    ("what surveys does Statistics Canada run", "statcan_surveys_search_surveys"),
    ("sustainable development goals indicator Canada", "statcan_sdg_search_indicators"),
    ("StatCan boundary files census divisions map", "statcan_geo_list_services"),
    ("active wildfires in British Columbia right now", "bcgw_get_active_wildfires"),
    ("mining claims BC", "bcgw_get_mining_tenure"),
    ("credit card interest rate comparison", "fcac_search_credit_cards"),
    ("butter price support", "cdc_get_butter_support_prices"),
    ("avian influenza outbreaks in poultry", "cfia_avian_influenza"),
    ("wheat exports by destination", "cgc_exports_query"),
    ("opioid overdose deaths", "phac_infobase_list_datasets"),
    ("federal budget spending by department", "gc_infobase_query"),
    ("charities registered with CRA", "ckan_search_datasets"),
    ("digital platform operators registry", "cra_digital_economy_registry_search"),
    ("bus service disruptions Edmonton", "ets_get_service_alerts"),
    ("where is my bus Edmonton live location", "ets_get_vehicle_positions"),
    ("property assessment Edmonton open data", "socrata_search_datasets"),
    ("natural gas production Alberta monthly", "aer_get_production_volumes_link"),
    ("crude oil exports pipeline", "cer_list_datasets"),
    ("list municipal open data portals", "arcgis_hub_list_portals"),
    ("hospital beds staffed by province", "cihi_search_indicators"),
    ("drug price review board annual report", "pmprb_list_report_tables"),
    ("download full StatCan table as CSV", "wds_get_full_table_download"),
    ("Quebec population estimates ISQ", "isq_search_tables"),
    ("research data repository Canadian universities", "borealis_search_ivt"),
    ("place name gazetteer coordinates", "nrcan_geo_search_names"),
    ("ocean water temperature buoy", "dfo_iwls_get_water_levels"),
    # Gaps found and fixed 2026-09-28: BoC mortgage rates, WDS
    # interprovincial migration and Borealis as a research repository
    # were each missing from the top 3 before their keywords were added.
]


@pytest.mark.parametrize(("query", "expected"), CASES)
async def test_english_query_finds_tool(query: str, expected: str):
    async with Client(mcp) as client:
        result = await client.call_tool("search_tools", {"query": query})
    text = " ".join(getattr(block, "text", "") for block in result.content)
    names = re.findall(r'"name":\s*"([a-z0-9_]+)"', text)[:TOP_N]
    assert expected in names, f"{query!r} -> {names}"
