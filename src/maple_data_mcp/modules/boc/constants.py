"""Constants for the Bank of Canada Valet API module.

Base URL and endpoint shapes confirmed live against
https://www.bankofcanada.ca/valet/ this session (see client.py's module
docstring for the full list of what was verified).
"""

BASE_URL = "https://www.bankofcanada.ca/valet/"

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
