"""Constants for the CBSA border wait times module (checked live 2026-10-03)."""

CSV_URL = {
    "en": "https://www.cbsa-asfc.gc.ca/bwt-taf/bwt-eng.csv",
    "fr": "https://www.cbsa-asfc.gc.ca/bwt-taf/bwt-fra.csv",
}
PAGE_URL = {
    "en": "https://www.cbsa-asfc.gc.ca/bwt-taf/menu-eng.html",
    "fr": "https://www.cbsa-asfc.gc.ca/bwt-taf/menu-fra.html",
}
# open.canada.ca datasets with the historical files (land 2010 onward, air).
HISTORICAL_LAND_DATASET = "000fe5aa-1d77-42d1-bfe7-458c51dacfef"
HISTORICAL_AIR_DATASET = "fe8020ad-51a1-4752-a509-b011a48411a8"

RATE_LIMIT_SOURCE = "cbsa"
RATE_LIMIT_PER_SECOND = 1.0
RATE_LIMIT_CAPACITY = 2.0

# The file is rewritten every few minutes (Last-Modified moved between two
# requests 20 seconds apart on 2026-10-03), so the cache stays short.
CACHE_TTL_SECONDS = 120
# The files were 3.4 KB (en) and 3.7 KB (fr).
MAX_FILE_BYTES = 512 * 1024

LICENCE = (
    "Contains information licensed under the Open Government Licence - Canada "
    "(https://open.canada.ca/en/open-government-licence-canada). Source: Canada Border "
    "Services Agency."
)
LICENCE_FR = (
    "Contient des informations visées par la Licence du gouvernement ouvert – Canada "
    "(https://ouvert.canada.ca/fr/licence-du-gouvernement-ouvert-canada). Source : Agence "
    "des services frontaliers du Canada (ASFC)."
)

FRESHNESS = "file rewritten every few minutes; each crossing has its own update time"
FRESHNESS_FR = (
    "fichier réécrit toutes les quelques minutes ; chaque poste frontalier a sa propre "
    "heure de mise à jour"
)
COVERAGE = "about 30 land crossings; most U.S.-bound lanes are not reported ('--')"
COVERAGE_FR = (
    "une trentaine de postes frontaliers terrestres ; la plupart des voies vers les "
    "États-Unis ne sont pas indiquées (« -- »)"
)
# The French file translates office names and wait values but not locations.
LOCATION_NOTE_FR = (
    "Les noms des bureaux et les temps d'attente viennent du fichier français de l'ASFC ; "
    "les lieux (« location ») n'y sont pas traduits et restent tels que publiés."
)

# Time zone abbreviations in the "Last updated" column, English and French,
# as UTC offsets in hours. Saskatchewan crossings say CST all year.
ZONES: dict[str, float] = {
    "NDT": -2.5,
    "HAT": -2.5,
    "NST": -3.5,
    "HNT": -3.5,
    "ADT": -3,
    "HAA": -3,
    "AST": -4,
    "HNA": -4,
    "EDT": -4,
    "HAE": -4,
    "EST": -5,
    "HNE": -5,
    "CDT": -5,
    "HAC": -5,
    "CST": -6,
    "HNC": -6,
    "MDT": -6,
    "HAR": -6,
    "MST": -7,
    "HNR": -7,
    "PDT": -7,
    "HAP": -7,
    "PST": -8,
    "HNP": -8,
}

PROVINCES = {
    "NB": ("New Brunswick", "Nouveau-Brunswick"),
    "QC": ("Quebec", "Québec"),
    "ON": ("Ontario", "Ontario"),
    "MB": ("Manitoba", "Manitoba"),
    "SK": ("Saskatchewan", "Saskatchewan"),
    "AB": ("Alberta", "Alberta"),
    "BC": ("British Columbia", "Colombie-Britannique"),
    "YT": ("Yukon", "Yukon"),
    "NS": ("Nova Scotia", "Nouvelle-Écosse"),
}
