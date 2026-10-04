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
    "ontario": ("Ontario", (_ckan("on"), _arcgis("ontario_geohub"))),
    "british columbia": (
        "British Columbia",
        (
            _ckan("bc"),
            PlanStep("bc_stats_list_files", "BC Stats Excel tables (labour, GDP, population)"),
            PlanStep("bcgw_query_layer", "BC Geographic Warehouse layers: type_name"),
            _arcgis("bc_energy_regulator"),
        ),
    ),
    "alberta": (
        "Alberta",
        (
            PlanStep("ab_opendata_search_datasets", "Open Alberta Excel and CSV files"),
            _ckan("ab"),
            PlanStep("ab_economic_list_indicators", "Alberta Economic Dashboard"),
            PlanStep("aer_get_well_licences_daily", "Alberta Energy Regulator reports"),
        ),
    ),
    "quebec": (
        "Quebec",
        (
            _ckan("qc"),
            PlanStep(
                "isq_search_tables", "Institut de la statistique du Quebec tables: query=<topic>"
            ),
        ),
    ),
    "manitoba": ("Manitoba", (_arcgis("mb"),)),
    # No provincial catalogue is covered; the two largest cities publish their own.
    "saskatchewan": (
        "Saskatchewan",
        (
            PlanStep(
                "arcgis_hub_search_datasets",
                "search with portal='saskatoon' (city data; no provincial portal is covered)",
            ),
            PlanStep(
                "ckan_search_datasets",
                "search with portal='regina' (city data; no provincial portal is covered)",
            ),
        ),
    ),
    "prince edward island": ("Prince Edward Island", (_arcgis("pe"),)),
    "nova scotia": ("Nova Scotia", (_socrata("ns"),)),
    "new brunswick": ("New Brunswick", (_socrata("nb"),)),
    "newfoundland": (
        "Newfoundland and Labrador",
        (
            PlanStep("nl_stats_list_files", "NL Statistics Agency Excel tables by topic"),
            PlanStep("nl_opendata_search_datasets", "provincial open-data catalogue"),
        ),
    ),
    "northwest territories": (
        "Northwest Territories",
        (
            PlanStep(
                "nwt_stats_search_files", "NWT Bureau of Statistics Excel tables (query by words)"
            ),
            _ckan("nt"),
            _arcgis("ntgs"),
            _arcgis("ntgs_datahub"),
        ),
    ),
    "yukon": (
        "Yukon",
        (
            PlanStep("yukon_stats_list_tables", "Yukon Bureau of Statistics tables"),
            _ckan("yt"),
        ),
    ),
    # No Nunavut portal is covered; the federal catalogue and StatCan tables
    # carry its figures.
    "nunavut": (
        "Nunavut",
        (
            _ckan("federal", ", q='Nunavut' (no Nunavut portal is covered)"),
            PlanStep("wds_search_cubes", "StatCan tables with Nunavut as a geography"),
        ),
    ),
}

PROVINCE_ALIASES: dict[str, str] = {
    "colombie-britannique": "british columbia",
    "ile-du-prince-edouard": "prince edward island",
    "nouvelle-ecosse": "nova scotia",
    "nouveau-brunswick": "new brunswick",
    "terre-neuve": "newfoundland",
    "territoires du nord-ouest": "northwest territories",
    "labrador": "newfoundland",
    "bc": "british columbia",
    "b c": "british columbia",  # "B.C." after normalization
    "pei": "prince edward island",
    "p e i": "prince edward island",
    "ipe": "prince edward island",
    "nwt": "northwest territories",
    "tno": "northwest territories",
}

# Two-letter codes that are also ordinary words ("nu" in French, "on"):
# they count only when typed in capitals, as in "QC" or "NL".
PROVINCE_CODES: dict[str, str] = {
    "AB": "alberta",
    "BC": "british columbia",
    "SK": "saskatchewan",
    "MB": "manitoba",
    "QC": "quebec",
    "NS": "nova scotia",
    "NB": "new brunswick",
    "NL": "newfoundland",
    "PE": "prince edward island",
    "YT": "yukon",
    "NT": "northwest territories",
    "NU": "nunavut",
}

# Phrases in which a city name means something else: StatCan's Delta File
# is not Delta, British Columbia.
CITY_SHADOWS: dict[str, tuple[str, ...]] = {
    "delta": ("delta file", "delta files", "fichier delta", "fichiers delta", "statcan delta"),
}

