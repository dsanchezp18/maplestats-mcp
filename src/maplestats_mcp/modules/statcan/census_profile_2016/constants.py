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

# Checked 2026-10-02 and 2026-10-05: www12.statcan.gc.ca answers every
# path, this REST API included, with HTTP 403 and a Cloudflare managed
# challenge ("Just a moment..."), which only a browser can pass. MapleStats does not try to get
# past it; the tools report the block and point to the same data elsewhere.
BLOCKED_NOTE = (
    "Statistics Canada's www12 host, which serves the 2016 Census Profile service, is "
    "currently behind a Cloudflare bot challenge that scripts cannot pass. WDS "
    "holds the indicator subset of the 2016 profile at those levels only (Canada, provinces "
    "and territories, health regions; no census subdivisions, tracts or dissemination "
    "areas): wds_search_cubes for 'Census indicator profile' (17100122 short form, "
    "17100123 long form) read with wds_get_data_from_cube_coord; 2021 figures are "
    "in statcan_census_profile_*. Bulk 2016 files: statcan_census_profile_archive_* "
    "(download in a browser)."
)
BLOCKED_NOTE_FR = (
    "Le serveur www12 de Statistique Canada, qui sert le service du Profil du recensement de "
    "2016, est actuellement derrière une vérification de sécurité Cloudflare que les scripts "
    "ne peuvent pas franchir. Le WDS contient le sous-ensemble d'indicateurs du profil de 2016 "
    "à ces seuls niveaux (Canada, provinces et territoires, régions sociosanitaires\u00a0; "
    "aucune subdivision de recensement, aucun secteur de recensement ni aucune aire de "
    "diffusion) : wds_search_cubes avec «\u00a0Census indicator profile\u00a0» "
    "(17100122 pour le questionnaire abrégé, 17100123 pour le questionnaire détaillé), à lire "
    "avec wds_get_data_from_cube_coord\u00a0; les chiffres de 2021 sont dans "
    "statcan_census_profile_*. Fichiers complets de 2016 : "
    "statcan_census_profile_archive_* (à télécharger dans un navigateur)."
)
