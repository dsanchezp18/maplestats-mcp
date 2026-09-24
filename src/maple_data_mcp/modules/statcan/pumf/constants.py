"""Constants for StatCan PUMF discovery and codebooks.

Confirmed live 2026-09-24 on seven PUMFs (LFS 71M0001X, Census 98M0001X,
CCHS 82M0013X, SHS 62M0004X, GSS 45-25-0001, EICS 89M0025X, CSWC
14-25-0001): each catalogue page links one or more /n1/pub/ pages whose
.zip links are free, unauthenticated downloads (30 to 534 MB). Codebooks
ship inside the zips as an LFS-style CSV, Stata .dct/.do files, SPSS
_vare/_vale (_varf/_valf in French) files, or, for SHS and CSWC, SAS
label files only. All text files sampled are CP1252.
"""

BASE_URL = "https://www150.statcan.gc.ca"
CATALOGUE_URL = BASE_URL + "/n1/{lang}/catalogue/{number}"
ALLOWED_HOST = "www150.statcan.gc.ca"

RATE_LIMIT_SOURCE = "statcan-pumf"
RATE_LIMIT_PER_SECOND = 2.0
RATE_LIMIT_CAPACITY = 4.0

CACHE_TTL_SECONDS = 24 * 60 * 60
MAX_PUB_PAGES = 6
VARIABLES_DEFAULT = 50
VARIABLES_MAX = 500
VALUES_PER_VARIABLE = 60
TABLE_ROWS_MAX = 500
