"""Constants for the Government of Canada Open Data (CKAN federal) module.

Base URL and the `{"help", "success", "result"}` envelope confirmed live
this session directly against
https://open.canada.ca/data/api/3/action/package_search?q=climate&rows=1
— the standard CKAN Action API 3 shape
(https://docs.ckan.org/en/latest/api/), not assumed from the generic
docs alone. See client.py for the deployment-specific field quirks
found while verifying it.
"""

BASE_URL = "https://open.canada.ca/data/api/3/action/"

# No documented per-request rate limit was found: the API docs page
# (https://open.canada.ca/data/en/api) is a bare {"version": 1} stub
# with no throttling guidance, and live response headers carry no
# X-RateLimit-* fields (checked directly). The only published
# throttling signal anywhere on the host is robots.txt's
# "Crawl-delay: 20" (generic HTML-crawler guidance, not API-specific —
# https://open.canada.ca/robots.txt). Since this is a shared
# public-sector CKAN instance serving many clients against an
# ~48,000-dataset catalogue, stay conservative rather than probe for
# the real ceiling.
RATE_LIMIT_SOURCE = "ckan-federal"
RATE_LIMIT_PER_SECOND = 2.0
RATE_LIMIT_CAPACITY = 5.0

CACHE_TTL_SEARCH_SECONDS = 10 * 60  # 10m: search results/catalogue change often
CACHE_TTL_PACKAGE_SECONDS = 60 * 60  # 1h
# An individual organization's title/description is at least as stable
# as the roster it's drawn from, so organization_show shares the same
# 24h TTL as organization_list rather than the shorter default below.
CACHE_TTL_ORGANIZATION_LIST_SECONDS = 24 * 60 * 60  # 24h: org roster is stable
CACHE_TTL_ORGANIZATION_SECONDS = CACHE_TTL_ORGANIZATION_LIST_SECONDS
CACHE_TTL_RESOURCE_SECONDS = 60 * 60  # 1h
CACHE_TTL_LICENSE_LIST_SECONDS = 7 * 24 * 60 * 60  # 7d: licenses rarely change

# CKAN's own package_search hard cap: a `rows` above this is silently
# truncated to 1000 server-side (confirmed live: rows=5000 returned
# exactly 1000 results, not an error). SEARCH_ROWS_MAX bounds the
# agent-facing default well below that per AGENTS.md's "keep responses
# compact enough for MCP clients" principle -- an agent deciding which
# dataset to open next with ckan_get_dataset rarely needs more than a
# couple dozen hits at once.
SEARCH_ROWS_DEFAULT = 10
SEARCH_ROWS_MAX = 100

# How much of a dataset's `notes` survives into a compact search-result
# row before being truncated with an ellipsis; full text is available
# via ckan_get_dataset.
NOTES_EXCERPT_LENGTH = 300

# Human-browsable dataset/organization landing pages, for provenance
# and for handing an agent a link a person can actually open (the
# Action API's own URLs are JSON endpoints, not useful to click).
# {lang} is "en"/"fr" - confirmed live that both
# https://open.canada.ca/data/en/dataset/<id> and .../data/fr/dataset/<id>
# 302-redirect to a working bilingual landing page for a real dataset id.
DATASET_LANDING_URL = "https://open.canada.ca/data/{lang}/dataset/"
ORGANIZATION_LANDING_URL = "https://open.canada.ca/data/{lang}/organization/"
