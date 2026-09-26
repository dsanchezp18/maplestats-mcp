"""Constants for IRCC's "Monthly IRCC Updates" open data files.

Checked live 2026-09-25: the 12 datasets titled "... - Monthly IRCC
Updates" on open.canada.ca (organization `cic`) list 96 CSV resources, all
served from www.ircc.canada.ca/opendata-donneesouvertes/data/ODP-*.csv
without a challenge. The largest is about 30 MB (ODP-PR-PT_NOC4.csv).
"""

CKAN_SEARCH_URL = "https://open.canada.ca/data/api/3/action/package_search"
CKAN_QUERY = 'title:"Monthly IRCC Updates"'
CKAN_ROWS = 50
DATASET_PAGE_URL = "https://open.canada.ca/data/en/dataset/"
DATASET_PAGE_URL_FR = "https://ouvert.canada.ca/data/fr/dataset/"
FILE_HOST = "www.ircc.canada.ca"
FILE_PREFIX = "https://www.ircc.canada.ca/opendata-donneesouvertes/data/"

RATE_LIMIT_SOURCE = "ircc-monthly"
RATE_LIMIT_PER_SECOND = 1.0
RATE_LIMIT_CAPACITY = 2.0

# Files are refreshed once a month; the catalogue changes even less often.
CATALOGUE_TTL_SECONDS = 24 * 60 * 60
TABLE_TTL_SECONDS = 12 * 60 * 60
MAX_FILE_BYTES = 64 * 1024 * 1024

ROWS_DEFAULT = 100
ROWS_MAX = 5000
VALUES_SHOWN_MAX = 200

# Cell text for a count IRCC suppresses (0 < n < 5, per its notes).
SUPPRESSED = "--"

MONTHS = {
    m: i
    for i, m in enumerate(
        ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"),
        start=1,
    )
}

ROUNDING_NOTE = (
    "IRCC rounds every count to a multiple of 5 and shows counts from 1 to 4 "
    "as '--' (suppressed); its files say 'not for calculations'. Sums of "
    "rounded cells can differ from IRCC's published totals."
)
ROUNDING_NOTE_FR = (
    "IRCC arrondit chaque nombre au multiple de 5 et affiche les nombres de "
    "1 à 4 par « -- » (supprimés); ses fichiers indiquent « pas pour les "
    "calculs ». La somme de cellules arrondies peut différer des totaux "
    "publiés par IRCC."
)