CITIES: dict[str, tuple[str, tuple[PlanStep, ...]]] = {
    "toronto": ("Toronto", (_ckan("toronto"), _arcgis("toronto_police"))),
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
    "ottawa": ("Ottawa", (_arcgis("ottawa"), _arcgis("ottawa_police"))),
    "halifax": ("Halifax", (_arcgis("halifax"),)),
    "london": ("London (Ontario)", (_arcgis("london"),)),
    "kitchener": ("Kitchener", (_arcgis("kitchener"), _arcgis("waterloo_region"))),
    "waterloo": ("Region of Waterloo", (_arcgis("waterloo_region"),)),
    "windsor": ("Windsor", (_arcgis("windsor"),)),
    "saskatoon": ("Saskatoon", (_arcgis("saskatoon"),)),
    "victoria": ("Victoria", (_arcgis("victoria"),)),
    "surrey": ("Surrey", (_arcgis("surrey"),)),
    "mississauga": ("Mississauga", (_arcgis("mississauga"), _arcgis("peel"))),
    "brampton": ("Brampton", (_arcgis("brampton"), _arcgis("peel"))),
    "markham": ("Markham", (_arcgis("markham"), _arcgis("york"))),
    "lethbridge": ("Lethbridge", (_arcgis("lethbridge"),)),
    "red deer": ("Red Deer", (_arcgis("red_deer"),)),
    "medicine hat": ("Medicine Hat", (_arcgis("medicine_hat"),)),
    "oakville": ("Oakville", (_arcgis("oakville"),)),
    "burlington": ("Burlington (Ontario)", (_arcgis("burlington"),)),
    "milton": ("Milton (Ontario)", (_arcgis("milton"),)),
    "halton": ("Halton Region", (_arcgis("oakville"), _arcgis("burlington"), _arcgis("milton"))),
    "cochrane": ("Cochrane (Alberta)", (_arcgis("cochrane"),)),
    "okotoks": ("Okotoks", (_arcgis("okotoks"),)),
    "kingston": ("Kingston", (_arcgis("kingston"),)),
    "kelowna": ("Kelowna", (_arcgis("kelowna"),)),
    "barrie": ("Barrie", (_arcgis("barrie"),)),
    "burnaby": ("Burnaby", (_arcgis("burnaby"),)),
    "fredericton": ("Fredericton", (_arcgis("fredericton"),)),
    "sudbury": ("Greater Sudbury", (_arcgis("greater_sudbury"),)),
    "greater sudbury": ("Greater Sudbury", (_arcgis("greater_sudbury"),)),
    "guelph": ("Guelph", (_arcgis("guelph"),)),
    "moncton": ("Moncton", (_arcgis("moncton"),)),
    "abbotsford": ("Abbotsford", (_arcgis("abbotsford"),)),
    "whitby": ("Whitby", (_arcgis("whitby"),)),
    "oshawa": ("Oshawa", (_arcgis("oshawa"),)),
    "niagara falls": ("Niagara Falls", (_arcgis("niagara_falls"), _arcgis("niagara_region"))),
    "niagara": (
        "Niagara Region",
        (_arcgis("niagara_region"), _arcgis("niagara_falls"), _arcgis("st_catharines")),
    ),
    # Keys are matched after normalization, which turns "St." into "st".
    "st catharines": ("St. Catharines", (_arcgis("st_catharines"),)),
    "saint catharines": ("St. Catharines", (_arcgis("st_catharines"),)),
    "thunder bay": ("Thunder Bay", (_arcgis("thunder_bay"),)),
    "peterborough": ("Peterborough", (_arcgis("peterborough"),)),
    "coquitlam": ("Coquitlam", (_arcgis("coquitlam"),)),
    "saanich": ("Saanich", (_arcgis("saanich"),)),
    "kamloops": ("Kamloops", (_arcgis("kamloops"),)),
    "prince george": ("Prince George", (_arcgis("prince_george"),)),
    "delta": ("Delta (BC)", (_arcgis("delta"),)),
    "yellowknife": ("Yellowknife", (_arcgis("yellowknife"),)),
    "cambridge": ("Cambridge (Ontario)", (_arcgis("cambridge"),)),
    "maple ridge": ("Maple Ridge", (_arcgis("maple_ridge"),)),
    "pickering": ("Pickering", (_arcgis("pickering"),)),
    "sarnia": ("Sarnia", (_arcgis("sarnia"),)),
    "saint john": ("Saint John (New Brunswick)", (_arcgis("saint_john"),)),
    "port moody": ("Port Moody", (_arcgis("port_moody"),)),
    "white rock": ("White Rock", (_arcgis("white_rock"),)),
    "penticton": ("Penticton", (_arcgis("penticton"),)),
    "orangeville": ("Orangeville", (_arcgis("orangeville"),)),
    "canmore": ("Canmore", (_arcgis("canmore"),)),
}
