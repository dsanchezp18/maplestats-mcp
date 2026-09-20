"""Constants for the BC Data Catalogue (CKAN BC) module.

Base URL and the `{"help", "success", "result"}` envelope confirmed live
this session directly against
https://catalogue.data.gov.bc.ca/api/3/action/site_read and
.../package_search?q=wildfire&rows=1 -- the standard CKAN Action API 3
shape (https://docs.ckan.org/en/latest/api/), not assumed from the
generic docs alone. See client.py for the deployment-specific field
quirks found while verifying it.
"""

BASE_URL = "https://catalogue.data.gov.bc.ca/api/3/action/"

# No documented per-request rate limit was found: this deployment's
# only throttling signal anywhere is robots.txt's "Crawl-Delay: 10"
# (https://catalogue.data.gov.bc.ca/robots.txt) -- half of
# ckan_federal's "Crawl-Delay: 20", but still generic HTML-crawler
# guidance, not API-specific (robots.txt also disallows crawling /api/
# entirely, which this module deliberately does not follow -- the
# Action API is a documented, intended integration surface, not the
# HTML site robots.txt is scoped to). Live response headers carry no
# X-RateLimit-* fields (checked directly); the only header signal is a
# Kong API gateway proxy (x-kong-upstream-latency/x-kong-proxy-latency),
# which exposes no rate-limit headers itself. Kept at the same
# conservative rate as ckan_federal rather than probing the real
# ceiling, since this is also a shared public-sector CKAN instance
# serving many clients.
RATE_LIMIT_SOURCE = "ckan-bc"
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
# The 26 curated groups (confirmed live via group_list) are a hand-
# maintained thematic roster, at least as stable as organizations.
CACHE_TTL_GROUP_LIST_SECONDS = 24 * 60 * 60  # 24h
CACHE_TTL_GROUP_SECONDS = CACHE_TTL_GROUP_LIST_SECONDS
# The ~7,087-tag vocabulary (confirmed live via tag_list) is free text
# added by publishers; treat it as similarly stable to search results
# rather than as volatile as an individual dataset's own metadata.
CACHE_TTL_TAG_LIST_SECONDS = 60 * 60  # 1h
CACHE_TTL_DATASTORE_SECONDS = 15 * 60  # 15m: DataStore-backed data can update daily

# Mirrors ckan_federal's DATASTORE_ROWS_MAX reasoning: this deployment's
# own datastore_search ceiling is far higher (confirmed live: limit=
# 999999 against a 5,014-row resource returned every row, not an
# error), so this stays capped well below that for agent-facing
# compactness rather than exposing whatever the raw server allows.
DATASTORE_ROWS_DEFAULT = 20
DATASTORE_ROWS_MAX = 1000

# CKAN's own package_search hard cap: a `rows` above this is silently
# truncated to 1000 server-side (confirmed live: rows=5000 returned
# exactly 1000 results, not an error -- the same cap as ckan_federal).
# SEARCH_ROWS_MAX bounds the agent-facing default well below that per
# AGENTS.md's "keep responses compact enough for MCP clients" principle.
SEARCH_ROWS_DEFAULT = 10
SEARCH_ROWS_MAX = 100

# How much of a dataset's `notes` survives into a compact search-result
# row before being truncated with an ellipsis; full text is available
# via ckan_bc_get_dataset.
NOTES_EXCERPT_LENGTH = 300

# CKAN's tag_list has no server-side rows/limit parameter -- confirmed
# live that an unfiltered call returns all ~7,087 tag names in one
# response. TAG_LIST_MAX caps that unfiltered case client-side so
# ckan_bc_list_tags stays compact; pass `query` (tag_list's own
# substring-match parameter, confirmed live) to search a specific term
# instead of relying on the capped full list.
TAG_LIST_MAX = 200

# group_list(all_fields=True) requires an authenticated session on this
# deployment -- confirmed live: an anonymous request returns HTTP 403
# with {"success": false, "error": {"__type": "Authorization Error",
# "message": "Access denied"}}. ckan_bc_list_groups uses
# package_search's `groups` facet instead (confirmed live, public,
# unauthenticated) to get each group's name/title/dataset count without
# touching group_list at all. GROUP_FACET_LIMIT bounds how many facet
# values Solr returns; the catalogue only has 26 groups total (confirmed
# live via the plain, unauthenticated group_list, which returns bare
# names with no auth wall), so this comfortably covers every one that
# has at least one dataset (facets only surface groups with count > 0).
GROUP_FACET_LIMIT = 200

# organization_list(all_fields=True) is silently capped at exactly 25
# results on this deployment, regardless of a `limit`/`rows` parameter
# -- confirmed live by trying limit=300/rows=300/sort=package_count/
# order_by=name, all still returning 25 of the portal's ~244
# organizations. This differs from ckan_federal, where
# organization_list(all_fields=True) returns its full roster uncapped.
# ckan_bc_list_organizations works around this the same way
# ckan_bc_list_groups works around group_list's auth wall: reading
# package_search's `organization` facet instead (confirmed live,
# uncapped, returned all 164 organizations that have at least one
# dataset). ORGANIZATION_FACET_LIMIT bounds how many facet values Solr
# returns; set comfortably above the ~164 organizations confirmed to
# have at least one dataset.
ORGANIZATION_FACET_LIMIT = 500

# Human-browsable dataset/organization/group landing pages, for
# provenance and for handing an agent a link a person can actually open
# (the Action API's own URLs are JSON endpoints, not useful to click).
# No {lang} placeholder -- confirmed live this portal is English-only
# (see __init__.py's module docstring), unlike ckan_federal's bilingual
# .../data/{lang}/dataset/... pattern.
DATASET_LANDING_URL = "https://catalogue.data.gov.bc.ca/dataset/"
ORGANIZATION_LANDING_URL = "https://catalogue.data.gov.bc.ca/organization/"
GROUP_LANDING_URL = "https://catalogue.data.gov.bc.ca/group/"
