"""Constants for the City of Montreal open-data (CKAN Montreal) module.

Base URL and the `{"help", "success", "result"}` envelope confirmed live
this session directly against
https://donnees.montreal.ca/api/3/action/package_search?q=&rows=1
-- the standard CKAN Action API 3 shape, not assumed from generic docs.
See client.py for the deployment-specific field quirks found while
verifying it.
"""

BASE_URL = "https://donnees.montreal.ca/api/3/action/"

# No documented per-request rate limit was found: there is no public API
# docs page for this deployment, live response headers carry no
# X-RateLimit-* fields (checked directly against package_search), and
# https://donnees.montreal.ca/robots.txt returned a bare "RBAC: access
# denied" body rather than a normal robots.txt (checked directly) -- not
# a usable Crawl-delay signal the way federal's robots.txt gave one.
# `server: istio-envoy` + `Via: 1.1 google` on every response indicates a
# managed, multi-tenant edge (Envoy/GCP), not a dedicated box -- stay
# conservative for the same reason ckan_federal does: a shared public
# portal serving many clients, not a known-dedicated one.
RATE_LIMIT_SOURCE = "ckan-montreal"
RATE_LIMIT_PER_SECOND = 2.0
RATE_LIMIT_CAPACITY = 5.0

CACHE_TTL_SEARCH_SECONDS = 10 * 60  # 10m: search results/catalogue change often
CACHE_TTL_PACKAGE_SECONDS = 60 * 60  # 1h
# An individual organization's title/description is at least as stable
# as the roster it's drawn from, so organization_show shares the same
# 24h TTL as organization_list rather than the shorter default below.
CACHE_TTL_ORGANIZATION_LIST_SECONDS = (
    24 * 60 * 60
)  # 24h: org roster is stable (6 orgs, confirmed live)
CACHE_TTL_ORGANIZATION_SECONDS = CACHE_TTL_ORGANIZATION_LIST_SECONDS
CACHE_TTL_RESOURCE_SECONDS = 60 * 60  # 1h
CACHE_TTL_LICENSE_LIST_SECONDS = 7 * 24 * 60 * 60  # 7d: licenses rarely change
# Tags (1,174 live) and groups (12 live) are both roster-like and stable
# for the same reason organization_list is -- share its 24h TTL.
CACHE_TTL_TAG_LIST_SECONDS = CACHE_TTL_ORGANIZATION_LIST_SECONDS
CACHE_TTL_GROUP_LIST_SECONDS = CACHE_TTL_ORGANIZATION_LIST_SECONDS

# Unlike ckan_federal's confirmed hard server-side cap of 1000, this
# deployment showed no server-side cap: rows=5000 against a 404-dataset
# catalogue returned all 404 results, not a truncated 1000 (confirmed
# live). SEARCH_ROWS_MAX still bounds the agent-facing default well below
# the full catalogue size per AGENTS.md's "keep responses compact enough
# for MCP clients" principle.
SEARCH_ROWS_DEFAULT = 10
SEARCH_ROWS_MAX = 100

# How much of a dataset's `notes` (or an organization's `description`)
# survives into a compact row before being truncated with an ellipsis;
# full text is available via ckan_montreal_get_dataset/get_organization.
NOTES_EXCERPT_LENGTH = 300
DESCRIPTION_EXCERPT_LENGTH = 200

# Human-browsable dataset/organization landing pages. {lang} is "en"/"fr"
# -- confirmed live that https://donnees.montreal.ca/{en,fr}/dataset/<id>
# and .../{en,fr}/organization/<name> all return HTTP 200 (a plain UA-less
# curl request gets HTTP 403 from this host's bot-detection; a
# browser-like User-Agent is required to reproduce the 200, which is how
# this was actually confirmed). Only the surrounding CKAN UI chrome
# changes with {lang} -- the dataset content itself stays French
# regardless, per this module's language-default finding (see
# __init__.py's docstring).
DATASET_LANDING_URL = "https://donnees.montreal.ca/{lang}/dataset/"
ORGANIZATION_LANDING_URL = "https://donnees.montreal.ca/{lang}/organization/"


CACHE_TTL_DATASTORE_SECONDS = 15 * 60  # 15m: DataStore-backed data can update daily

# Mirrors ckan_federal/ckan_bc's DATASTORE_ROWS_MAX reasoning: kept far
# below whatever this deployment's own datastore_search ceiling is, for
# agent-facing compactness rather than exposing the raw server limit.
DATASTORE_ROWS_DEFAULT = 20
DATASTORE_ROWS_MAX = 1000
