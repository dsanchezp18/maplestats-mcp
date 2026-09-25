BASE_URL = "https://canadabuys.canada.ca/opendata/pub"
OPEN_TENDERS_URL = f"{BASE_URL}/openTenderNotice-ouvertAvisAppelOffres.csv"
NEW_TENDERS_URL = f"{BASE_URL}/newTenderNotice-nouvelAvisAppelOffres.csv"
# Award notices are split into one file per federal fiscal year
# (April 1 to March 31), named e.g. "2026-2027-awardNotice-avisAttribution.csv".
AWARDS_URL_TEMPLATE = BASE_URL + "/{fiscal_year}-awardNotice-avisAttribution.csv"
# Confirmed live 2026-09-22: 2022-2023 is the first per-year award file
# CanadaBuys publishes; earlier awards only exist in the legacy bulk file.
FIRST_AWARD_FISCAL_YEAR = 2022
# Contract history ("contrats octroyés") is also one file per fiscal
# year, confirmed live 2026-09-22 back to 2009-2010, plus a partial
# "2009-jan-Mar" file for the last quarter of fiscal 2008-2009.
CONTRACTS_URL_TEMPLATE = BASE_URL + "/{fiscal_year}-contractHistory-contratsOctroyes.csv"
FIRST_CONTRACT_FISCAL_YEAR = 2009
CONTRACTS_PARTIAL_2009_KEY = "2009-jan-Mar"
# Whole-history and pre-CanadaBuys legacy files: 57MB to 833MB each
# (Content-Length confirmed live 2026-09-22), far too large to download
# per tool call, so they are only listed with their links and sizes.
BULK_FILES = {
    "tenders_complete": (
        "All CanadaBuys tender notices, 2022-08-08 onwards",
        "tenderNoticeComplete-avisAppelOffresComplet.csv",
    ),
    "tenders_legacy": (
        "Legacy tender notices, 2009 to 2022 (prior to CanadaBuys)",
        "2009-2022-tenderNoticeHistorical-AvisAppelOffresHistorique.csv",
    ),
    "awards_complete": (
        "All CanadaBuys award notices, 2022-08-08 onwards",
        "awardNoticeComplete-avisAttributionComplet.csv",
    ),
    "awards_legacy": (
        "Legacy award notices, 2012 to 2022-08 (prior to CanadaBuys)",
        "2012-2022-awardNoticeHistorical-avisAttributionHistorique.csv",
    ),
    "contracts_complete": (
        "All CanadaBuys contract history, 2023-06-01 onwards",
        "contractHistoryComplete-contratsOctroyesComplet.csv",
    ),
    "contracts_legacy": (
        "Legacy contract history, 2009-01 to 2023-05 (prior to CanadaBuys)",
        "2009-2023-contractHistoryHistorical-contratsOctroyesHistorique.csv",
    ),
}
FISCAL_YEAR_TIMEZONE = "America/Toronto"

RATE_LIMIT_SOURCE = "canadabuys"
RATE_LIMIT_PER_SECOND = 1.0
RATE_LIMIT_CAPACITY = 2.0
# The files are regenerated once a day (Last-Modified early morning ET),
# so a few hours of caching avoids re-downloading multi-MB files per call
# without serving a day-old notice list.
CACHE_TTL_SECONDS = 4 * 60 * 60
# Past fiscal years' contract files rarely change and run up to 113MB
# (2009-2010), so they are kept for a day instead of re-downloaded.
PAST_YEAR_CACHE_TTL_SECONDS = 24 * 60 * 60
SEARCH_RESULTS_DEFAULT = 25
SEARCH_RESULTS_MAX = 100
SUMMARY_DESCRIPTION_CHARS = 300
