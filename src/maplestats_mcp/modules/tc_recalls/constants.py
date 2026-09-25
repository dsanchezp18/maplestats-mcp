"""Constants for Transport Canada's vehicle recall API.

Confirmed live 2026-09-23:
- Search: /recall[/make-name/{make}][/model-name/{model}][/year-range/{a}-{b}]
  returns 25 rows by default, oldest first; `limit` (up to at least
  5000) and 1-based `page` page through results.
- Summary: /recall-summary/recall-number/{n} returns one row per affected
  model and year, with paired `_ETXT`/`_FTXT` English/French fields.
- Every response is {"ResultSet": [[{"Name", "Value": {"Type", "Literal"}}]]};
  no match is an empty ResultSet, not a 404. Dates are "M/D/YYYY h:mm:ss AM".
"""

BASE_URL = "https://data.tc.gc.ca/v1.3/api/{lang}/vehicle-recall-database/"

RATE_LIMIT_SOURCE = "tc-recalls"
RATE_LIMIT_PER_SECOND = 3.0
RATE_LIMIT_CAPACITY = 5.0

CACHE_TTL_SECONDS = 6 * 60 * 60

LIMIT_DEFAULT = 50
LIMIT_MAX = 500
