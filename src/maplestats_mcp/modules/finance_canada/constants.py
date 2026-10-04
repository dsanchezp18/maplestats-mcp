"""Constants for the Finance Canada module (checked live 2026-10-03)."""

SITE = "https://www.canada.ca"
# The publications pages are filled by a script from this feed (every
# Finance publication with its type, title, links and date in both languages).
FEED_URL = SITE + "/content/dam/fin/documents/publications/pub-rep/json.json"
FRT_INDEX = {
    "en": SITE + "/en/department-finance/services/publications/fiscal-reference-tables.html",
    "fr": SITE + "/fr/ministere-finances/services/publications/tableaux-reference-financiers.html",
}
FRT_PAGE = {
    "en": SITE + "/en/department-finance/services/publications/fiscal-reference-tables/{year}.html",
    "fr": SITE + "/fr/ministere-finances/services/publications/tableaux-reference-financiers/"
    "{year}.html",
}
FRT_WORKBOOK = SITE + "/content/dam/fin/publications/frt-trf/{year}/frt-trf-{yy:02d}-{suffix}.xlsx"
WORKBOOK_SUFFIX = {"en": "eng", "fr": "fra"}
# The feed keeps five editions (2021-2025 on 2026-10-03); the 2019 and 2020
# workbooks are still on canada.ca. Earlier editions are PDF-only on
# publications.gc.ca.
FIRST_FRT_EDITION = 2019

RATE_LIMIT_SOURCE = "finance_canada"
RATE_LIMIT_PER_SECOND = 1.0
RATE_LIMIT_CAPACITY = 2.0

FEED_TTL_SECONDS = 6 * 60 * 60
WORKBOOK_TTL_SECONDS = 24 * 60 * 60
MONITOR_TTL_SECONDS = 6 * 60 * 60
# Workbooks were 470-670 KB, Fiscal Monitor pages about 150 KB.
MAX_WORKBOOK_BYTES = 10 * 1024 * 1024
MAX_PAGE_BYTES = 4 * 1024 * 1024
FEED_MAX_BYTES = 4 * 1024 * 1024

# One French sheet declares 16,384 columns; real tables use under 40.
MAX_SHEET_COLUMNS = 200
MAX_SHEET_ROWS = 800

# Divider sheets name the part of the workbook the tables after them belong to.
PARTS: dict[str, tuple[str, str]] = {
    "fed - pa": ("Federal government (Public Accounts)", "Gouvernement fédéral (Comptes publics)"),
    "fed - cp": ("Federal government (Public Accounts)", "Gouvernement fédéral (Comptes publics)"),
    "prov - pa": (
        "Provinces and territories (Public Accounts)",
        "Provinces et territoires (Comptes publics)",
    ),
    "prov - cp": (
        "Provinces and territories (Public Accounts)",
        "Provinces et territoires (Comptes publics)",
    ),
    "na": (
        "All levels of government (National Accounts)",
        "Toutes les administrations (comptes nationaux)",
    ),
    "cen": (
        "All levels of government (National Accounts)",
        "Toutes les administrations (comptes nationaux)",
    ),
    "int": ("International comparisons (G7)", "Comparaisons internationales (G7)"),
}

TERMS = (
    "Canada.ca terms (Department of Finance Canada): reproduction for non-commercial "
    "purposes with attribution and without implying endorsement; commercial reproduction "
    "needs written permission."
)
MONITOR_TERMS = (
    "Canada.ca terms (Department of Finance Canada): reproduction for non-commercial "
    "purposes with attribution. The same tables are also published as CSV files under the "
    "Open Government Licence - Canada on open.canada.ca ('The Fiscal Monitor: <year>')."
)
