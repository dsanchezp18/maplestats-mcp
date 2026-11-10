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
    # Since 2026-10-27 wds_get_data_from_vectors computes year-over-year CPI
    # inflation itself (transform="yoy_pct_change"), so it is the StatCan answer.
    ("latest CPI inflation Canada", "wds_get_data_from_vectors"),
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
    ("look up a drug by its DIN", "hc_drug_get_product"),
    ("which drugs contain metformin marketed in Canada", "hc_drug_search_products"),
    ("natural health product NPN melatonin", "hc_nhp_search_products"),
    ("is this insulin pump a licensed medical device in Canada", "hc_device_search_licences"),
    ("adverse reaction reports for myocarditis", "hc_vigilance_search_reactions"),
    ("vehicle recall Honda Civic 2018", "tc_recalls_search"),
    ("search federal open data datasets", "ckan_search_datasets"),
    ("Calgary open data building permits", "socrata_search_datasets"),
    # City permit records sit on the portal families; checked 2026-10-27.
    ("building permits issued Winnipeg", "socrata_search_datasets"),
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
    ("check my answer's figures before replying", "check_answer"),
    ("verify the numbers in my answer against the source", "check_answer"),
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
    ("Annex neighbourhood profile renters Toronto", "toronto_get_neighbourhood_profile"),
    ("RentSafeTO apartment building scores by ward", "toronto_summarize_apartment_scores"),
    ("lowest scoring RentSafeTO apartment buildings", "toronto_get_apartment_evaluations"),
    (
        "Toronto Airbnb short-term rental registrations by ward",
        "toronto_summarize_short_term_rentals",
    ),
    ("DineSafe restaurant inspection closed Toronto", "toronto_search_dinesafe"),
    ("Edmonton drinking water quality", "epcor_get_daily_water_quality"),
    ("MLS home price index CREA download", "crea_get_hpi_links"),
    ("Ontario electricity demand by hour", "electricity_ontario_get_hourly_demand"),
    ("lobster landings value Nova Scotia", "dfo_landings_get_landings"),
    ("commercial fish catch by species in Canada", "dfo_landings_get_landings"),
    ("Hydro-Quebec electricity demand right now", "electricity_quebec_get_demand"),
    ("Quebec electricity exports to New York", "electricity_quebec_get_trade"),
    ("Ontario generation mix nuclear wind gas", "electricity_ontario_get_supply_by_fuel"),
    ("Alberta pool price yesterday by hour", "electricity_alberta_get_pool_price"),
    ("how much wind is Alberta generating now", "electricity_alberta_get_supply_demand"),
    ("Alberta monthly average electricity price", "electricity_alberta_get_monthly_summary"),
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
    ("federal government contracts awarded to a vendor", "disclosure_search_contracts"),
    ("minister travel expenses", "disclosure_search_travel"),
    ("grants and contributions by federal riding", "disclosure_search_grants"),
    ("top departments by total contract value", "disclosure_summarize"),
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
    ("charities registered with CRA", "cra_charities_search"),
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
    ("reconcile a workbook of vector IDs against a published table", "wds_get_full_table_download"),
    ("get hundreds of StatCan series at once", "wds_get_full_table_download"),
    ("Quebec population estimates ISQ", "isq_search_tables"),
    ("research data repository Canadian universities", "borealis_search_ivt"),
    ("place name gazetteer coordinates", "nrcan_geo_search_names"),
    # Matched on "water" alone; get_water_levels tied with eccc_coverages_get_data and
    # fell to fourth when isc_ added two water-advisory tools (2026-10-26).
    ("ocean water temperature buoy", "dfo_iwls_search_stations"),
    # Gaps found and fixed 2026-09-28: BoC mortgage rates, WDS
    # interprovincial migration and Borealis as a research repository
    # were each missing from the top 3 before their keywords were added.
    # StatCan misses found in the 2026-10-02 review (no StatCan tool in the top
    # 5, or the wrong one first).
    ("population estimates by province quarterly", "wds_search_cubes"),
    ("monthly unemployment rate for Alberta", "wds_search_cubes"),
    # Found in the 2026-10-14 review: CPI and population queries had no StatCan
    # table tool in the top 3, and the AQHI tool outranked BC's wildfire layer.
    ("consumer price index monthly", "wds_search_cubes"),
    ("population estimates by province", "wds_search_cubes"),
    ("wildfires British Columbia", "bcgw_get_active_wildfires"),
    ("time series for a vector between two dates", "wds_get_data_by_reference_period_range"),
    ("GDP as originally published before revisions", "wds_get_series_as_of"),
    ("NOC occupation classification", "rdaas_search_classifications"),
    # StatCan's extra SDMX spaces (CCEI energy information, shared), 2026-10-02.
    ("greenhouse gas emissions by province and IPCC category", "sdmx_space_get_data"),
    ("find a dataflow in the energy information space", "sdmx_space_list_flows"),
    ("air pollutants black carbon emissions inventory", "sdmx_space_search"),
    ("browse dimensions and codes of an SDMX dataflow in CCEI", "sdmx_space_get_structure"),
    ("how does Canada compare with G7 countries on GDP per capita", "worldbank_get_canada_series"),
    ("World Bank development indicator code search", "worldbank_search_indicators"),
    # CBSA Customs Tariff, 2026-10-26.
    ("Canada import duty rate MFN for a tariff item", "cbsa_tariff_lookup"),
    ("find the customs tariff HS code of a product by name", "cbsa_tariff_search"),
    ("customs tariff editions and effective dates", "cbsa_tariff_list_editions"),
    # Indigenous Services Canada and CIRNAC, 2026-10-26.
    ("long-term drinking water advisories First Nations", "isc_list_drinking_water_advisories"),
    ("First Nation band number lookup", "isc_search_first_nations"),
    ("chief and council tribal council reserves of a First Nation", "isc_get_first_nation_profile"),
    (
        "registered population on reserve and off reserve Indian Register",
        "isc_get_registered_population",
    ),
    ("short-term boil water advisory First Nations south of 60", "isc_list_short_term_advisories"),
    # BIS statistics, 2026-10-26.
    ("household debt service ratio Canada compared with other countries", "bis_compare_countries"),
    ("Bank for International Settlements datasets", "bis_list_datasets"),
    ("dimensions and codes of a BIS dataset series key", "bis_describe_dataset"),
    # OECD Data Explorer, 2026-11-07.
    ("OECD economic outlook GDP growth projections Canada vs G7", "oecd_compare_countries"),
    ("search OECD Data Explorer datasets", "oecd_search_datasets"),
    ("dimensions and codes of an OECD dataset series key", "oecd_describe_dataset"),
    # Eurostat, 2026-11-07.
    ("euro area HICP inflation compared with Germany and France", "eurostat_compare"),
    ("find a Eurostat dataset code for EU statistics", "eurostat_search_datasets"),
    ("Eurostat dataset dimensions codes and status flags", "eurostat_describe_dataset"),
    # ILOSTAT, 2026-11-08.
    ("ILO unemployment rate Canada compared with G7 countries", "ilo_compare_countries"),
    ("search ILOSTAT labour statistics datasets", "ilo_search_datasets"),
    ("dimensions and codes of an ILOSTAT dataset series key", "ilo_describe_dataset"),
    # Australian Bureau of Statistics, 2026-11-08.
    ("Australian trimmed mean inflation ABS", "abs_get_indicator"),
    ("search Australian Bureau of Statistics datasets", "abs_search_datasets"),
    # UK Office for National Statistics, 2026-11-08.
    ("UK CPIH inflation Office for National Statistics", "ons_get_indicator"),
    ("find the ONS series id CDID for a UK statistic", "ons_search_series"),
    # US Federal Reserve Board releases, 2026-11-07.
    ("US federal funds rate compared with the Bank of Canada", "fed_get_indicator"),
    ("US 10-year Treasury yield", "fed_get_indicator"),
    ("Federal Reserve H.15 H.10 G.17 statistical releases", "fed_list_releases"),
    ("find a Federal Reserve series id", "fed_search_series"),
    # European Central Bank Data Portal, 2026-11-07.
    ("ECB deposit facility rate compared with the Bank of Canada", "ecb_get_indicator"),
    ("euro to Canadian dollar ECB reference exchange rate", "ecb_get_indicator"),
    ("list of European Central Bank datasets", "ecb_list_datasets"),
    ("find the series key of an ECB series", "ecb_search_series"),
    # Ontario Energy Board open data, 2026-10-03.
    ("SAIDI SAIFI power outages Ontario utility", "oeb_query_dataset"),
    ("Ontario time-of-use electricity prices history", "oeb_rates"),
    ("Ontario Energy Board open data datasets", "oeb_list_datasets"),
    ("which fields does an OEB RRR file have", "oeb_describe_dataset"),
    # Ontario Financial Information Return, 2026-10-26.
    ("police spending per capita Ontario municipalities", "on_fir_compare"),
    ("Toronto municipal expenses by function Financial Information Return", "on_fir_get_schedule"),
    ("Ontario municipality MUNID upper tier lower tier", "on_fir_search_municipalities"),
    ("FIR schedule line column code for reserve funds", "on_fir_search_lines"),
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
    # CRTC Communications Market Reports (telecom_prices), 2026-10-27: before the
    # module, these went to the Ontario electricity rates and butter price tools.
    ("how have mobile plan prices changed since 2020", "telecom_get_plan_prices"),
    ("cell phone plan prices Canada", "telecom_get_plan_prices"),
    ("home Internet plan prices by speed rural", "telecom_get_plan_prices"),
    ("average revenue per GB of mobile data", "telecom_get_market_table"),
    ("mobile market share Bell Rogers TELUS", "telecom_get_market_table"),
    ("list CRTC communications market report tables", "telecom_list_market_tables"),
    ("quarterly mobile subscribers and wireless data traffic", "telecom_get_quarterly_trends"),
    # A department's total spending or headcount is GC InfoBase's; proactive disclosure
    # (contracts, travel) ranked first for these before 2026-11-03.
    ("federal government spending by department", "gc_infobase_query"),
    ("public servants employees count by department", "gc_infobase_query"),
    ("How much did ESDC spend in 2023-24 and how many employees", "gc_infobase_query"),
    # StatCan tables for a CMA or a monthly series, not BC Stats or the Ontario
    # electricity price history (2026-11-03).
    ("unemployment rate Toronto CMA", "wds_search_cubes"),
    ("GDP by industry monthly", "wds_search_cubes"),
    ("average hourly wage of registered nurses in Ontario", "jobbank_get_wages"),
    # Economic-statistician exam gaps, 2026-11-09: none of these reached its tool.
    # Definitions sit in survey guides; the IMDB tool's docstring names them and
    # sends the agent to statcan_reference_search_documents.
    ("CPI-trim core inflation Bank of Canada", "boc_search_series"),
    ("CPI-common", "boc_search_series"),
    ("Bank of Canada Banking and Financial Statistics tables", "boc_search_groups"),
    ("Labour Force Survey definitions and concepts", "statcan_surveys_get_survey_metadata"),
    ("involuntary part-time definition", "statcan_surveys_get_survey_metadata"),
    ("hedonic adjustment in price indexes", "statcan_surveys_get_survey_metadata"),
    ("IPPI industrial product price index survey id", "statcan_surveys_search_surveys"),
    ("Raw materials price index survey", "statcan_surveys_search_surveys"),
    ("Employment Insurance Coverage Survey", "statcan_surveys_search_surveys"),
    # The guides' text itself (2026-11-10): the search tools above return titles and
    # descriptions only, so these must reach the tools that read the publication.
    ("definition of involuntary part-time", "statcan_reference_get_section_text"),
    ("involuntary part-time definition", "statcan_reference_get_section_text"),
    ("LFS guide", "statcan_reference_get_publication"),
    ("CPI reference paper", "statcan_reference_get_publication"),
    ("hedonic adjustment", "statcan_reference_get_section_text"),
    ("hedonic adjustment in price indexes", "statcan_reference_get_section_text"),
    ("gross output allocation method", "statcan_reference_get_section_text"),
    ("how does the CPI treat owned accommodation", "statcan_reference_get_section_text"),
    ("read the Guide to the Labour Force Survey", "statcan_reference_get_publication"),
]

# Queries whose right tool must come first, not just within TOP_N.
FIRST = [
    ("federal government spending by department", "gc_infobase_query"),
    ("public servants employees count by department", "gc_infobase_query"),
    ("unemployment rate Toronto CMA", "wds_search_cubes"),
    ("GDP by industry monthly", "wds_search_cubes"),
    ("average hourly wage of registered nurses in Ontario", "jobbank_get_wages"),
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


@pytest.mark.parametrize(("query", "expected"), FIRST)
def test_english_query_ranks_tool_first(query: str, expected: str, top_names: dict[str, list[str]]):
    assert top_names[query][:1] == [expected], f"{query!r} -> {top_names[query]}"
