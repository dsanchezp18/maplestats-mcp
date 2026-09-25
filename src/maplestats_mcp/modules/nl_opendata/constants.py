"""Constants for the Open Data Newfoundland and Labrador catalogue.

The page IDs, download route, and observed listing sizes were checked live
against opendata.gov.nl.ca. The catalogue does not publish a rate-limit
header or JSON API, so this module uses a conservative per-host limiter.
"""

BASE_URL = "https://opendata.gov.nl.ca/public/opendata/page/"
FILE_DOWNLOAD_URL = "https://opendata.gov.nl.ca/public/opendata/filedownload/"
RATE_LIMIT_SOURCE = "nl-opendata"
RATE_LIMIT_PER_SECOND = 1.0
RATE_LIMIT_CAPACITY = 2.0

CACHE_TTL_LISTING_SECONDS = 10 * 60
CACHE_TTL_DETAIL_SECONDS = 60 * 60
CACHE_TTL_TAGS_SECONDS = 24 * 60 * 60

SEARCH_LIMIT_DEFAULT = 10
SEARCH_LIMIT_MAX = 100
DESCRIPTION_EXCERPT_LENGTH = 300
LICENCE_URL = f"{BASE_URL}?page-id=licence"
