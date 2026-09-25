"""Constants for the 2021 Census Profile SDMX API.

Confirmed live 2026-09-20 against
`https://api.statcan.gc.ca/census-recensement/profile/sdmx/rest/` — a
different host and a genuinely different SDMX implementation than
`modules/statcan/sdmx` (www150.statcan.gc.ca, XML-only, generic
table/vector data). This one is documented at
https://www12.statcan.gc.ca/wds-sdw/2021profile-profil2021-eng.cfm and
actually honours `format=jsondata`, returning self-describing SDMX-JSON
(dimension labels embedded alongside the data, so a caller does not
need a separate metadata call to read a response). No API key or
session is required.

Geography is split across 14 dataflows, one per geography level, each
with its own geography codelist sharing the DATAFLOW_ID's suffix
(`DF_CD` <-> `CL_GEO_CD`, etc.) — confirmed live for every level below.
`CL_CHARACTERISTIC` (2,631 codes), `CL_GENDER` (3 codes), and
`CL_STATISTIC` (2 codes) are shared across all geography levels.
"""

BASE_URL = "https://api.statcan.gc.ca/census-recensement/profile/sdmx/rest"
AGENCY = "STC_CP"

RATE_LIMIT_SOURCE = "statcan-census-profile"
RATE_LIMIT_PER_SECOND = 5.0
RATE_LIMIT_CAPACITY = 10.0

CACHE_TTL_CODELIST_SECONDS = 24 * 60 * 60
CACHE_TTL_DATA_SECONDS = 60 * 60

GEOGRAPHY_SEARCH_LIMIT_DEFAULT = 20
GEOGRAPHY_SEARCH_LIMIT_MAX = 200
CHARACTERISTIC_SEARCH_LIMIT_DEFAULT = 20
CHARACTERISTIC_SEARCH_LIMIT_MAX = 200

CHARACTERISTIC_CODELIST = "CL_CHARACTERISTIC"

# level -> (dataflow id, geography codelist id)
GEOGRAPHY_LEVEL_TO_DATAFLOW = {
    "canada_provinces_territories": ("DF_PR", "CL_GEO_PR"),
    "census_divisions": ("DF_CD", "CL_GEO_CD"),
    "census_subdivisions": ("DF_CSD", "CL_GEO_CSD"),
    "dissolved_census_subdivisions": ("DF_DCSD", "CL_GEO_DCSD"),
    "census_metro_areas": ("DF_CMACA", "CL_GEO_CMACA"),
    "census_tracts": ("DF_CT", "CL_GEO_CT"),
    "dissemination_areas": ("DF_DA", "CL_GEO_DA"),
    "aggregate_dissemination_areas": ("DF_ADA", "CL_GEO_ADA"),
    "designated_places": ("DF_DPL", "CL_GEO_DPL"),
    "economic_regions": ("DF_ER", "CL_GEO_ER"),
    "federal_electoral_districts": ("DF_FED", "CL_GEO_FED"),
    "forward_sortation_areas": ("DF_FSA", "CL_GEO_FSA"),
    "health_regions": ("DF_HR", "CL_GEO_HR"),
    "population_centres": ("DF_POPCNTR", "CL_GEO_POPCNTR"),
}

# Confirmed live via CL_GENDER/CL_STATISTIC codelists.
GENDER_TO_CODE = {"total": "1", "men": "2", "women": "3"}
STATISTIC_TO_CODE = {"counts": "1", "rate": "4"}
