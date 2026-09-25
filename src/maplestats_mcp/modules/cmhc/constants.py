"""Constants for CMHC's Housing Market Information Portal (HMIP).

Base URL and endpoint shapes confirmed live against
https://www03.cmhc-schl.gc.ca/hmip-pimh/ this session (see client.py's
module docstring for the full list of what was verified). Server
identifies itself as IIS/7.5, ASP.NET MVC 4 -- a legacy platform with
no published API docs; every endpoint here was found by reading the
site's own rendered HTML/JS, then cross-checked against the
independently-maintained `mountainMath/cmhc` R package (CRAN, actively
updated) for corroboration.
"""

BASE_URL = "https://www03.cmhc-schl.gc.ca/hmip-pimh"

# No published rate limit. This is a legacy IIS 7.5 box (not a modern
# cloud API), so this project's more conservative default is used --
# the same reasoning already applied to the ArcGIS Hub and Socrata
# modules (2 req/s) rather than the 10 req/s used for modern JSON APIs
# like Bank of Canada Valet or MSC GeoMet.
RATE_LIMIT_SOURCE = "cmhc"
RATE_LIMIT_PER_SECOND = 2.0
RATE_LIMIT_CAPACITY = 5.0

# The category taxonomy and province list are small, mostly-static
# inventories (confirmed live) -- cached like boc's series/group lists.
CACHE_TTL_CATEGORIES_SECONDS = 24 * 60 * 60  # 24h
CACHE_TTL_PROVINCES_SECONDS = 24 * 60 * 60  # 24h

# A category's valid ColumnField/RowField combinations change rarely.
CACHE_TTL_TABLE_OPTIONS_SECONDS = 24 * 60 * 60  # 24h

# CMHC's surveys update monthly/quarterly/annually at most -- a short
# TTL only smooths a caller re-running the same query moments apart.
CACHE_TTL_TABLE_DATA_SECONDS = 6 * 60 * 60  # 6h

# Confirmed live: the CSV export declares no charset and is NOT valid
# UTF-8 or strict ISO-8859-1 (a byte 0x97 em-dash in a table title
# decodes to an unprintable C1 control character under true latin-1,
# but to U+2014 EM DASH under cp1252) -- this is a Windows/IIS server,
# so cp1252 (Windows-1252) is the correct encoding, not "latin-1" as
# one community reference package's own code comment claims.
CSV_ENCODING = "cp1252"

# Confirmed live: value cells using these tokens are not numeric data
# (suppressed for confidentiality, not statistically reliable, or not
# applicable) - "n/a" added after cross-checking the reference R
# package's own parse_numeric() helper, which lists it alongside "**"/
# "++".
SUPPRESSED_VALUE_TOKENS = frozenset({"**", "++", "n/a"})

# Confirmed live (and matching the reference R package's own
# parse_numeric()): a bare "-" is CMHC's own notation for a real,
# counted zero (e.g. zero housing starts in a small market that
# period), not a missing/suppressed value - kept distinct from
# SUPPRESSED_VALUE_TOKENS so it parses to 0.0, not None.
NIL_VALUE_TOKENS = frozenset({"-"})
