"""Constants for the BC Stats Excel module.

Verified live on 2026-10-01 against catalogue.data.gov.bc.ca. The `bc-stats`
organization has 99 datasets; 65 of their resources are `.xlsx` files (some
are tagged format `other`, so files are recognised by URL, not by `format`).
Licences by dataset: Open Government Licence - British Columbia (37),
Statistics Canada Open Licence (52, StatCan-derived tables), Open Government
Licence - Canada (7), Access Only (3, geographic layers, no Excel). Files sit
at /dataset/<id>/resource/<id>/download/<name>.xlsx on the catalogue host and
download directly (no redirect). robots.txt disallows /api/ and sets
Crawl-Delay 10 for all agents; discovery goes through the shipped CKAN
helper (its own `ckan-bc` bucket) and file downloads wait 10 s between
requests.

The catalogue's `datastore_active` flag is not reliable for these files: two
of the five .xlsx resources flagged true (LFS earnings and employment
trends, BC population projections) answer 404 "Resource was not found" from
datastore_search, so the flag is reported as the catalogue states it and
nothing here depends on it.
"""

from maplestats_mcp.modules.ckan.constants import PORTALS

PORTAL = "bc"
ORGANIZATION = "bc-stats"
DOMAIN = "catalogue.data.gov.bc.ca"
SITE = f"https://{DOMAIN}"
ORGANIZATION_URL = f"{SITE}/organization/{ORGANIZATION}"
DOWNLOAD_PATH_MARKER = "/download/"
CKAN_PORTAL = PORTALS[PORTAL]

RATE_LIMIT_SOURCE = "bc-stats-files"
RATE_LIMIT_PER_SECOND = 0.1
RATE_LIMIT_CAPACITY = 2.0

CACHE_TTL_LIST_SECONDS = 6 * 60 * 60
CACHE_TTL_FILE_SECONDS = 6 * 60 * 60

# The largest BC Stats workbook is 32 MB (LFS median wages, bilingual); only
# the raw bytes are kept and one requested sheet is parsed per call.
MAX_FILE_BYTES = 40 * 1024 * 1024
MAX_ROWS_PER_SHEET = 20000
ROWS_LIMIT_DEFAULT = 50
ROWS_LIMIT_MAX = 500
FILES_LIMIT_DEFAULT = 100
FILES_LIMIT_MAX = 200
PAGE_SIZE = 100

PROVENANCE_SOURCE = "bc-stats"
