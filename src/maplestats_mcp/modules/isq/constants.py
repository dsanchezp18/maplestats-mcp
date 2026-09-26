"""Constants for statistique.quebec.ca's detailed tables (checked 2026-09-26)."""

SITE = "https://statistique.quebec.ca"
SITEMAP_URL = SITE + "/sitemap.xml"
TABLE_PATH = "/produit/tableau/"
KEN = SITE + "/pls/ken/ken411_data_explt_v2."

RATE_LIMIT_SOURCE = "isq"
RATE_LIMIT_PER_SECOND = 1.0
RATE_LIMIT_CAPACITY = 2.0

SITEMAP_TTL_SECONDS = 24 * 60 * 60
TABLE_TTL_SECONDS = 6 * 60 * 60
MAX_BYTES = 20 * 1024 * 1024

SEARCH_LIMIT_DEFAULT = 25
SEARCH_LIMIT_MAX = 200
ROWS_DEFAULT = 200
ROWS_MAX = 5000

# Helper fields the page script uses for sorting and layout, not data.
LAYOUT_FIELDS = frozenset({"tri_coln", "gras", "saut"})

# Names for the untitled label columns tables use most (checked on 26 tables).
FIELD_LABELS = {
    "de_group": "Groupe",
    "de_coln": "Libellé",
    "de_detl": "Détail",
    "mesr": "Unité",
}
