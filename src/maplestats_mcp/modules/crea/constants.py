SOURCE = "crea"
TIMEZONE = "America/Toronto"

# Confirmed live 2026-10-03 (see the module docstring for the spelling drift).
ZIP_URL = "https://www.crea.ca/files/mls-hpi-data/MLS_HPI_{month}_{year}.zip"
SHORT_MONTHS = {
    1: "Jan",
    2: "Feb",
    3: "Mar",
    4: "Apr",
    5: "May",
    6: "Jun",
    7: "Jul",
    8: "Aug",
    9: "Sept",
    10: "Oct",
    11: "Nov",
    12: "Dec",
}
FULL_MONTHS = {
    1: "January",
    2: "February",
    3: "March",
    4: "April",
    5: "May",
    6: "June",
    7: "July",
    8: "August",
    9: "September",
    10: "October",
    11: "November",
    12: "December",
}

# CREA releases the national statistics and the HPI around the 15th; the
# 14 Sep 2026 file was the newest on 3 Oct. Before this day of the month the
# client looks for the previous month's file, so a release that slips a few
# days does not leave it looking for a file that is not out yet.
RELEASE_SETTLED_DAY = 20

# Pages, English and French, each answered HTTP 200 on 2026-10-03.
PAGES = {
    "hpi_tool": {
        "en": "https://www.crea.ca/housing-market-stats/mls-home-price-index/hpi-tool/",
        "fr": (
            "https://www.crea.ca/fr/analyses-du-marche-de-lhabitation/"
            "indice-des-prix-des-proprietes-mls-ipp-mls/essayez-loutil-ipp-mls/"
        ),
    },
    "national_statistics": {
        "en": "https://stats.crea.ca/en-CA/",
        "fr": "https://stats.crea.ca/fr-CA/",
    },
    "quarterly_forecasts": {
        "en": (
            "https://www.crea.ca/housing-market-stats/canadian-housing-market-stats/"
            "quarterly-forecasts/"
        ),
        "fr": (
            "https://www.crea.ca/fr/analyses-du-marche-de-lhabitation/"
            "statistiques-sur-le-marche-de-lhabitation-canadien/previsions-trimestrielles/"
        ),
    },
    "housing_market_snapshot": {
        "en": "https://www.crea.ca/housing-market-stats/canadian-housing-market-stats/",
        "fr": (
            "https://www.crea.ca/fr/analyses-du-marche-de-lhabitation/"
            "statistiques-sur-le-marche-de-lhabitation-canadien/"
        ),
    },
    "terms": {
        "en": "https://www.crea.ca/legal/",
        "fr": "https://www.crea.ca/fr/renseignements-juridiques/",
    },
}

RATE_LIMIT_PER_SECOND = 1.0
RATE_LIMIT_CAPACITY = 2.0

CACHE_TTL_LINK_SECONDS = 6 * 60 * 60
