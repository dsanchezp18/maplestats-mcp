"""Realistic English questions must find the right tool through search_tools.

Clients see only search_tools, call_tool and plan_query, so a tool whose
docstring lacks the words people actually type is effectively invisible.
These are phrased the way a user asks, not the way a tool is named;
the French counterpart is test_french_discovery.py. Several expectations
accept a reasonable neighbour (e.g. CPI from the Bank of Canada rather
than StatCan) because either answers the question.
"""

from __future__ import annotations

import asyncio
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
    ("federal corporation lookup by name", "ised_corporations_get_corporation"),
    ("trademark search", "ised_cipo_search_trademarks"),
    ("Senate votes", "senate_list_votes"),
    ("Canada Gazette proposed regulations", "gazette_get_issue"),
    ("hospital wait times indicator", "cihi_search_indicators"),
    ("Census 2021 population of a city", "statcan_census_profile_get_data"),
    ("public use microdata Labour Force Survey", "statcan_pumf_search"),
    ("cross-tabulate PUMF microdata", "statcan_pumf_tabulate"),
    ("generate R code to reproduce this query", "reproduce_code"),
    ("Alberta economic dashboard unemployment", "ab_economic_get_data"),
    ("BC Stats Excel workbook list British Columbia", "bc_stats_list_files"),
    ("Open Alberta Excel CSV dataset files AISH caseload", "ab_opendata_search_datasets"),
    ("read rows of an Open Alberta xlsx file", "ab_opendata_read_resource"),
    ("NPRI pollutant releases by facility mercury Ontario", "eccc_datamart_npri_facilities"),
    ("largest greenhouse gas emitters facility GHGRP Alberta", "eccc_datamart_ghgrp_facilities"),
    ("browse ECCC data catalogue folder files", "eccc_datamart_browse"),
    ("read the Excel file of an open.canada.ca resource with no DataStore", "ckan_read_resource"),
    ("sheets and columns of the xlsx file behind a CKAN resource", "ckan_describe_resource"),
    ("Edmonton bus real-time arrivals", "ets_get_stop_predictions"),
    ("STM scheduled departures at a stop", "transit_get_stop_departures"),
    ("bus route frequency headway by hour", "transit_get_route_summary"),
    ("small town transit agencies Canada national GTFS database", "transit_list_national_agencies"),
    ("Edmonton crime occurrences", "eps_list_occurrences"),
    ("Edmonton drinking water quality", "epcor_get_daily_water_quality"),
    ("MLS home price index CREA download", "crea_get_hpi_links"),
    ("Ontario electricity demand by hour", "electricity_ontario_get_hourly_demand"),
    ("Hydro-Quebec electricity demand right now", "electricity_quebec_get_demand"),
    ("Quebec electricity exports to New York", "electricity_quebec_get_trade"),
    ("Ontario generation mix nuclear wind gas", "electricity_ontario_get_supply_by_fuel"),
    ("wildfire burned area by year", "nrcan_nbac_query_fires"),
    ("Alberta wildfires out of control by cause", "ab_wildfire_get_fires"),
    ("Alberta fire danger rating extreme near Hinton", "ab_wildfire_get_fire_danger"),
    ("is there a fire ban in my Alberta county", "ab_wildfire_get_fire_restrictions"),
    ("patented medicine prices", "pmprb_search_patented_medicines"),
    ("who lobbied the BC minister of health", "bc_lobbyists_search_activity_reports"),
    ("British Columbia lobbyist registration for a company", "bc_lobbyists_search_registrations"),
    ("Parliamentary Budget Officer cost estimate", "pbo_search_publications"),
    (
        "federal election candidate financial returns",
        "elections_financial_returns_search_candidates",
    ),
    ("Quebec provincial election results by riding", "elections_provincial_get_results"),
    ("Alberta general election winner electoral division", "elections_provincial_get_results"),
    ("BC election seats by party popular vote", "elections_provincial_get_seats"),
    ("which provincial elections have results available", "elections_provincial_list_elections"),
    ("compare bank account fees FCAC", "fcac_search_bank_accounts"),
    ("grain deliveries by province", "cgc_weekly_query"),
    ("timber harvest volume by province", "nfd_query_table"),
    ("seedlings planted forestry data comments", "nfd_table_comments"),
    ("milk class prices dairy", "cdc_get_component_prices"),
    ("animal disease cases CFIA", "cfia_disease_detections"),
    ("NWT Bureau of Statistics topics", "nwt_stats_list_files"),
    ("Northwest Territories community price index table", "nwt_stats_search_files"),
    ("read NWT Bureau of Statistics Excel sheet", "nwt_stats_read_file"),
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
    (
        "projected temperature in Edmonton in 2050 under a high emissions scenario",
        "eccc_coverages_get_data",
    ),
    ("which climate projection datasets have SSP5-8.5 scenarios", "eccc_coverages_search"),
    ("is this company incorporated federally", "ised_corporations_get_corporation"),
    ("spectrum licences held by Rogers", "ised_spectrum_query_licences"),
    ("patent search by keyword", "ised_ip_horizons_search_patents"),
    ("which committees does my MP sit on", "ourcommons_get_member_roles"),
    (
        "who ran in the 1997 and 2000 federal elections candidate names",
        "elections_results_get_historical_candidates",
    ),
    ("median household income by census tract", "statcan_census_profile_search_characteristic"),
    ("population density by province", "statcan_census_profile_search_geography"),
    ("what surveys does Statistics Canada run", "statcan_surveys_search_surveys"),
    ("sustainable development goals indicator Canada", "statcan_sdg_search_indicators"),
    ("crude oil exports to the US by HS code", "cimt_get_trade"),
    ("find the HS code for a product", "cimt_search_commodities"),
    ("top export markets for Canadian lumber", "cimt_get_top_partners"),
    ("StatCan boundary files census divisions map", "statcan_geo_list_services"),
    (
        "Canadian index of multiple deprivation dissemination area",
        "statcan_geo_query_spatial_layer",
    ),
    ("national road network road segments by province", "statcan_geo_query_spatial_layer"),
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
    # StatCan misses found in the 2026-10-02 review (no StatCan tool in the top
    # 5, or the wrong one first).
    ("population estimates by province quarterly", "wds_search_cubes"),
    ("monthly unemployment rate for Alberta", "wds_search_cubes"),
    ("time series for a vector between two dates", "wds_get_data_by_reference_period_range"),
    ("NOC occupation classification", "rdaas_search_classifications"),
    # StatCan's extra SDMX spaces (CCEI energy information, shared), 2026-10-02.
    ("greenhouse gas emissions by province and IPCC category", "sdmx_space_get_data"),
    ("find a dataflow in the energy information space", "sdmx_space_list_flows"),
    ("air pollutants black carbon emissions inventory", "sdmx_space_search"),
    ("browse dimensions and codes of an SDMX dataflow in CCEI", "sdmx_space_get_structure"),
    ("how does Canada compare with G7 countries on GDP per capita", "worldbank_get_canada_series"),
    ("World Bank development indicator code search", "worldbank_search_indicators"),
    # Ontario Energy Board open data, 2026-10-03.
    ("SAIDI SAIFI power outages Ontario utility", "oeb_query_dataset"),
    ("Ontario time-of-use electricity prices history", "oeb_rates"),
    ("Ontario Energy Board open data datasets", "oeb_list_datasets"),
    ("which fields does an OEB RRR file have", "oeb_describe_dataset"),
    # Federal sources added 2026-10-03.
    ("border wait time at the Peace Bridge right now", "cbsa_border_wait_times"),
    ("pesticide products registered with active ingredient glyphosate", "pmra_search_products"),
    ("maximum residue limit for pesticide on apples ppm", "pmra_get_residue_limits"),
    ("pesticide registration number details pests and sites of use", "pmra_get_product"),
    ("gold production by province mining statistics", "nrcan_minerals_get_production"),
    ("value of mineral production in Canada since 1990 time series", "nrcan_minerals_get_series"),
    (
        "federal deficit and debt history since 1966 fiscal reference tables",
        "finance_frt_list_tables",
    ),
    ("Alberta provincial net debt and deficit by year", "finance_frt_get_table"),
    ("federal deficit year to date this fiscal year monthly", "finance_fiscal_monitor_get_tables"),
]


@pytest.fixture(scope="module")
def top_names() -> dict[str, list[str]]:
    """search_tools's top names for every query, asked over one client session.

    One session serves every case instead of one session per case.
    """

    async def search_all() -> dict[str, list[str]]:
        found = {}
        async with Client(mcp) as client:
            for query, _ in CASES:
                result = await client.call_tool("search_tools", {"query": query})
                text = " ".join(getattr(block, "text", "") for block in result.content)
                found[query] = re.findall(r'"name":\s*"([a-z0-9_]+)"', text)[:TOP_N]
        return found

    return asyncio.run(search_all())


@pytest.mark.parametrize(("query", "expected"), CASES)
def test_english_query_finds_tool(query: str, expected: str, top_names: dict[str, list[str]]):
    names = top_names[query]
    assert expected in names, f"{query!r} -> {names}"
