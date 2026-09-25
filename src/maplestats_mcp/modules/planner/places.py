"""Place names mapped to the portal-specific tools that cover them.

Keys are accent-free lowercase aliases (English and French). Portal keys
match ckan/arcgis_hub/socrata constants.PORTALS; tests/test_planner.py
checks that each one exists.
"""

from __future__ import annotations

from maplestats_mcp.modules.planner.topics import PlanStep


def _ckan(portal: str, extra: str = "") -> PlanStep:
    return PlanStep("ckan_search_datasets", f"search with portal='{portal}'{extra}")


def _arcgis(portal: str) -> PlanStep:
    return PlanStep("arcgis_hub_search_datasets", f"search with portal='{portal}'")


def _socrata(portal: str) -> PlanStep:
    return PlanStep("socrata_search_datasets", f"search with portal='{portal}'")


def _qc_city(org: str) -> PlanStep:
    return _ckan("qc", f", fq='organization:{org}' (the city publishes on Donnees Quebec)")


PROVINCES: dict[str, tuple[str, tuple[PlanStep, ...]]] = {
    "ontario": ("Ontario", (_ckan("on"),)),
    "british columbia": (
        "British Columbia",
        (_ckan("bc"), PlanStep("bcgw_query_layer", "BC Geographic Warehouse layers")),
    ),
    "alberta": (
        "Alberta",
        (
            _ckan("ab"),
            PlanStep("ab_economic_list_indicators", "Alberta Economic Dashboard"),
            PlanStep("aer_get_well_licences_daily", "Alberta Energy Regulator reports"),
        ),
    ),
    "quebec": ("Quebec", (_ckan("qc"),)),
    "manitoba": ("Manitoba", (_arcgis("mb"),)),
    "saskatchewan": ("Saskatchewan", (_arcgis("sk"),)),
    "prince edward island": ("Prince Edward Island", (_arcgis("pe"),)),
    "nova scotia": ("Nova Scotia", (_socrata("ns"),)),
    "new brunswick": ("New Brunswick", (_socrata("nb"),)),
    "newfoundland": (
        "Newfoundland and Labrador",
        (PlanStep("nl_opendata_search_datasets", "provincial open-data catalogue"),),
    ),
    "northwest territories": ("Northwest Territories", (_ckan("nt"),)),
    "yukon": ("Yukon", (_ckan("yt"),)),
}

PROVINCE_ALIASES: dict[str, str] = {
    "colombie-britannique": "british columbia",
    "ile-du-prince-edouard": "prince edward island",
    "nouvelle-ecosse": "nova scotia",
    "nouveau-brunswick": "new brunswick",
    "terre-neuve": "newfoundland",
    "territoires du nord-ouest": "northwest territories",
    "labrador": "newfoundland",
}

CITIES: dict[str, tuple[str, tuple[PlanStep, ...]]] = {
    "toronto": ("Toronto", (_ckan("toronto"),)),
    "montreal": ("Montreal", (_ckan("montreal"),)),
    "regina": ("Regina", (_ckan("regina"),)),
    "quebec city": ("Quebec City", (_qc_city("ville-de-quebec"),)),
    "ville de quebec": ("Quebec City", (_qc_city("ville-de-quebec"),)),
    "laval": ("Laval", (_qc_city("ville-de-laval"),)),
    "gatineau": ("Gatineau", (_qc_city("ville-de-gatineau"),)),
    "longueuil": ("Longueuil", (_qc_city("ville-de-longueuil"),)),
    "sherbrooke": ("Sherbrooke", (_qc_city("ville-de-sherbrooke"),)),
    "trois-rivieres": ("Trois-Rivieres", (_qc_city("ville-de-trois-rivieres"),)),
    "calgary": ("Calgary", (_socrata("calgary"),)),
    "edmonton": (
        "Edmonton",
        (
            _socrata("edmonton"),
            PlanStep("eps_summarize_occurrences", "Edmonton Police Service occurrences"),
            PlanStep("ets_get_service_alerts", "Edmonton Transit"),
            PlanStep("epcor_get_daily_water_quality", "EPCOR drinking water quality"),
        ),
    ),
    "winnipeg": ("Winnipeg", (_socrata("winnipeg"),)),
    "vancouver": (
        "Vancouver",
        (
            PlanStep("opendatasoft_vancouver_search_datasets", "City of Vancouver open data"),
            _arcgis("metro_vancouver"),
        ),
    ),
    "ottawa": ("Ottawa", (_arcgis("ottawa"),)),
    "halifax": ("Halifax", (_arcgis("halifax"),)),
    "hamilton": ("Hamilton", (_arcgis("hamilton"),)),
    "london": ("London (Ontario)", (_arcgis("london"),)),
    "kitchener": ("Kitchener", (_arcgis("kitchener"), _arcgis("waterloo_region"))),
    "waterloo": ("Region of Waterloo", (_arcgis("waterloo_region"),)),
    "windsor": ("Windsor", (_arcgis("windsor"),)),
    "saskatoon": ("Saskatoon", (_arcgis("saskatoon"),)),
    "victoria": ("Victoria", (_arcgis("victoria"),)),
    "surrey": ("Surrey", (_arcgis("surrey"),)),
    "mississauga": ("Mississauga", (_arcgis("mississauga"), _arcgis("peel"))),
    "brampton": ("Brampton", (_arcgis("peel"),)),
    "markham": ("Markham", (_arcgis("markham"), _arcgis("york"))),
    "lethbridge": ("Lethbridge", (_arcgis("lethbridge"),)),
    "red deer": ("Red Deer", (_arcgis("red_deer"),)),
    "medicine hat": ("Medicine Hat", (_arcgis("medicine_hat"),)),
}
