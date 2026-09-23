BASE_URL = "https://canadabuys.canada.ca/opendata/pub"
OPEN_TENDERS_URL = f"{BASE_URL}/openTenderNotice-ouvertAvisAppelOffres.csv"
NEW_TENDERS_URL = f"{BASE_URL}/newTenderNotice-nouvelAvisAppelOffres.csv"
# Award notices are split into one file per federal fiscal year
# (April 1 to March 31), named e.g. "2026-2027-awardNotice-avisAttribution.csv".
AWARDS_URL_TEMPLATE = BASE_URL + "/{fiscal_year}-awardNotice-avisAttribution.csv"
# Confirmed live 2026-09-22: 2022-2023 is the first per-year award file
# CanadaBuys publishes; earlier awards only exist in the legacy bulk file.
FIRST_AWARD_FISCAL_YEAR = 2022
FISCAL_YEAR_TIMEZONE = "America/Toronto"

RATE_LIMIT_SOURCE = "canadabuys"
RATE_LIMIT_PER_SECOND = 1.0
RATE_LIMIT_CAPACITY = 2.0
# The files are regenerated once a day (Last-Modified early morning ET),
# so a few hours of caching avoids re-downloading multi-MB files per call
# without serving a day-old notice list.
CACHE_TTL_SECONDS = 4 * 60 * 60
SEARCH_RESULTS_DEFAULT = 25
SEARCH_RESULTS_MAX = 100
SUMMARY_DESCRIPTION_CHARS = 300
