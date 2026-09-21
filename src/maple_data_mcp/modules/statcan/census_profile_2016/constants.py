"""Constants for the 2016 Census Profile Web Data Service.

Confirmed live 2026-09-21, found via StatCan's official "Developers"
hub (statcan.gc.ca/en/developers) -- a genuinely different, live,
unauthenticated JSON REST API family for 2016 census data, distinct
from `modules/statcan/census_profile` (2021, SDMX) and from
`modules/statcan/census_profile_archive` (2001/2006/2011/2016 bulk
CSV/TAB downloads only, no live query). Two endpoints:

- CR2016Geo: list geographies (and their DGUIDs) for one level.
- CPR2016: full census profile data for one geography (all topics or
  one), given its DGUID from CR2016Geo.

Both are documented at
https://www12.statcan.gc.ca/wds-sdw/cr2016geo-eng.cfm and
https://www12.statcan.gc.ca/wds-sdw/cpr2016-eng.cfm.
"""

BASE_URL = "https://www12.statcan.gc.ca/rest/census-recensement"

RATE_LIMIT_SOURCE = "statcan-census-profile-2016"
RATE_LIMIT_PER_SECOND = 5.0
RATE_LIMIT_CAPACITY = 10.0

CACHE_TTL_SECONDS = 24 * 60 * 60

GEOGRAPHY_LEVELS = {
    "canada_provinces_territories": "PR",
    "census_divisions": "CD",
    "census_subdivisions": "CSD",
    "census_metro_areas": "CMACA",
    "census_tracts": "CT",
    "dissemination_areas": "DA",
    "designated_places": "DPL",
    "economic_regions": "ER",
    "federal_electoral_districts": "FED",
    "forward_sortation_areas": "FSA",
    "health_regions": "HR",
    "population_centres": "POPCNTR",
}

PROVINCE_TERRITORY_CODES = {
    "all": "00",
    "newfoundland_and_labrador": "10",
    "prince_edward_island": "11",
    "nova_scotia": "12",
    "new_brunswick": "13",
    "quebec": "24",
    "ontario": "35",
    "manitoba": "46",
    "saskatchewan": "47",
    "alberta": "48",
    "british_columbia": "59",
    "yukon": "60",
    "northwest_territories": "61",
    "nunavut": "62",
}

TOPICS = {
    "all_topics": 0,
    "aboriginal_peoples": 1,
    "education": 2,
    "ethnic_origin": 3,
    "families_households_and_marital_status": 4,
    "housing": 5,
    "immigration_and_citizenship": 6,
    "income": 7,
    "journey_to_work": 8,
    "labour": 9,
    "language": 10,
    "language_of_work": 11,
    "mobility": 12,
    "population": 13,
    "visible_minority": 14,
}

STATISTIC_TO_CODE = {"counts": 0, "rate": 1}
LANG_TO_CODE = {"en": "E", "fr": "F"}
