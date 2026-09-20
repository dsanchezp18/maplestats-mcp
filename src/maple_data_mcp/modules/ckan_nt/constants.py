"""Constants for the Northwest Territories Open Data (CKAN NT) module.

Base URL, the `{"help", "success", "result"}` envelope, and every count
below confirmed live this session directly against
https://opendata.gov.nt.ca/api/3/action/... -- the standard CKAN Action
API 3 shape (https://docs.ckan.org/en/latest/api/), not assumed from the
generic docs or from modules/ckan_federal/'s deployment-specific choices.
See client.py for the deployment-specific field quirks found while
verifying it.
"""

BASE_URL = "https://opendata.gov.nt.ca/api/3/action/"

# No documented per-request rate limit was found: this portal publishes
# no API docs page distinct from its dataset pages, and live response
# headers carry no X-RateLimit-* fields (checked directly). The only
# published throttling signal anywhere on the host is robots.txt's
# "Crawl-Delay: 10" alongside "Disallow: /api/"
# (https://opendata.gov.nt.ca/robots.txt) -- the Disallow targets
# generic web crawlers, not this Action API client, but it is still a
# signal that this deployment does not expect or want heavy automated
# traffic against /api/. This is a small territorial-government
# catalogue (341 datasets, confirmed live), likely running on lighter
# infrastructure than the federal open.canada.ca instance, so this
# module stays more conservative than ckan_federal's 2.0/5.0 rather than
# matching it.
RATE_LIMIT_SOURCE = "ckan-nt"
RATE_LIMIT_PER_SECOND = 1.0
RATE_LIMIT_CAPACITY = 3.0

CACHE_TTL_SEARCH_SECONDS = 10 * 60  # 10m: search results/catalogue change often
CACHE_TTL_PACKAGE_SECONDS = 60 * 60  # 1h
# An individual organization's/group's title/description is at least as
# stable as the roster it's drawn from, so organization_show/group_show
# share the same 24h TTL as their *_list counterparts rather than the
# shorter default below.
CACHE_TTL_ORGANIZATION_LIST_SECONDS = 24 * 60 * 60  # 24h: org roster is stable
CACHE_TTL_ORGANIZATION_SECONDS = CACHE_TTL_ORGANIZATION_LIST_SECONDS
CACHE_TTL_GROUP_LIST_SECONDS = 24 * 60 * 60  # 24h: topic-group roster is stable
CACHE_TTL_TAG_LIST_SECONDS = 24 * 60 * 60  # 24h: tag vocabulary is stable
CACHE_TTL_RESOURCE_SECONDS = 60 * 60  # 1h
CACHE_TTL_LICENSE_LIST_SECONDS = 7 * 24 * 60 * 60  # 7d: licenses rarely change

# This catalogue has only 341 datasets total (package_search with no
# filter, confirmed live) -- far below the 1000-row hard cap CKAN's own
# package_search enforces server-side (confirmed on the federal portal;
# a rows=5000 request here returned all 341 results untruncated, so the
# cap was not independently re-observed on this deployment, but nothing
# suggests it is lower). SEARCH_ROWS_MAX stays at the same 100 default
# this codebase uses for the much larger federal catalogue: response
# compactness for an MCP client is a property of one page of results,
# not of the catalogue's total size, so a small catalogue does not
# justify a larger per-request cap.
SEARCH_ROWS_DEFAULT = 10
SEARCH_ROWS_MAX = 100

# How much of a dataset's `notes` survives into a compact search-result
# row before being truncated with an ellipsis; full text is available
# via ckan_nt_get_dataset.
NOTES_EXCERPT_LENGTH = 300

# Human-browsable dataset/organization/group landing pages, for
# provenance and for handing an agent a link a person can actually open
# (the Action API's own URLs are JSON endpoints, not useful to click).
# Confirmed live: https://opendata.gov.nt.ca/dataset/<name>,
# .../organization/<name>, and .../group/<name> all 200. Unlike
# ckan_federal's {lang}-templated URLs, these have no French variant --
# confirmed live that /fr/dataset/<name> and /dataset/fr/<name> both
# 404 -- so no {lang} placeholder is used here.
DATASET_LANDING_URL = "https://opendata.gov.nt.ca/dataset/"
ORGANIZATION_LANDING_URL = "https://opendata.gov.nt.ca/organization/"
GROUP_LANDING_URL = "https://opendata.gov.nt.ca/group/"


CACHE_TTL_DATASTORE_SECONDS = 15 * 60  # 15m: DataStore-backed data can update daily

# Mirrors ckan_federal/ckan_bc's DATASTORE_ROWS_MAX reasoning: kept far
# below whatever this deployment's own datastore_search ceiling is, for
# agent-facing compactness rather than exposing the raw server limit.
DATASTORE_ROWS_DEFAULT = 20
DATASTORE_ROWS_MAX = 1000
