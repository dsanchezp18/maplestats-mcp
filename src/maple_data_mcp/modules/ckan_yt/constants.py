"""Constants for the Yukon Open Data (CKAN ckan_yt) module.

Base URL and the `{"help", "success", "result"}` envelope confirmed
live this session directly against
https://open.yukon.ca/api/3/action/package_search?q=mining&rows=1 --
the standard CKAN Action API 3 shape
(https://docs.ckan.org/en/latest/api/), not assumed from the federal
portal's behavior. See client.py for the deployment-specific field
quirks found while verifying it. `site_read` returns HTTP 400 on this
deployment (confirmed live) -- package_list/package_search were used
for the initial connectivity check instead.
"""

BASE_URL = "https://open.yukon.ca/api/3/action/"

# No documented per-request rate limit was found on the Yukon Open Data
# API docs; there are no X-RateLimit-* response headers (checked
# directly against package_list). Unlike the federal portal's generic
# robots.txt stub, this deployment's robots.txt
# (https://open.yukon.ca/robots.txt) carries an explicit, non-generic
# "Crawl-Delay: 10" alongside "Disallow: /api/" -- a real signal that
# this host wants slow, deliberate traffic even though it does not
# specifically target API clients (it is aimed at generic web
# crawlers). Combined with this being a much smaller territorial
# government deployment than the federal portal (see MODULE_DESCRIPTION
# for the dataset-count comparison) with less headroom to absorb bursty
# traffic, this module is more conservative than ckan_federal's
# 2.0/5.0 rather than reusing that figure unexamined.
RATE_LIMIT_SOURCE = "ckan-yt"
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
# Tags/groups are this portal's own subject-classification vocabulary
# (unlike the federal portal, which uses neither) -- both share the
# organization roster's 24h TTL for the same reason: the vocabulary
# itself, not its use on any one dataset, is what's being cached.
CACHE_TTL_TAG_LIST_SECONDS = 24 * 60 * 60  # 24h
CACHE_TTL_GROUP_LIST_SECONDS = 24 * 60 * 60  # 24h

# CKAN's own package_search hard cap: a `rows` above this is silently
# truncated to 1000 server-side (confirmed live: rows=5000 returned
# exactly 1000 results, not an error, matching the federal portal's
# identical cap). SEARCH_ROWS_MAX bounds the agent-facing default well
# below that per AGENTS.md's "keep responses compact enough for MCP
# clients" principle. Kept at the same 100-row default/cap as
# ckan_federal even though this catalogue (~3,841 datasets) is far
# smaller -- 100 rows is already a meaningfully large single response
# regardless of total catalogue size, and an agent deciding which
# dataset to open next with ckan_yt_get_dataset rarely needs more than
# a couple dozen hits at once.
SEARCH_ROWS_DEFAULT = 10
SEARCH_ROWS_MAX = 100

# How much of a dataset's `notes` survives into a compact search-result
# row before being truncated with an ellipsis; full text is available
# via ckan_yt_get_dataset.
NOTES_EXCERPT_LENGTH = 300

# Human-browsable dataset/organization/group landing pages, for
# provenance and for handing an agent a link a person can actually open
# (the Action API's own URLs are JSON endpoints, not useful to click).
# {lang} is "en"/"fr" -- confirmed live that
# https://open.yukon.ca/en/dataset/<name> and .../fr/dataset/<name>
# both 200 for a real dataset name, with a genuinely different
# <html lang="..."> attribute on the two responses (the site's UI
# chrome is bilingual). The dataset's own title/notes text does NOT
# change between the two -- confirmed live on "Mining districts - 1M"
# -- since this portal's underlying data is English-only (see
# __init__.py's module docstring). {lang} is kept anyway so a
# French-preferring user still gets French page chrome around the same
# English dataset content, matching this repo's "accept lang, document
# when it has no data-level effect" convention (see boc_'s tools).
DATASET_LANDING_URL = "https://open.yukon.ca/{lang}/dataset/"
ORGANIZATION_LANDING_URL = "https://open.yukon.ca/{lang}/organization/"
GROUP_LANDING_URL = "https://open.yukon.ca/{lang}/group/"
