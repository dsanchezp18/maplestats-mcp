"""Constants for StatCan's "Reference resources" catalogue search.

Confirmed live 2026-09-21. This is StatCan's central repository of
definitions, data sources, methods, and survey documentation --
distinct from The Daily (`modules/statcan/daily`) and from the actual
data tables (WDS/SDMX/RDaaS) -- 2,031 documents confirmed live at
`www150.statcan.gc.ca/n1/en/type/reference` (a plain Drupal 10
faceted-search view, no JSON API). Real quirk handled: the `text`
query parameter is silently ignored -- the response still renders
every document, unfiltered -- unless the requesting session has first
loaded the unparameterized base page and carries the session cookie it
sets; confirmed live with a bare `curl` reproducing this exactly
(same URL, same query string, different result depending only on
whether the base page was visited first in the same cookie jar). This
client "warms up" its session with one request to BASE_URL before its
first real search in a process.

French uses a different path (plural "references", confirmed live)
and a different query parameter name (`texte`, not `text`).
"""

BASE_URL_TEMPLATE = "https://www150.statcan.gc.ca/n1/{lang}/type/{path}"
# lang -> (path segment, query param name for the keyword)
LANG_CONFIG = {
    "en": {"path": "reference", "query_param": "text"},
    "fr": {"path": "references", "query_param": "texte"},
}

RATE_LIMIT_SOURCE = "statcan-reference"
RATE_LIMIT_PER_SECOND = 3.0
RATE_LIMIT_CAPACITY = 5.0

CACHE_TTL_SECONDS = 6 * 60 * 60

SEARCH_COUNT_DEFAULT = 10
SEARCH_COUNT_MAX = 100
