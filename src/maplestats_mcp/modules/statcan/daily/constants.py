"""Constants for The Daily (StatCan's official release bulletin) Atom feeds.

Confirmed live 2026-09-20: `www150.statcan.gc.ca/n1/dai-quo/index-eng.htm`
(The Daily's own landing page) has no JSON API behind it -- its
"Search The Daily" and calendar views are plain server-rendered HTML.
The genuine, documented, machine-readable path is the official Atom
feed family listed at `www150.statcan.gc.ca/eng/sc/rss`: one feed per
subject (30 subjects) plus an "all" feed covering every subject in one
call, each carrying the last 100 days of releases (title, canonical
URL, publication timestamp, plain-text summary). No API key or session
required.

The Atom feeds only cover 100 days. The release-schedule calendar page
(`n1/dai-quo/cal3-eng.htm`) renders a much deeper history client-side
from a single JSON file its own inline script points at
(`eventsjson:`) -- found by fetching the calendar page's raw HTML
(not its browser-rendered DOM) and reading that script config
directly, since the file is loaded by client-side JS rather than
linked as a normal href. That file
(`FULL_ARCHIVE_URL` below) is the complete Daily release archive:
18,222 entries confirmed live, from 2012-03-14 (StatCan's own calendar
UI separately claims "since April 2012" -- the JSON's actual earliest
entry is about three weeks earlier) through several weeks of scheduled
upcoming releases past the current date. One 3.7 MB JSON array, no
pagination, no API key.
"""

BASE_URL = "https://www150.statcan.gc.ca/n1/rss/dai-quo"
FULL_ARCHIVE_URL = (
    "https://www150.statcan.gc.ca/n1/dai-quo/ssi/homepage/schedule-previous_releases-{suffix}.json"
)

ATOM_NS = {"atom": "http://www.w3.org/2005/Atom", "xhtml": "http://www.w3.org/1999/xhtml"}

RATE_LIMIT_SOURCE = "statcan-daily"
RATE_LIMIT_PER_SECOND = 5.0
RATE_LIMIT_CAPACITY = 10.0

# StatCan releases The Daily once per business day at 8:30am ET.
CACHE_TTL_SECONDS = 30 * 60

RELEASES_LIMIT_DEFAULT = 20
RELEASES_LIMIT_MAX = 300  # confirmed live: "all" feed carries ~270 entries

# The archive file is large (3.7 MB) and only grows by a handful of
# entries per business day -- cached longer than the 100-day feeds.
CACHE_TTL_ARCHIVE_SECONDS = 6 * 60 * 60
ARCHIVE_SEARCH_LIMIT_DEFAULT = 20
ARCHIVE_SEARCH_LIMIT_MAX = 200

# subject key -> feed numeric code, confirmed live from
# www150.statcan.gc.ca/eng/sc/rss
SUBJECT_TO_CODE = {
    "all": "0",
    "agriculture_and_food": "32",
    "business_and_consumer_services_and_culture": "21",
    "business_performance_and_ownership": "33",
    "children_and_youth": "42",
    "construction": "34",
    "crime_and_justice": "35",
    "digital_economy_and_society": "22",
    "economic_accounts": "36",
    "education_training_and_learning": "37",
    "energy": "25",
    "environment": "38",
    "families_households_and_marital_status": "39",
    "government": "10",
    "health": "13",
    "housing": "46",
    "immigration_and_ethnocultural_diversity": "43",
    "income_pensions_spending_and_wealth": "11",
    "indigenous_peoples": "41",
    "international_trade": "12",
    "labour": "14",
    "languages": "15",
    "manufacturing": "16",
    "older_adults_and_population_aging": "44",
    "population_and_demography": "17",
    "prices_and_price_indexes": "18",
    "reference": "89",
    "retail_and_wholesale": "20",
    "science_and_technology": "27",
    "society_and_community": "45",
    "statistical_methods": "19",
    "transportation": "23",
    "travel_and_tourism": "24",
}

LANG_TO_SUFFIX = {"en": "eng", "fr": "fra"}
