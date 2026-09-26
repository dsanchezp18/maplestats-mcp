"""Constants for the Canadian Grain Commission statistics files (checked 2026-09-26).

Both hosts answer: `grainscanada.gc.ca` and `www.grainscanada.gc.ca`. The
www host is used because the site's own links point there. Both fail the
TLS handshake now and then (SSL_ERROR_SYSCALL from curl, ConnectError from
httpx), with either ALPN offer: 3 of 15 fresh connections to the bare host
with http2=False and 2 of 5 with http2=True on 2026-09-26, and the www host
failed once in a run of curl requests as well. It is not the ALPN block
StatCan has; a retry succeeds, so the client retries connection failures
more than the shared default (see client._download).
"""

from __future__ import annotations

HOST = "www.grainscanada.gc.ca"
BASE_EN = f"https://{HOST}/en/grain-research/statistics/"
BASE_FR = f"https://{HOST}/fr/recherche-donnees/statistiques/"

WEEKLY_PAGE_EN = BASE_EN + "grain-statistics-weekly/"
WEEKLY_PAGE_FR = BASE_FR + "statistique-hebdomadaire/"
EXPORTS_PAGE_EN = BASE_EN + "exports-grain-licensed-facilities/"
EXPORTS_PAGE_FR = BASE_FR + "exportations/"

# Monthly exports from licensed facilities, January 2013 onward. The English
# and French files have the same rows in a different order.
EXPORTS_URL_EN = EXPORTS_PAGE_EN + "csv/exports.csv"
EXPORTS_URL_FR = EXPORTS_PAGE_FR + "csv/exportation.csv"

# Grain Statistics Weekly CSVs exist from crop year 2013-14 (listed on the
# federal CKAN record); the CGC archive page lists 2017-18 onward.
FIRST_CROP_YEAR = 2013
# English files up to 2017-18 sit in a csv/ subfolder; French paths use a
# two-digit crop year ("26-27") for every year.
LAST_CSV_SUBFOLDER_YEAR = 2017

# The crop year runs August 1 to July 31. The CGC is in Winnipeg.
CROP_YEAR_START_MONTH = 8
TIMEZONE = "America/Winnipeg"

RATE_LIMIT_SOURCE = "cgc"
RATE_LIMIT_PER_SECOND = 1.0
RATE_LIMIT_CAPACITY = 2.0

# A full crop year of the weekly CSV is about 25 MB (2024-25: 24.7 MB,
# 219,182 rows); the exports file is about 4 MB.
MAX_FILE_BYTES = 60 * 1024 * 1024
DOWNLOAD_TIMEOUT_SECONDS = 120.0
# Extra passes over the shared client's own 3 attempts, for the handshake
# failures described above.
DOWNLOAD_PASSES = 3

# The weekly file is replaced on Thursdays; past crop years change rarely.
CURRENT_WEEKLY_TTL_SECONDS = 3 * 60 * 60
PAST_WEEKLY_TTL_SECONDS = 7 * 24 * 60 * 60
EXPORTS_TTL_SECONDS = 12 * 60 * 60

ROWS_DEFAULT = 200
ROWS_MAX = 5000
VALUES_LISTED_MAX = 60

LICENCE = "Open Government Licence - Canada"
