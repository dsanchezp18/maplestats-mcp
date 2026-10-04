"""Constants for the Canadian Dairy Commission (CDC) module.

Every URL below was fetched live on 2026-09-26 from the CDC site
(cdc-ccl.ca, Drupal 10); the AAFC open-data server hosting the CDC market
data file is the one open.canada.ca links to.
"""

DOMAIN = "cdc-ccl.ca"
SITE = f"https://{DOMAIN}"

# Special milk class component prices, one static CSV per calendar year
# (2002 onward). The site's "History of Special Milk Class Prices" form
# posts to /en/pricing/history and answers with a cookie pointing at
# exactly this file; the file itself needs no form or session.
COMPONENT_PRICES_URL = SITE + "/sites/default/files/pricing/pricing_history_{year}.csv"
COMPONENT_PRICES_FIRST_YEAR = 2002
COMPONENT_PRICES_PAGE = {"en": SITE + "/en/pricing/history", "fr": SITE + "/fr/pricing/history"}

# Drupal node ids work in both languages (/en/node/N and /fr/node/N).
SUPPORT_PRICES_PAGE = {"en": SITE + "/en/node/720", "fr": SITE + "/fr/node/720"}
MILK_CLASSES_PAGE = {"en": SITE + "/en/node/717", "fr": SITE + "/fr/node/717"}
# Index of the yearly "National milk production target" pages; each year
# is a separate page whose node id is not predictable, so the client reads
# the year links from this index.
NATIONAL_QUOTA_INDEX = {"en": SITE + "/en/node/653", "fr": SITE + "/fr/node/653"}

# "Dairy statistics and market information" (open.canada.ca dataset
# 308a7041-413a-47a0-9604-ae1c55676693, organization aafc-aac, Open
# Government Licence - Canada): four CDC datasets in one bilingual CSV.
MARKET_DATA_URL = "https://od-do.agr.gc.ca/CDC_CCL.csv"
MARKET_DATA_DATASET_ID = "308a7041-413a-47a0-9604-ae1c55676693"
MARKET_DATA_DICTIONARY = {
    "en": "https://od-do.agr.gc.ca/CDCDictionaryEn.html",
    "fr": "https://od-do.agr.gc.ca/CCLDictionnaireFr.html",
}

RATE_LIMIT_SOURCE = "cdc"
RATE_LIMIT_PER_SECOND = 2.0
RATE_LIMIT_CAPACITY = 4.0

# Component prices are announced by the 15th of each month and 4(a)
# solids-non-fat prices by the 5th, so the current year's file changes
# at most a few times a month; past years are final.
CURRENT_YEAR_TTL_SECONDS = 6 * 60 * 60
PAST_YEAR_TTL_SECONDS = 7 * 24 * 60 * 60
PAGE_TTL_SECONDS = 12 * 60 * 60
MARKET_DATA_TTL_SECONDS = 6 * 60 * 60
MAX_PAGE_BYTES = 2 * 1024 * 1024

MARKET_DATA_DEFAULT_LIMIT = 500
MARKET_DATA_MAX_LIMIT = 5000

REFERENCE_TZ = "America/Toronto"
