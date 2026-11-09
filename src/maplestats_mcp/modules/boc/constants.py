"""Constants for the Bank of Canada Valet API module.

Base URL and endpoint shapes confirmed live against
https://www.bankofcanada.ca/valet/ this session (see client.py's module
docstring for the full list of what was verified).
"""

BASE_URL = "https://www.bankofcanada.ca/valet/"

# The same Valet API on the Bank's French domain returns every label and
# description in French (series, groups, observations) and its own error
# messages in French ("Série X non valide."), with identical JSON shapes
# and codes (checked live 2026-10-04). The English domain has no language
# parameter: `?lang=fr` is ignored on /series and rejected on
# /observations, so the domain is the only way to get French text.
BASE_URL_FR = "https://www.banqueducanada.ca/valet/"

# Valet publishes no numeric rate-limit figure in its docs
# (https://www.bankofcanada.ca/valet/docs), and a live response to
# /valet/series/FXUSDCAD/json and /valet/lists/series/json carried no
# X-RateLimit-*/Retry-After style header (checked this session) - so
# there is nothing to read a real number from. 10 req/s matches this
# project's shared conservative default (shared/rate_limiter.py's
# get_limiter signature) and is well under StatCan WDS's documented
# 25 req/s, which is a reasonable ceiling for another Government of
# Canada JSON API with similar traffic characteristics.
RATE_LIMIT_SOURCE = "boc"
RATE_LIMIT_PER_SECOND = 10.0
RATE_LIMIT_CAPACITY = 10.0

# /lists/series/json and /lists/groups/json are large, mostly-static
# inventories (15,928 series / 2,538 groups measured live this
# session) - Valet's own Cache-Control on these responses is only
# max-age=30 (a CDN-level hint, not a signal the underlying inventory
# changes that often), so a much longer client-side TTL is appropriate.
CACHE_TTL_LISTS_SECONDS = 24 * 60 * 60  # 24h

# Series/group detail (label/description) changes rarely.
CACHE_TTL_DETAIL_SECONDS = 24 * 60 * 60  # 24h

# Observations update at most once per business day for any series
# covered here (FX, policy rate, CPI, commodity prices).
CACHE_TTL_OBSERVATIONS_SECONDS = 60 * 60  # 1h

# Response sizes measured live 2026-10-03: the full series inventory is
# about 2.2 MB and the group inventory about 1 MB, and FX_RATES_DAILY with no
# date window about 1.2 MB. Lists default to a page, searches to the top
# matches, and observations keep the most recent dates within a byte budget.
SEARCH_LIMIT_DEFAULT = 25
SEARCH_LIMIT_MAX = 200
LIST_LIMIT_DEFAULT = 50
LIST_LIMIT_MAX = 1000
OBSERVATIONS_MAX_BYTES = 200_000
# With no date window or recent_* argument, only this many of the newest dates come
# back (about two months of a daily series, two and a half years of a monthly one):
# a whole history is rarely the question, and it cost a model up to 200 KB to read.
# Changed from "as many as fit in OBSERVATIONS_MAX_BYTES" on 2026-11-08.
NO_WINDOW_DATES = 30

# Series status (active or discontinued) needs each series' newest date: one
# observations?recent=1 request per STATUS_CHUNK names (Valet takes comma-joined
# names; 50 keeps the URL under about 2,000 characters), and at most
# STATUS_CHECK_MAX series per listing, so a search costs at most four requests.
STATUS_CHUNK = 50
STATUS_CHECK_MAX = 200
