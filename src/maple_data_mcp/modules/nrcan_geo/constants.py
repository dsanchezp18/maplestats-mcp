"""Constants for NRCan's Geolocator and geographical names APIs.

Confirmed live 2026-09-23:
- Geolocator: GET https://geolocator.api.geo.ca/?q=..&lang=en|fr returns
  a JSON list of {key, name, province, category, lat, lng, bbox, tag};
  `key` names the backing source (nominatim, locate, fsa, geonames, ...).
- Geonames: GET .../geoname/{en|fr}/geonames.json with q, lat/lon/radius
  (km), bbox (w,s,e,n), province (SGC code, e.g. 48), concise (e.g. CITY,
  LAKE), num. Items carry codes only; `codes/concise.json` gives the
  terms. A malformed parameter answers HTTP 404 with a Tomcat HTML page.
"""

GEOLOCATOR_URL = "https://geolocator.api.geo.ca/"
GEONAMES_ROOT = "https://geogratis.gc.ca/services/geoname/{lang}/"

RATE_LIMIT_SOURCE = "nrcan-geo"
RATE_LIMIT_PER_SECOND = 3.0
RATE_LIMIT_CAPACITY = 5.0

CACHE_TTL_LOOKUP_SECONDS = 24 * 60 * 60
CACHE_TTL_CODES_SECONDS = 7 * 24 * 60 * 60

LIMIT_DEFAULT = 10
LIMIT_MAX = 100
RADIUS_MAX_KM = 500

PROVINCE_CODES = {
    "NL": "10",
    "PE": "11",
    "NS": "12",
    "NB": "13",
    "QC": "24",
    "ON": "35",
    "MB": "46",
    "SK": "47",
    "AB": "48",
    "BC": "59",
    "YT": "60",
    "NT": "61",
    "NU": "62",
}
