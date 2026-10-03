"""Constants for the National Forestry Database (checked live 2026-10-02).

Plain http on purpose: from the build machine nfdp.ccfm.org accepted port 80
(HTTP 200) while port 443 timed out on every attempt (curl and httpx, three
tries over several minutes), and the site's own pages link its files with
`http://nfdp.ccfm.org/...`. If the host later redirects to https the client
follows that redirect (see client._download).
"""

from __future__ import annotations

BASE_URL = "http://nfdp.ccfm.org"
PAGE_EN = f"{BASE_URL}/en/download.php"
PAGE_FR = f"{BASE_URL}/fr/download.php"

RATE_LIMIT_SOURCE = "nfd"
RATE_LIMIT_PER_SECOND = 2.0
RATE_LIMIT_CAPACITY = 4.0

# Largest CSV on 2026-10-02 is 3.9 MB (22,945 rows).
MAX_FILE_BYTES = 30 * 1024 * 1024
DOWNLOAD_TIMEOUT_SECONDS = 90.0

# Tables change a few times a year (dictionaries are dated April to June).
CATALOGUE_TTL_SECONDS = 6 * 60 * 60
TABLE_TTL_SECONDS = 12 * 60 * 60

ROWS_DEFAULT = 200
ROWS_MAX = 5000
VALUES_LISTED_MAX = 60

LICENCE = "Open Government Licence - Canada, version 2.0"
SOURCE_NAME = "national-forestry-database"

# Identical in all 25 data dictionaries (English and French sheets compared
# on 2026-10-02). Codes are case-sensitive: "E" and "e", "U" and "u" differ.
QUALIFIERS_EN = {
    "a": "actual figures",
    "E": "estimated by Statistics Canada or the Canadian Forest Service",
    "e": "estimated by provincial or territorial forestry agency",
    "n": "figures not appropriate or not applicable",
    "p": "preliminary figures",
    "r": "revised figures",
    "s": "amount too small to be expressed",
    "U": "figures not available and are known to be large relative to the total for the province",
    "u": "figures not available and are known to be very small relative to the total for the province",
}
QUALIFIERS_FR = {
    "a": "valeur actuelle",
    "E": "estimation par Statistique Canada ou le Service canadien des forêts",
    "e": "estimation par les organismes forestiers provinciaux ou territoriaux",
    "n": "n'ayant pas lieu de figurer",
    "p": "nombres provisoires",
    "r": "nombres rectifiés",
    "s": "nombres infimes",
    "U": "nombres non disponibles et reconnus significatifs par rapport au total pour la province",
    "u": "nombres non disponibles et reconnus comme étant minimes par rapport au total",
}

# Yukon is coded "YK" in the scarification table and "YT" in every other.
ISO_ALIASES = {"YK": "YT"}
