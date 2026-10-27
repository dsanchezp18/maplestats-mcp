SITE_URL = "https://efis.fma.csc.gov.on.ca/fir/"
# The "FIR Data By Year - .CSV Format" page: one row per year with its last
# update date, posting date and a relative link to fir_data_<year>.zip.
INDEX_URL = "https://efis.fma.csc.gov.on.ca/fir/MultiYearReport/MYCIndex.html"
ZIP_URL = "https://efis.fma.csc.gov.on.ca/fir/MultiYearReport/fir_data_{year}.zip"
DOCUMENTATION_URL = (
    "https://efis.fma.csc.gov.on.ca/fir/MultiYearReport/Documentation%20for%20CSV%20files.pdf"
)
SOURCE = "on-fir"

RATE_LIMIT_SOURCE = "on_fir"
RATE_LIMIT_PER_SECOND = 1.0
RATE_LIMIT_CAPACITY = 2.0
INDEX_TTL_SECONDS = 6 * 3600

# Ontario's count of municipalities required to file, as the page states
# ("FIR2025 Files Posted: 34 of the 444 Municipalities in Ontario").
ONTARIO_MUNICIPALITIES = 444

# Schedule 02, line 0041, column 1: the population the treasurer reports.
POPULATION_SLC = "slc.02X.L0041.C01.01"
HOUSEHOLDS_SLC = "slc.02X.L0040.C01.01"

MAX_COMPARE_YEARS = 10
MAX_COMPARE_MUNICIPALITIES = 50
DEFAULT_COMPARE_LIMIT = 50
MAX_COMPARE_LIMIT = 500
MAX_SCHEDULE_ROWS = 2000
DEFAULT_SEARCH_LIMIT = 25
MAX_SEARCH_LIMIT = 200

TIER_NAMES = {
    "UT": ("upper tier (county, region, district)", "palier supérieur (comté, région, district)"),
    "LT": ("lower tier", "palier inférieur"),
    "ST": ("single tier", "palier unique"),
}
# MTYPE_CODE, from the Ministry's documentation for the CSV files.
MUNICIPAL_TYPES = {
    "0": ("upper tier", "palier supérieur"),
    "1": ("city", "cité"),
    "3": ("separated town", "ville séparée"),
    "4": ("town", "ville"),
    "5": ("village", "village"),
    "6": ("township", "canton"),
}
MSO_NAMES = {
    "11": ("Central", "Centre"),
    "12": ("Eastern", "Est"),
    "13": ("Northeastern", "Nord-Est"),
    "14": ("Northwestern", "Nord-Ouest"),
    "15": ("Western", "Ouest"),
}
