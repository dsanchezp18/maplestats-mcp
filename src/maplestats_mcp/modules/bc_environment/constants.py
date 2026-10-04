"""Constants for the BC Ministry of Environment monitoring files.

Verified live on 2026-10-03 against www.env.gov.bc.ca (Apache directory
listings, every file family downloaded and profiled):

Air (EMAB, Air_Quality and Meteorological folders): one CSV per parameter,
newest hour first, 730 hourly rows per station (about 30 days), columns
DATE_PST, STATION_NAME, RAW_VALUE, REPORTED_VALUE, INSTRUMENT, UNITS,
PARAMETER, EMS_ID, LATITUDE, LONGITUDE. DATE_PST is fixed Pacific Standard
Time (UTC-8) all year: the per-station files carry both DATE_PST and
DATE_LOCAL, and in October DATE_LOCAL is one hour later and labelled PDT.
Missing hours are empty cells; PM25.csv also carried two -6999 values. The
files are rewritten hourly (about 20 minutes past). The per-station files
(Station/<EMS_ID>.csv, about 100 KB) hold the same 30 days as one column
per parameter plus rolling averages (PM25_24, O3_8, ...). The
SNOW.csv files in both folders stopped updating (June 2026 and April 2023)
and are not offered. Verified (quality-assured) historical air data is
published only on an ftp:// server, which this server cannot reach.

Snow (River Forecast Centre, snow/asws/data): wide files, one column per
station headed "<id> <name>", first column DATE(UTC). Current-season files
start on 1 October; the _Archive files run from October 2003 and are
sorted by time, so a period is read with HTTP range requests (the archives
are 40-80 MB). SnowAll/<id>.csv is the tidy per-station file with units
and grades and ISO times with +00:00.

Groundwater (obswell/map/data): OWnnn-data.csv (full record, up to
9.7 MB), -recent.csv (last 12 months, hourly) and -average.csv (daily
means). Values are depth to water in metres below ground: for OW002,
44.8 m groundwater elevation (water/GWElevation.csv) = 193.1 ft ground
elevation in the provincial wells database (58.9 m) minus 14.1 m. The
times carry no zone; aligned against GWElevation.csv (labelled UTC) the
hourly values match at UTC-7, and the series has no daylight-saving gap
or repeat, so it is a fixed UTC-7 clock.

Hydrometric (water folder): long format, Location ID, Location Name,
Status, Latitude, Longitude, Date/Time(UTC), Parameter, Value, Unit,
Grade, Windows-1252 (an en dash in a station name). Current files hold
the water year that began on 1 October; archives are sorted by station
and then time. On 2026-10-03 the archive for the 2025-26 water year held
only its header.
"""

DOMAIN = "www.env.gov.bc.ca"
SITE = f"https://{DOMAIN}"
AIR_BASE = f"{SITE}/epd/bcairquality/aqo/csv"
AIR_RAW = f"{AIR_BASE}/Hourly_Raw_Air_Data"
AIR_STATIONS_URL = f"{AIR_BASE}/bc_air_monitoring_stations.csv"
AQHI_URL = f"{AIR_BASE}/AQHIWeb.csv"
SNOW_BASE = f"{SITE}/wsd/data_searches/snow/asws/data"
WELL_BASE = f"{SITE}/wsd/data_searches/obswell/map/data"
WATER_BASE = f"{SITE}/wsd/data_searches/water"

WFS_URL = "https://openmaps.gov.bc.ca/geo/pub/wfs"
SNOW_STATIONS_LAYER = "WHSE_WATER_MANAGEMENT.SSL_SNOW_ASWS_STNS_SP"
WELLS_LAYER = "WHSE_WATER_MANAGEMENT.GW_WATER_WELLS_WRBC_SVW"
WELL_REGIONS_URL = (
    "https://catalogue.data.gov.bc.ca/dataset/a74f1b97-17f7-499b-84e7-6455e169e425/"
    "resource/a8933793-eadb-4a9c-992c-da4f6ac8ca51/download/gw_well_table.csv"
)

ALLOWED_HOSTS = frozenset({DOMAIN, "catalogue.data.gov.bc.ca", "openmaps.gov.bc.ca"})

AIR_QUALITY_PARAMETERS = (
    "CH4", "CO", "H2S", "HF", "NMHC", "NO", "NO2", "NOx", "O3", "PM10", "PM25", "SO2",
    "THC", "TRS",
)  # fmt: skip
MET_PARAMETERS = (
    "HUMIDITY", "PRECIP", "PRESSURE", "TEMP", "VAPOUR_PRESSURE", "WDIR_UVEC", "WDIR_VECT",
    "WSPD_SCLR", "WSPD_VECT",
)  # fmt: skip

# Wide current-season snow files. Units for SW, SD, PC, TA and the peak wind
# files are stated in the per-station SnowAll files; PA, XR and UD are read
# from the values (about 800-1000, 0-100, 0-360). US states no unit.
SNOW_VARIABLES: dict[str, tuple[str, str | None]] = {
    "SW": ("Snow water equivalent", "mm"),
    "SD": ("Snow depth", "cm"),
    "PC": ("Cumulative precipitation", "mm"),
    "TA": ("Air temperature", "degC"),
    "SW_DAILY": ("Snow water equivalent, daily", "mm"),
    "PA": ("Air pressure", "hPa"),
    "XR": ("Relative humidity", "%"),
    "UD": ("Wind direction", "deg"),
    "US": ("Wind speed", None),
    "UP": ("Peak wind velocity", "km/hr"),
    "UR": ("Peak wind direction", "deg"),
}
SNOW_ARCHIVES = {
    "SW": "SW_Archive.csv",
    "SD": "SD_Archive.csv",
    "PC": "PC_Archive.csv",
    "TA": "TA_Archive.csv",
    "SW_DAILY": "SW_DailyArchive.csv",
}
SNOW_CURRENT = {key: f"{key}.csv" for key in SNOW_VARIABLES} | {"SW_DAILY": "SWDaily.csv"}

HYDRO_FILES = {"discharge": "Discharge", "stage": "Stage"}

RATE_LIMIT_SOURCE = "bc-environment"
RATE_LIMIT_PER_SECOND = 2.0
RATE_LIMIT_CAPACITY = 4.0

CACHE_TTL_HOURLY_SECONDS = 15 * 60
CACHE_TTL_LIST_SECONDS = 6 * 60 * 60
CACHE_TTL_ARCHIVE_SECONDS = 6 * 60 * 60

MAX_FILE_BYTES = 16 * 1024 * 1024
RANGE_CHUNK_BYTES = 128 * 1024
RANGE_READ_MAX_BYTES = 24 * 1024 * 1024

ROWS_LIMIT_DEFAULT = 200
ROWS_LIMIT_MAX = 5000
LIST_LIMIT_DEFAULT = 100
LIST_LIMIT_MAX = 1000

PROVENANCE_SOURCE = "bc-environment"
LICENCE = {
    "en": "Contains information licensed under the Open Government Licence - British "
    "Columbia (https://www2.gov.bc.ca/gov/content/data/policy-standards/open-data/"
    "open-government-licence-bc). Source: BC Ministry of Environment and Parks.",
    "fr": "Contient des renseignements visés par la Licence du gouvernement ouvert - "
    "Colombie-Britannique (https://www2.gov.bc.ca/gov/content/data/policy-standards/"
    "open-data/open-government-licence-bc). Source : ministère de l'Environnement et des "
    "Parcs de la Colombie-Britannique.",
}
