"""Constants for CWFIS (GeoServer WFS + situation-report API)."""

WFS_URL = "https://cwfis.cfs.nrcan.gc.ca/geoserver/ows"
SITREP_URL = "https://api.cwfif.nrcan.gc.ca/situationreports/situationreport"

RATE_LIMIT_SOURCE = "cwfis"
RATE_LIMIT_PER_SECOND = 2.0
RATE_LIMIT_CAPACITY = 5.0
SITREP_RATE_SOURCE = "cwfis-sitrep"

# Layer names confirmed live in GetCapabilities 2026-09-29.
HOTSPOTS_CURRENT = "public:hotspots_last24hrs"
HOTSPOTS_ARCHIVE = "public:hotspots"
PERIMETERS = "public:m3_polygons_current"
STATIONS = "public:firewx_stns_current"
FORECAST = "public:firewx_scribe"
DANGER = "public:fdr_current_shp"
NFDB = "public:NFDB_point"

CACHE_TTL_HOTSPOTS = 10 * 60
CACHE_TTL_LIVE = 30 * 60
CACHE_TTL_FORECAST = 60 * 60
CACHE_TTL_ARCHIVE = 24 * 60 * 60
CACHE_TTL_SITREP = 60 * 60

ROWS_LIMIT_DEFAULT = 20
ROWS_LIMIT_MAX = 1000
SITREP_LIMIT_MAX = 100  # confirmed live: limit > 100 answers HTTP 422
MAX_RADIUS_KM = 200.0

# The hotspot layer also carries US and Mexican detections (agency 'TX', 'MX'...).
CANADIAN_AGENCIES = ("BC", "AB", "SK", "MB", "ON", "QC", "NB", "NS", "PE", "NL", "YT", "NT", "NU")
# Codes the hotspot layer uses outside Canada: US state codes and MX.
OTHER_HOTSPOT_AGENCIES = (
    "AK",
    "AL",
    "AR",
    "AZ",
    "CA",
    "CO",
    "CT",
    "DC",
    "DE",
    "FL",
    "GA",
    "HI",
    "IA",
    "ID",
    "IL",
    "IN",
    "KS",
    "KY",
    "LA",
    "MA",
    "MD",
    "ME",
    "MI",
    "MN",
    "MO",
    "MS",
    "MT",
    "NC",
    "ND",
    "NE",
    "NH",
    "NJ",
    "NM",
    "NV",
    "NY",
    "OH",
    "OK",
    "OR",
    "PA",
    "RI",
    "SC",
    "SD",
    "TN",
    "TX",
    "UT",
    "VA",
    "VT",
    "WA",
    "WI",
    "WV",
    "WY",
    "MX",
)
# The national fire database adds Parks Canada.
LARGE_FIRE_AGENCIES = (*CANADIAN_AGENCIES, "PC")

# A perimeter polygon can be hundreds of KB (20 perimeters with geometry were
# 1.96 MB live, 2026-10-03), so geometry rows stop at this many bytes.
GEOMETRY_BYTES_MAX = 400_000

# The station layer uses legacy province codes: NF for NL, SA for SK (live).
PROVINCE_TO_STATION_CODE = {"NL": "NF", "SK": "SA"}
STATION_CODE_TO_PROVINCE = {v: k for k, v in PROVINCE_TO_STATION_CODE.items()}

# Legend of public:fdr_current_shp (WMS GetLegendGraphic): GRIDCODE 0-3 are
# Low..Very High; 4 (Extreme) is inferred from the CWFIS five-class scale.
DANGER_CLASSES = {0: "Low", 1: "Moderate", 2: "High", 3: "Very High", 4: "Extreme"}
# The French class names CWFIS's French danger map uses.
DANGER_CLASSES_FR = {0: "Bas", 1: "Modéré", 2: "Élevé", 3: "Très élevé", 4: "Extrême"}

NFDB_CAUSES = {
    "N": "Natural",
    "H": "Human",
    "U": "Unknown",
    "H-PB": "Human (prescribed burn)",
}
NFDB_CAUSES_FR = {
    "N": "Naturelle",
    "H": "Humaine",
    "U": "Inconnue",
    "H-PB": "Humaine (brûlage dirigé)",
}
