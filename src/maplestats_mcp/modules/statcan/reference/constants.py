"""Constants for StatCan's Drupal-based catalogue search views.

Confirmed live 2026-09-21. This one Drupal 10 faceted-search engine
backs at least three of StatCan's catalogues: "Reference resources"
(definitions, data sources, methods, and survey documentation --
distinct from The Daily (`modules/statcan/daily`), 2,031 documents
confirmed live), "Analysis" (analytical articles, "Stats in brief",
journals and periodicals -- 10,841+ documents confirmed live), and
"Data" (13,342+ items confirmed live) at
`www150.statcan.gc.ca/n1/en/type/{reference,analysis,data}`
respectively -- identical HTML structure, identical quirks, only the
path segment and document counts differ. No JSON API for any of them.

"Data" is not fully redundant with WDS/SDMX table search, confirmed
live: most of its results are ordinary table PIDs also reachable via
wds_/sdmx_, but it also indexes product families WDS has no discovery
path for at all -- notably Public Use Microdata Files (PUMFs, category
"Public use microdata"; confirmed live: searching "Public Use
Microdata Files" here returns 144 results, e.g. catalogue number
71M0001X for the Labour Force Survey PUMF, 98M0001X for the Census).
A PUMF's own catalogue-number page (via
statcan_reference_get_document_formats) links to a series index page
with the real bulk download -- confirmed live for 98M0001X: a direct,
unauthenticated ~173 MB ZIP download
(n1/pub/98m0001x/2023001/cen21_ind_98m0001x_part_rec21.zip, HTTP 200,
Content-Type: application/zip, no login or account required). That
per-product bulk-download page is its own bespoke static HTML layout
(not this Drupal engine), so it is surfaced as a link for a caller to
follow rather than parsed generically here.

Real quirk handled: the `text`/`texte` query parameter is silently
ignored -- the response still renders every document, unfiltered --
unless the requesting session has first loaded the unparameterized
base page and carries the session cookie it sets; confirmed live with
a bare `curl` reproducing this exactly (same URL, same query string,
different result depending only on whether the base page was visited
first in the same cookie jar). This client "warms up" its session with
one request to the base page before its first real search per
(catalogue, lang) pair in a process.

French uses a different, pluralized path ("references"/"analyses"/
"donnees", all confirmed live) and a different query parameter name
(`texte`, not `text`).
"""

BASE_URL_TEMPLATE = "https://www150.statcan.gc.ca/n1/{lang}/type/{path}"
# (catalogue, lang) -> (path segment, query param name for the keyword)
CATALOGUE_CONFIG = {
    ("reference", "en"): {"path": "reference", "query_param": "text"},
    ("reference", "fr"): {"path": "references", "query_param": "texte"},
    ("analysis", "en"): {"path": "analysis", "query_param": "text"},
    ("analysis", "fr"): {"path": "analyses", "query_param": "texte"},
    ("data", "en"): {"path": "data", "query_param": "text"},
    ("data", "fr"): {"path": "donnees", "query_param": "texte"},
}

RATE_LIMIT_SOURCE = "statcan-reference"
RATE_LIMIT_PER_SECOND = 3.0
RATE_LIMIT_CAPACITY = 5.0

CACHE_TTL_SECONDS = 6 * 60 * 60

SEARCH_COUNT_DEFAULT = 10
SEARCH_COUNT_MAX = 100
