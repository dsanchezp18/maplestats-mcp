"""Constants for the City of Regina Open Data (CKAN Regina) module.

The public UI and the Action API share one host, unlike Toronto's split
between open.toronto.ca (UI) and a separate infrastructure host --
confirmed live: https://openregina.ca/api/3/action/package_list and
https://openregina.ca/dataset/<name> both resolve on the same domain.
"""

BASE_URL = "https://openregina.ca/api/3/action/"

# No documented per-request rate limit was found; no X-RateLimit-*
# header on any response and ten sequential package_show requests all
# returned 200 with no throttling observed. Staying conservative --
# same values used for every other CKAN module in this codebase --
# since this is the production API backing the public site.
RATE_LIMIT_SOURCE = "ckan-regina"
RATE_LIMIT_PER_SECOND = 2.0
RATE_LIMIT_CAPACITY = 5.0

CACHE_TTL_SEARCH_SECONDS = 10 * 60  # 10m: search results/catalogue change often
CACHE_TTL_PACKAGE_SECONDS = 60 * 60  # 1h
# Confirmed live: exactly one organization (city-of-regina, 1,379
# packages) -- as stable a roster as Toronto's single-organization
# portal, same 24h TTL rationale.
CACHE_TTL_ORGANIZATION_LIST_SECONDS = 24 * 60 * 60  # 24h
CACHE_TTL_ORGANIZATION_SECONDS = CACHE_TTL_ORGANIZATION_LIST_SECONDS
CACHE_TTL_RESOURCE_SECONDS = 60 * 60  # 1h
CACHE_TTL_LICENSE_LIST_SECONDS = 7 * 24 * 60 * 60  # 7d
CACHE_TTL_TAG_LIST_SECONDS = 24 * 60 * 60  # 24h
# Confirmed live: group_list(all_fields=true) is public here (HTTP 200,
# no auth needed) -- unlike ckan_bc, where the same call returns 403 and
# a package_search facet has to be used instead. Regina's group roster
# (25+ curated topics, confirmed live) changes about as often as its
# organization roster.
CACHE_TTL_GROUP_LIST_SECONDS = 24 * 60 * 60  # 24h
CACHE_TTL_GROUP_SECONDS = CACHE_TTL_GROUP_LIST_SECONDS

# Confirmed live: package_search accepted rows well beyond the
# catalogue's own size with no server-side rejection observed.
# SEARCH_ROWS_MAX still bounds the agent-facing default per AGENTS.md's
# "keep responses compact" principle, not because the API enforces it.
SEARCH_ROWS_DEFAULT = 10
SEARCH_ROWS_MAX = 100

# This deployment has no curated `excerpt` field (unlike Toronto) --
# confirmed live across sampled packages, only the raw `notes` field
# exists -- so PackageSummary truncates `notes` client-side, the same
# pattern as ckan_federal/ckan_bc.
NOTES_EXCERPT_MAX_LENGTH = 300

DATASET_LANDING_URL = "https://openregina.ca/dataset/"
ORGANIZATION_LANDING_URL = "https://openregina.ca/organization/"
GROUP_LANDING_URL = "https://openregina.ca/group/"
