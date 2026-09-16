"""Constants for the City of Toronto Open Data (CKAN Toronto) module.

The public-facing site is open.toronto.ca, but the Action API itself
lives on a separate infrastructure host -- confirmed live this session:
https://ckan0.cf.opendata.inter.prod-toronto.ca/api/3/action/package_list
returned the standard `{"help", "success", "result"}` envelope with a
557-id result, while open.toronto.ca serves only the human-browsable
catalogue UI, not the Action API. BASE_URL below is the API host;
DATASET_LANDING_URL/ORGANIZATION_LANDING_URL below are the UI host,
matching the federal module's own base-URL-vs-landing-URL split.
"""

BASE_URL = "https://ckan0.cf.opendata.inter.prod-toronto.ca/api/3/action/"

# No documented per-request rate limit was found. The API host's
# robots.txt (https://ckan0.cf.opendata.inter.prod-toronto.ca/robots.txt,
# checked directly) explicitly "Allow: /api/" with no Crawl-delay
# directive anywhere in the file, and no response carried an
# X-RateLimit-* header (checked directly on package_search/package_show).
# Ten sequential package_show requests all returned 200 with no
# throttling observed. Still staying conservative -- same values as
# ckan_federal -- since this is a shared production API backing the
# public open.toronto.ca site, not a sandbox, and the catalogue is
# small enough (557 datasets) that a slow crawl costs nothing.
RATE_LIMIT_SOURCE = "ckan-toronto"
RATE_LIMIT_PER_SECOND = 2.0
RATE_LIMIT_CAPACITY = 5.0

CACHE_TTL_SEARCH_SECONDS = 10 * 60  # 10m: search results/catalogue change often
CACHE_TTL_PACKAGE_SECONDS = 60 * 60  # 1h
# Only one organization exists on this portal (city-of-toronto,
# confirmed live via organization_list) -- its roster is at least as
# stable as the federal module's ~350-department roster, so it shares
# the same 24h TTL rationale.
CACHE_TTL_ORGANIZATION_LIST_SECONDS = 24 * 60 * 60  # 24h: org roster is stable
CACHE_TTL_ORGANIZATION_SECONDS = CACHE_TTL_ORGANIZATION_LIST_SECONDS
CACHE_TTL_RESOURCE_SECONDS = 60 * 60  # 1h
CACHE_TTL_LICENSE_LIST_SECONDS = 7 * 24 * 60 * 60  # 7d: licenses rarely change
CACHE_TTL_TAG_LIST_SECONDS = 24 * 60 * 60  # 24h: tag vocabulary is stable

# Confirmed live: package_search with rows=999999 still returned HTTP
# 200 with all 557 results (no server-side truncation observed, unlike
# the federal portal's confirmed hard 1000-row cap) -- this deployment
# appears to impose no ceiling of its own. SEARCH_ROWS_MAX still bounds
# the agent-facing default well below the full catalogue size per
# AGENTS.md's "keep responses compact enough for MCP clients"
# principle, not because the API would reject a larger request.
SEARCH_ROWS_DEFAULT = 10
SEARCH_ROWS_MAX = 100

# Toronto's package_search results carry a curated `excerpt` field
# written by the publishing team (confirmed live: populated on 100/100
# sampled packages, max observed length 348 characters) -- unlike the
# federal portal, which has no such field and requires truncating
# `notes` client-side. EXCERPT_MAX_LENGTH is a defensive cap only, in
# case a future record's excerpt is unusually long; it is not expected
# to trigger in normal use.
EXCERPT_MAX_LENGTH = 500

# Human-browsable dataset landing page, on the PUBLIC-FACING domain
# (open.toronto.ca), not the API host. Confirmed live:
# https://open.toronto.ca/dataset/<name>/ returns 200 for a real
# dataset name (package_show's `name`, not its `id`, is the correct
# key here -- confirmed live). No French variant exists: this portal's
# CKAN data carries no `_translated`/`_fra` fields at all (confirmed
# across a 50-package live sample), so there is no {lang} placeholder
# to fill, unlike the federal module's bilingual DATASET_LANDING_URL.
DATASET_LANDING_URL = "https://open.toronto.ca/dataset/"

# There is no per-organization landing page on this portal (confirmed
# live: https://open.toronto.ca/organization/city-of-toronto/ returns
# 404) -- expected, since only one organization exists here. The
# working equivalent is the catalogue page filtered to that
# organization, confirmed live:
# https://open.toronto.ca/catalogue/?organization=city-of-toronto
# returns 200.
ORGANIZATION_LANDING_URL = "https://open.toronto.ca/catalogue/?organization="
