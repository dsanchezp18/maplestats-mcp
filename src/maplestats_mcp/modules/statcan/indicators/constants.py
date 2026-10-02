"""Constants for StatCan's official Indicators JSON feeds.

Confirmed live 2026-09-21, found via StatCan's official "Developers"
hub (statcan.gc.ca/en/developers). These are the same feeds that power
My StatCan, the home page's "Latest statistics", and The Daily's own
indicator widgets -- current values for named economic/social
indicators (population, CPI, GDP, trade balance, unemployment rate,
etc.), each carrying its reference period, a growth-rate summary
versus the prior period, and a link back to the Daily article that
released it.

Three datasets, all confirmed live: "all" (every indicator StatCan
tracks, 2,362 confirmed live), "economic" (a curated subset of major
economic indicators), and "homepage" (the subset shown on
statcan.gc.ca's own home page).
"""

DATASET_URLS = {
    "all": "https://www150.statcan.gc.ca/n1/dai-quo/ssi/homepage/ind-all.json",
    "economic": "https://www150.statcan.gc.ca/n1/dai-quo/ssi/homepage/ind-econ.json",
    "homepage": "https://www150.statcan.gc.ca/n1/dai-quo/ssi/homepage/ind-hp.json",
}

RATE_LIMIT_SOURCE = "statcan-indicators"
RATE_LIMIT_PER_SECOND = 5.0
RATE_LIMIT_CAPACITY = 10.0

# Indicators update at most once per business day.
CACHE_TTL_SECONDS = 6 * 60 * 60

SEARCH_LIMIT_DEFAULT = 20
SEARCH_LIMIT_MAX = 300

# Province/territory SGC codes -> the feed's own 0-13 numbering (verified live
# 2026-10-02 against the "geo" lookup of ind-all.json). 10-13 are not listed:
# they are valid feed codes (BC, YT, NT, NU) and collide with SGC 10-13.
SGC_TO_FEED_GEO_CODE = {
    24: 5,
    35: 6,
    46: 7,
    47: 8,
    48: 9,
    59: 10,
    60: 11,
    61: 12,
    62: 13,
}
