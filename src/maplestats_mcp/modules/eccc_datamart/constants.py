"""Constants for the ECCC Data Catalogue file tree.

Verified live on 2026-10-03 against data-donnees.az.ec.gc.ca:

- `GET /api/path_contents?path=/<folder>` returns
  `{"path_catalogue_id", "path_parent", "path_contents": [...]}`; each entry has
  `name`, `path` (relative, no leading slash), `is_directory`, `last_modified`
  (a date), `display_name` ({"en", "fr"}, often both null) and
  `content_length` as rounded text ("36 MiB", "3 KiB", "0 B" for folders), so
  exact byte counts are only known on download. An unknown path answers 404
  with the JSON string "Path not found."; a file path answers 200 with that one
  file as the only entry. HEAD requests answer 404, so only GET is used.
- `GET /api/file?path=/<file>` answers 302 to a signed blob URL on the same
  host (/public/...), which serves the bytes with Content-Length.
- Neither endpoint is documented; both are the ones the catalogue's web page
  (a single-page app) calls. A `path_metadata` endpoint also used by that page
  answered HTTP 500 or did not answer, so it is not used.
- `path_catalogue_id` is the open.canada.ca dataset id of the folder.
- No rate limit is published; this module paces itself at 4 requests per
  second.
- The root `license-en.txt` is the Open Government Licence - Canada 2.0
  (Windows-1252 text): worldwide, royalty-free, perpetual, non-exclusive,
  commercial use allowed, attribution required.
- Encodings differ by file: the NPRI single-year CSVs are Windows-1252, the
  GHGRP CSV is UTF-8 with a byte-order mark, the GHGRP read-me CSVs are
  Windows-1252.
"""

DOMAIN = "data-donnees.az.ec.gc.ca"
SITE = f"https://{DOMAIN}"
LISTING_URL = f"{SITE}/api/path_contents"
FILE_URL = f"{SITE}/api/file"
BROWSE_URL = SITE + "/data{path}?lang={lang}"
CATALOGUE_URL = "https://open.canada.ca/data/{lang}/dataset/{id}"
LICENCE_FILE = "/license-en.txt"

RATE_LIMIT_SOURCE = "eccc-datamart"
RATE_LIMIT_PER_SECOND = 4.0
RATE_LIMIT_CAPACITY = 4.0
INDEX_CONCURRENCY = 4

CACHE_TTL_LISTING_SECONDS = 6 * 60 * 60
CACHE_TTL_INDEX_SECONDS = 24 * 60 * 60
CACHE_TTL_FILE_SECONDS = 6 * 60 * 60

# The NPRI single-year CSVs are 34-38 MiB; the bulk all-years files are 50-375 MiB.
MAX_FILE_BYTES = 40 * 1024 * 1024
READABLE_SUFFIXES = (".csv", ".tsv", ".txt", ".xlsx", ".xls")
ARCHIVE_SUFFIXES = (".zip", ".gz", ".7z", ".tar", ".tgz")
DOC_PATTERN = r"(?i)(read ?me|lisez|dictionar|diction|codebook|modification|notes?\b|metadata)"
DOC_EXCERPT_MAX_BYTES = 200 * 1024
DOC_EXCERPT_CHARS = 4000
DOC_EXCERPTS_MAX = 2

# Depth 3 is /<topic>/<function>/<dataset>: 60 listings, 510 folders on 2026-10-03.
INDEX_DEPTH = 3

ENTRIES_LIMIT_DEFAULT = 200
ENTRIES_LIMIT_MAX = 1000
SEARCH_LIMIT_DEFAULT = 20
SEARCH_LIMIT_MAX = 100
ROWS_LIMIT_DEFAULT = 50
ROWS_LIMIT_MAX = 1000

NPRI_FOLDER = (
    "/substances/plansreports/reporting-facilities-pollutant-release-and-transfer-data/"
    "single-year-data-tables-by-facility-releases-transfers-and-disposals"
)
NPRI_FILE_PATTERN = r"^NPRI-INRP_DataDonn.es_(?P<year>\d{4})\.csv$"
NPRI_BULK_FOLDER = (
    "/substances/plansreports/reporting-facilities-pollutant-release-and-transfer-data/"
    "bulk-data-files-for-all-years-releases-disposals-transfers-and-facility-locations"
)
GHGRP_FOLDER = (
    "/substances/monitor/greenhouse-gas-reporting-program-ghgrp-facility-greenhouse-gas-ghg-data"
)
GHGRP_FILE_PATTERN = r"^PDGES-GHGRP-GHGEmissionsGES-\d{4}-Present\.csv$"

OGL_ATTRIBUTION = "Contains information licensed under the Open Government Licence – Canada."
LICENCE_TEXT = (
    "Open Government Licence - Canada (https://open.canada.ca/en/open-government-licence-"
    "canada), as stated in the catalogue's license-en.txt: commercial use allowed; "
    f"attribution required: '{OGL_ATTRIBUTION}'"
)

PROVENANCE_SOURCE = "eccc-data-catalogue"
UNDOCUMENTED_NOTE = (
    "Listings and files come from the catalogue's api/path_contents and api/file "
    "endpoints, which its web page uses; they are undocumented and may change."
)
