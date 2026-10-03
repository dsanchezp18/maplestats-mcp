"""Constants for the MSC GeoMet OGC API - Coverages tools.

Checked live against https://api.weather.gc.ca on 2026-10-03: 49 of the
server's coverage collections have ids starting with `climate:` (CMIP5,
CanDCS-U6, DCS, climate indices, SPEI-1/3/12, CanGRD). The server also
publishes `weather:rdpa:*` and `weather:cansips:*` coverages, but those
answer with a projected grid whose CRS id is "None" (RDPA) or with range
names that differ from the collection schema (CanSIPS: `TMP` for
`AirTemp_AGL-2m`), so these tools read the `climate:` family only.
"""

from maplestats_mcp.modules.eccc import constants as eccc_constants

BASE_URL = eccc_constants.BASE_URL
RATE_LIMIT_SOURCE = eccc_constants.RATE_LIMIT_SOURCE
RATE_LIMIT_PER_SECOND = eccc_constants.RATE_LIMIT_PER_SECOND
RATE_LIMIT_CAPACITY = eccc_constants.RATE_LIMIT_CAPACITY

COLLECTION_PREFIX = "climate:"

# Collection metadata and schemas change with dataset releases, not daily.
CACHE_TTL_CATALOGUE_SECONDS = 24 * 60 * 60
# Projections are static datasets; a repeated identical request is safe to
# reuse for a day.
CACHE_TTL_COVERAGE_SECONDS = 24 * 60 * 60

# Measured live: a CanDCS-U6 point request took 1 to 16 s (the slow ones are
# the first request for a variable); a whole-Canada single-year request was
# 6.2 MB in 1.7 s.
COVERAGE_TIMEOUT_SECONDS = 60.0
CATALOGUE_CONCURRENCY = 8
COVERAGE_CONCURRENCY = 4

# One upstream request is made per variable x scenario x percentile x
# season x averaging period (and per time step for CanGRD, whose responses
# carry no time axis). The server rejects several variables in one request
# for the CMIP5 collections (HTTP 500), so variables are never combined.
MAX_REQUESTS = 40

# The server has no cap of its own: a whole-Canada CanDCS-U6 year is 544,680
# grid values. Requests whose estimated size exceeds this are refused before
# any call is made.
MAX_ESTIMATED_VALUES = 250_000

ROWS_DEFAULT = 1000
ROWS_MAX = 10_000
SEARCH_LIMIT_DEFAULT = 20

# Environment and Climate Change Canada Data Services End-use Licence,
# version 2.1.1 (https://eccc-msc.github.io/open-data/licence/readme_en/),
# read 2026-10-03: free use including commercial, attribution required.
ECCC_LICENCE = (
    "Data Source: Environment and Climate Change Canada. Licensed under the "
    "Environment and Climate Change Canada Data Services End-use Licence "
    "(https://eccc-msc.github.io/open-data/licence/readme_en/): use, including "
    "commercial use, is free; the source must be acknowledged and adapted data "
    "must not be presented as endorsed by ECCC."
)
ECCC_LICENCE_FR = (
    "Source des données : Environnement et Changement climatique Canada. Utilisé "
    "selon la Licence d'utilisation finale des services de données d'Environnement "
    "et Changement climatique Canada "
    "(https://eccc-msc.github.io/open-data/licence/readme_fr/) : utilisation libre, "
    "y compris commerciale; la source doit être mentionnée et les données adaptées "
    "ne doivent pas être présentées comme approuvées par ECCC."
)
