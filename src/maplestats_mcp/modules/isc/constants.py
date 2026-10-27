"""Constants for the ISC / CIRNAC module (checked live 2026-10-26)."""

FNP_HOST = "fnp-ppn.aadnc-aandc.gc.ca"
FNP_SEARCH = f"https://{FNP_HOST}/fnp/Main/Search/"
# One page per tab of a profile; each takes BAND_NUMBER and lang=eng|fra.
FNP_PAGES = {
    "main": "FNMain.aspx",
    "reserves": "FNReserves.aspx",
    "governance": "FNGovernance.aspx",
    "geography": "FNGeography.aspx",
    "population": "FNRegPopulation.aspx",
}

SAC_HOST = "www.sac-isc.gc.ca"
# The long-term advisory page carries the map's App_config, whose
# LinkAjaxSource names the JSON file (its name has a timestamp).
LTDWA_PAGE = "https://www.sac-isc.gc.ca/{lang}/1506514143353/1533317130660"
STDWA_PAGE = "https://www.sac-isc.gc.ca/{lang}/1562856509704/1562856530304"

OPEN_HOST = "open.canada.ca"
# open.canada.ca answers a download with 302 to a signed blob URL.
BLOB_HOST = "opencanada.blob.core.windows.net"
REGPOP_DATASET = "b1b8433a-47c8-4427-94d9-0b051b17d108"
REGPOP_PACKAGE = f"https://open.canada.ca/data/api/3/action/package_show?id={REGPOP_DATASET}"
REGPOP_PAGE = f"https://open.canada.ca/data/en/dataset/{REGPOP_DATASET}"

RATE_LIMIT_SOURCE = "isc"
RATE_LIMIT_PER_SECOND = 2.0
RATE_LIMIT_CAPACITY = 4.0

PROFILE_TTL_SECONDS = 6 * 60 * 60
# The map file's GenerateDate moved weekly; the short-term page daily.
ADVISORY_TTL_SECONDS = 60 * 60
REGPOP_TTL_SECONDS = 24 * 60 * 60

# Profile pages were 22-26 KB, the map file 2.7 MB (English) and 3.1 MB
# (French), the population CSV 200 KB.
MAX_PAGE_BYTES = 2 * 1024 * 1024
MAX_MAP_BYTES = 16 * 1024 * 1024

SEARCH_DEFAULT_LIMIT = 50
SEARCH_MAX_LIMIT = 700
ADVISORY_DEFAULT_LIMIT = 200
ADVISORY_MAX_LIMIT = 1000

# Province and territory codes with their English and French names.
PROVINCES: dict[str, tuple[str, str]] = {
    "NL": ("Newfoundland and Labrador", "Terre-Neuve-et-Labrador"),
    "PE": ("Prince Edward Island", "Île-du-Prince-Édouard"),
    "NS": ("Nova Scotia", "Nouvelle-Écosse"),
    "NB": ("New Brunswick", "Nouveau-Brunswick"),
    "QC": ("Quebec", "Québec"),
    "ON": ("Ontario", "Ontario"),
    "MB": ("Manitoba", "Manitoba"),
    "SK": ("Saskatchewan", "Saskatchewan"),
    "AB": ("Alberta", "Alberta"),
    "BC": ("British Columbia", "Colombie-Britannique"),
    "YT": ("Yukon", "Yukon"),
    "NT": ("Northwest Territories", "Territoires du Nord-Ouest"),
    "NU": ("Nunavut", "Nunavut"),
}

# The short-term page has one table per ISC region; the Atlantic one holds
# the four Atlantic provinces. British Columbia and the territories have none.
STDWA_REGIONS: dict[str, str] = {
    "NL": "ATLANTIC",
    "PE": "ATLANTIC",
    "NS": "ATLANTIC",
    "NB": "ATLANTIC",
    "QC": "QUEBEC",
    "ON": "ONTARIO",
    "MB": "MANITOBA",
    "SK": "SASKATCHEWAN",
    "AB": "ALBERTA",
}
STDWA_REGION_NAMES: dict[str, str] = {
    "atlantic": "ATLANTIC",
    "atlantique": "ATLANTIC",
    "quebec": "QUEBEC",
    "ontario": "ONTARIO",
    "manitoba": "MANITOBA",
    "saskatchewan": "SASKATCHEWAN",
    "alberta": "ALBERTA",
}

# The page's legend (BWA, DNC, DNU in English; AEE, ANPB, ANU in French).
# The English Ontario table also used "DWA", which the legend does not define.
ADVISORY_CODES: dict[str, str] = {
    "BWA": "boil_water",
    "AEE": "boil_water",
    "DNC": "do_not_consume",
    "ANPB": "do_not_consume",
    "DNU": "do_not_use",
    "ANU": "do_not_use",
}
