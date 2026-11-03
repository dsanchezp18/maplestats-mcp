"""Constants for Job Bank's yearly "Wages" dataset on open.canada.ca.

Checked live 2026-11-03 with package_show and datastore_search:

- Package adad580f-76b0-4502-bd05-20c125de9116 ("Wages" / "Salaires", ESDC,
  OGL-Canada) holds one CSV resource per release, named "<year> Wages", all
  DataStore-active, 2012 to 2025. The 2025 release (19 Nov 2025) is resource
  9da94d63-b178-4a64-aeb3-b6a3bd721ad2 with 44,376 rows: 516 occupations x
  86 geographies.
- The 2023, 2024 and 2025 releases use NOC 2021 five-digit codes
  ("NOC_21231"); 2022 and earlier use NOC 2016 four-digit codes and other
  column names ("NOC_Title", "ER_Name_Nom_RE"), so they are not read here.
- Column names drift between releases (NOC_TITLE_ENG in 2023, NOC_Title_eng
  in 2024-2025; Source2025_NHQ only in 2025; Non_WageBen_pct in 2024,
  EmployeesWithNonWageBenefit_Pct in 2025). The client resolves them from
  the resource's `fields`, case-insensitively, rather than hard-coding them.
- National rows have ER code ER00 and prov "NAT" (2024-2025) or "NA" (2023).
"""

BASE_URL = "https://open.canada.ca/data/api/3/action/"
RATE_LIMIT_SOURCE = "jobbank-wages"
RATE_LIMIT_PER_SECOND = 2.0
RATE_LIMIT_CAPACITY = 4.0

PACKAGE_ID = "adad580f-76b0-4502-bd05-20c125de9116"
RESOURCE_NAME_PATTERN = r"^\s*(\d{4})\s+wages\s*$"
# First release on NOC 2021 (see the module docstring).
MIN_RELEASE_YEAR = 2023

# Used only when package_show lists no "<year> Wages" resource this module can
# read (a renamed or restructured package); the result then says so.
FALLBACK_YEAR = 2025
FALLBACK_RESOURCE_ID = "9da94d63-b178-4a64-aeb3-b6a3bd721ad2"

DATASET_PAGE_EN = f"https://open.canada.ca/data/en/dataset/{PACKAGE_ID}"
DATASET_PAGE_FR = f"https://ouvert.canada.ca/data/fr/dataset/{PACKAGE_ID}"
JOB_BANK_WAGES_EN = "https://www.jobbank.gc.ca/trend-analysis/search-wages"
JOB_BANK_WAGES_FR = "https://www.guichetemplois.gc.ca/analyse-tendances/recherche-salaires"
METHODOLOGY_URL = "https://www.jobbank.gc.ca/trend-analysis/search-wages/wage-methodology"

# Released once a year (November so far), so a day is plenty.
DISCOVERY_TTL_SECONDS = 24 * 60 * 60
DATA_TTL_SECONDS = 24 * 60 * 60

NATIONAL_ER_CODE = "ER00"
DATASTORE_PAGE = 1000
DATASTORE_MAX_PAGES = 5

SEARCH_LIMIT_DEFAULT = 20
SEARCH_LIMIT_MAX = 100
COMPARE_MIN = 2
COMPARE_MAX = 25

# User province spellings -> the `prov` codes the dataset uses (read live).
PROVINCE_ALIASES: dict[str, str] = {
    "NL": "NL",
    "PE": "PEI",
    "PEI": "PEI",
    "NS": "NS",
    "NB": "NB",
    "QC": "QC",
    "ON": "ON",
    "MB": "MB",
    "SK": "SK",
    "AB": "AB",
    "BC": "BC",
    "YT": "YK",
    "YK": "YK",
    "NT": "NWT",
    "NWT": "NWT",
    "NU": "NU",
}
NATIONAL_PROV_CODES = frozenset({"NAT", "NA"})
