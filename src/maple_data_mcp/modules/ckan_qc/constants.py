"""Constants for the Quebec Open Data (CKAN QC) module.

Base URL, envelope shape, and every field-level claim in this file were
confirmed live this session directly against
https://www.donneesquebec.ca/recherche/api/3/action/... -- not assumed
from the federal deployment or generic CKAN docs. See client.py for
the full set of deployment-specific quirks found while verifying it.

Base URL note: the catalogue's Action API lives under a `/recherche/`
path segment, not at the domain root
(https://www.donneesquebec.ca/recherche/api/3/action/), confirmed by a
successful package_search there returning
{"success": true, "result": {"count": 1610, ...}}. A bare
https://www.donneesquebec.ca/api/3/action/... call also happened to
proxy the same backend during this session's live check (200, correct
data), but robots.txt explicitly disallows crawling both `/api/` and
`/recherche/api/`, and only `/recherche/` is what the site's own UI and
every `help` URL in a response envelope points back at -- stick with
`/recherche/` as the documented, intended path rather than relying on
what may just be an incidental proxy alias at the root.
"""

BASE_URL = "https://www.donneesquebec.ca/recherche/api/3/action/"

# No documented per-request rate limit was found on donneesquebec.ca --
# no API-specific docs page was located, and no X-RateLimit-* response
# headers were present on any call made this session. robots.txt does
# carry a real signal, though, and it is more specific than the federal
# portal's: it explicitly disallows crawling both `/api/` and
# `/recherche/api/` and states "Crawl-Delay: 10" for the whole site
# (https://www.donneesquebec.ca/robots.txt, checked live this session).
# This is a much smaller catalogue than federal's (~1,600 datasets vs.
# ~48,000), but with no positive evidence of a *higher* tolerance, stay
# at least as conservative as ckan_federal's 2/s rather than assume a
# smaller portal can take more load.
RATE_LIMIT_SOURCE = "ckan-qc"
RATE_LIMIT_PER_SECOND = 1.0
RATE_LIMIT_CAPACITY = 3.0

CACHE_TTL_SEARCH_SECONDS = 10 * 60  # 10m: search results/catalogue change often
CACHE_TTL_PACKAGE_SECONDS = 60 * 60  # 1h
# An individual organization's title/description is at least as stable
# as the roster it's drawn from, so organization_show shares the same
# 24h TTL as organization_list rather than the shorter default below.
CACHE_TTL_ORGANIZATION_LIST_SECONDS = 24 * 60 * 60  # 24h: org roster is stable
CACHE_TTL_ORGANIZATION_SECONDS = CACHE_TTL_ORGANIZATION_LIST_SECONDS
CACHE_TTL_RESOURCE_SECONDS = 60 * 60  # 1h
CACHE_TTL_LICENSE_LIST_SECONDS = 7 * 24 * 60 * 60  # 7d: licenses rarely change
# The 12 thematic groups are a small, curated, essentially static set
# (confirmed live via group_list(all_fields=true)) -- share the org
# roster's 24h TTL rather than the shorter search default.
CACHE_TTL_GROUP_LIST_SECONDS = 24 * 60 * 60  # 24h
# Free-text tags are added by publishers routinely (new dataset ->
# new/duplicate tag spelling, confirmed by the noisy live tag_list
# sample) -- shorter TTL than the group list's stable set.
CACHE_TTL_TAG_LIST_SECONDS = 60 * 60  # 1h

# Unlike the federal deployment (confirmed there: rows=5000 silently
# truncated to 1000), no hard rows cap was found on this portal --
# package_search?rows=5000&q= returned all 1,610 live catalogue
# datasets, the true total, with no truncation. SEARCH_ROWS_MAX stays
# conservative anyway, for the same agent-facing-compactness reason
# AGENTS.md gives for federal, not because this server enforces a
# lower cap of its own.
SEARCH_ROWS_DEFAULT = 10
SEARCH_ROWS_MAX = 100

# How much of a dataset's `notes` survives into a compact search-result
# row before being truncated with an ellipsis; full text is available
# via ckan_qc_get_dataset.
NOTES_EXCERPT_LENGTH = 300

# The tag namespace is large (4,402 free-text tags live, confirmed via
# an unfiltered tag_list call) and genuinely uncontrolled: publishers
# type their own casing/spelling, so "Transport", "TRANSPORT",
# "Transport.", and "transport routier" all coexist as distinct tags on
# the same topic (confirmed live). Returning the whole list by default
# would be neither compact nor useful, so TAGS_LIST_MAX caps an
# unfiltered ckan_qc_list_tags call; the tool's `query` parameter
# (passed straight through to tag_list's own substring filter,
# confirmed live to narrow results server-side) is the intended way to
# actually search this namespace.
TAGS_LIST_MAX = 200

# Human-browsable dataset/organization/group landing pages, for
# provenance and for handing an agent a link a person can actually open
# (the Action API's own URLs are JSON endpoints). Confirmed live that
# https://www.donneesquebec.ca/recherche/dataset/<name>,
# .../recherche/organization/<name>, and .../recherche/group/<name> all
# return HTTP 200 for real ids. Unlike ckan_federal's DATASET_LANDING_URL,
# there is no {lang} placeholder here: confirmed live that
# https://www.donneesquebec.ca/en/recherche/dataset/<name> 404s -- this
# portal has no English-language URL variant of its catalogue pages,
# consistent with the French-monolingual finding in this module's
# __init__.py docstring.
DATASET_LANDING_URL = "https://www.donneesquebec.ca/recherche/dataset/"
ORGANIZATION_LANDING_URL = "https://www.donneesquebec.ca/recherche/organization/"
GROUP_LANDING_URL = "https://www.donneesquebec.ca/recherche/group/"


CACHE_TTL_DATASTORE_SECONDS = 15 * 60  # 15m: DataStore-backed data can update daily

# Mirrors ckan_federal/ckan_bc's DATASTORE_ROWS_MAX reasoning: kept far
# below whatever this deployment's own datastore_search ceiling is, for
# agent-facing compactness rather than exposing the raw server limit.
DATASTORE_ROWS_DEFAULT = 20
DATASTORE_ROWS_MAX = 1000
