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

# Province and territory names and abbreviations -> the feed's 0-13 numbering, so
# geo_code="AB" or "Alberta" works and a place named in `query` filters by it. A
# model asked about Alberta passes "AB" or "Alberta" as often as a number; those
# were rejected as "not a whole number" (live /stats error, 2026-11-06). Keys are
# lower case with accents removed (see client._fold).
GEO_NAMES_TO_FEED_CODE = {
    "canada": 0,
    "can": 0,
    "ca": 0,
    "newfoundland and labrador": 1,
    "newfoundland": 1,
    "terre-neuve-et-labrador": 1,
    "terre-neuve": 1,
    "nl": 1,
    "prince edward island": 2,
    "ile-du-prince-edouard": 2,
    "pei": 2,
    "pe": 2,
    "ipe": 2,
    "nova scotia": 3,
    "nouvelle-ecosse": 3,
    "ns": 3,
    "new brunswick": 4,
    "nouveau-brunswick": 4,
    "nb": 4,
    "quebec": 5,
    "qc": 5,
    "ontario": 6,
    "on": 6,
    "manitoba": 7,
    "mb": 7,
    "saskatchewan": 8,
    "sk": 8,
    "alberta": 9,
    "ab": 9,
    "british columbia": 10,
    "colombie-britannique": 10,
    "bc": 10,
    "cb": 10,
    "yukon": 11,
    "yt": 11,
    "northwest territories": 12,
    "territoires du nord-ouest": 12,
    "nwt": 12,
    "nt": 12,
    "tno": 12,
    "nunavut": 13,
    "nu": 13,
}

# Words a query may use for an indicator whose title says something else. Each
# word matches a title containing any of its forms. Checked against the live
# titles of ind-all.json on 2026-11-06: "Consumer Price Index", "Real GDP - Canada",
# "Annual real gross domestic product by industry", "Unemployment rate".
QUERY_ALIASES = {
    "cpi": ("consumer price index", "cpi", "indice des prix a la consommation", "ipc"),
    "ipc": ("indice des prix a la consommation", "ipc", "consumer price index", "cpi"),
    "inflation": ("consumer price index", "cpi", "indice des prix a la consommation", "ipc"),
    "gdp": ("gdp", "gross domestic product"),
    "pib": ("pib", "produit interieur brut"),
    "jobless": ("unemployment",),
    "jobs": ("employment",),
    "chomage": ("chomage",),
}

# Words that carry no meaning for matching a title.
QUERY_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "the",
        "of",
        "in",
        "for",
        "to",
        "by",
        "on",
        "at",
        "latest",
        "current",
        "what",
        "is",
        "are",
        "de",
        "du",
        "des",
        "la",
        "le",
        "les",
        "l",
        "d",
        "en",
        "au",
        "aux",
        "et",
        "pour",
        "par",
    ]
)
