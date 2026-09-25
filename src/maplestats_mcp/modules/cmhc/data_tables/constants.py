"""Constants for CMHC's "Data Tables" document catalogue.

A separate platform from the rest of modules/cmhc/ (HMIP's legacy
ASP.NET MVC/Kendo app): this is www.cmhc-schl.gc.ca's Sitecore-managed
content site, confirmed live this session to publish official per-
edition Excel table downloads under
/professionals/housing-markets-data-and-research/housing-data/
data-tables/<category>/<table-slug>, resolved through a real Sitecore
custom API controller (api/Sitecore/PubsAndReports/GetFileDetails) --
see client.py's module docstring for the full confirmed request/
response shapes.
"""

BASE_URL = "https://www.cmhc-schl.gc.ca"
DATA_TABLES_PATH = "/professionals/housing-markets-data-and-research/housing-data/data-tables"
GET_FILE_DETAILS_URL = f"{BASE_URL}/api/Sitecore/PubsAndReports/GetFileDetails"

# Confirmed live this session: exactly these three top-level categories
# exist under DATA_TABLES_PATH (the parent index page 301-redirects and
# lists only these three). "canadian-housing-survey-data-tables" is a
# landing page that cross-links the other two categories rather than
# hosting its own leaf tables -- list_tables returns an empty list for
# it rather than guessing at an unconfirmed URL structure.
KNOWN_CATEGORIES = (
    "rental-market",
    "household-characteristics",
    "canadian-housing-survey-data-tables",
)

# No published rate limit; same conservative default as the rest of
# modules/cmhc/ (a legacy-platform-adjacent government site).
RATE_LIMIT_SOURCE = "cmhc-dt"
RATE_LIMIT_PER_SECOND = 2.0
RATE_LIMIT_CAPACITY = 5.0

# A category's table listing and a table's own geography/edition
# options change rarely (new editions are added a few times a year).
CACHE_TTL_LISTING_SECONDS = 24 * 60 * 60  # 24h
CACHE_TTL_TABLE_SECONDS = 24 * 60 * 60  # 24h

# A resolved download link for one geography+edition combination never
# changes once published (it is a specific historical file) -- cached
# long, same reasoning as CACHE_TTL_TABLE_SECONDS.
CACHE_TTL_DOWNLOAD_SECONDS = 24 * 60 * 60  # 24h
