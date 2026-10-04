"""Constants for the Open Alberta file reader.

Verified live on 2026-10-02 against open.alberta.ca (CKAN):

- 3,018 datasets of type `opendata`; 3,016 are under "Open Government
  Licence - Alberta" (license_id `OGLA`). About 700 have an XLSX resource,
  221 a CSV and 120 an XLS. The DataStore has no active resources
  (`datastore_active` is false on every resource sampled), so the files are
  the only route to the rows.
- Files sit at /dataset/<dataset id>/resource/<resource id>/download/<name>
  on the portal host and download directly (HTTP 200, no redirect). Some
  resources are links to other hosts (for example regionaldashboard.alberta.ca
  exports with no file extension); those are listed but not read.
- robots.txt disallows /api/ and sets `Crawl-Delay: 10` for all agents; the
  download paths are allowed. The owner decided that CKAN API use with
  pacing is acceptable (the Yukon precedent), so discovery goes through the
  CKAN Action API and both API calls and file downloads share one bucket of
  one request per 10 seconds.
- The OGL-Alberta text relied on: "worldwide, royalty-free, perpetual,
  non-exclusive licence to use the Information, including for commercial
  purposes", with the attribution statement below.
"""

DOMAIN = "open.alberta.ca"
SITE = f"https://{DOMAIN}"
API_BASE = f"{SITE}/api/3/action/"
DATASET_URL = SITE + "/dataset/{name}"
LICENCE_URL = f"{SITE}/licence"

DOWNLOAD_PATH_PATTERN = (
    r"^/dataset/(?P<dataset>[0-9a-f-]{36})/resource/(?P<resource>[0-9a-f-]{36})/download/[^/]+$"
)
READABLE_SUFFIXES = (".xlsx", ".xls", ".csv")
FORMATS = ("xlsx", "xls", "csv")

OGL_LICENCE_ID = "OGLA"
OGL_ATTRIBUTION = "Contains information licensed under the Open Government Licence – Alberta."

# One request per 10 seconds, API and downloads together: the portal's
# robots.txt crawl delay. Capacity 1 lets the first call go at once.
RATE_LIMIT_SOURCE = "ab-opendata"
RATE_LIMIT_PER_SECOND = 0.1
RATE_LIMIT_CAPACITY = 1.0

CACHE_TTL_API_SECONDS = 6 * 60 * 60
CACHE_TTL_FILE_SECONDS = 6 * 60 * 60
# An unknown dataset name is remembered this long, so asking again does not
# wait 10 seconds for the paced API to say no again.
CACHE_TTL_MISSING_SECONDS = 5 * 60

# Biggest files seen: a 10.4 MB wildfire CSV and 2.3 MB traffic workbooks.
# Only raw bytes are cached; each call scans the file once.
MAX_FILE_BYTES = 40 * 1024 * 1024
NOTES_EXCERPT_CHARS = 300

DATASETS_LIMIT_DEFAULT = 20
DATASETS_LIMIT_MAX = 50
ORGANIZATIONS_FACET_LIMIT = 200
ROWS_LIMIT_DEFAULT = 50
ROWS_LIMIT_MAX = 1000

PROVENANCE_SOURCE = "open-alberta"
