"""Constants for FCAC's credit card and account comparison tools.

Every form value below was read from the live filter pages on 2026-09-26
(itools-ioutils.fcac-acfc.gc.ca/CCCT-OCCC/ and /ACT-OCC/, English and
French). The two tools number provinces and currencies differently, so
each keeps its own map.
"""

from __future__ import annotations

BASE_URL = "https://itools-ioutils.fcac-acfc.gc.ca/"
CARDS_PATH = "CCCT-OCCC/"
ACCOUNTS_PATH = "ACT-OCC/"

# The tools use "eng"/"fra" in their page names and `lang` query values.
PAGE_LANG = {"en": "eng", "fr": "fra"}

# ASP.NET WebForms control-name prefix shared by every form field.
FIELD_PREFIX = "ctl00$ctl00$MainContent$MainContent$"

RATE_LIMIT_SOURCE = "fcac"
# No published limit. Walking one result list is one postback per page of
# ten products (95 Ontario credit cards took 10 requests), so a modest
# burst keeps a search to a few seconds without hammering the server.
RATE_LIMIT_PER_SECOND = 4.0
RATE_LIMIT_CAPACITY = 4.0
# Institutions update products at any time and FCAC publishes no schedule.
CACHE_TTL_SECONDS = 6 * 60 * 60
REQUEST_TIMEOUT_SECONDS = 60.0

# Ten products per result page; a list of 200 products is 20 pages. The
# largest list seen live was 101 credit cards (Ontario, CAD, student).
MAX_RESULT_PAGES = 60

LIMIT_DEFAULT = 25
LIMIT_MAX = 200

PROVINCE_NAMES = {
    "AB": ("Alberta", "Alberta"),
    "BC": ("British Columbia", "Colombie-Britannique"),
    "MB": ("Manitoba", "Manitoba"),
    "NB": ("New Brunswick", "Nouveau-Brunswick"),
    "NL": ("Newfoundland and Labrador", "Terre-Neuve-et-Labrador"),
    "NS": ("Nova Scotia", "Nouvelle-Écosse"),
    "NT": ("Northwest Territories", "Territoires du Nord-Ouest"),
    "NU": ("Nunavut", "Nunavut"),
    "ON": ("Ontario", "Ontario"),
    "PE": ("Prince Edward Island", "Île-du-Prince-Édouard"),
    "QC": ("Quebec", "Québec"),
    "SK": ("Saskatchewan", "Saskatchewan"),
    "YT": ("Yukon", "Yukon"),
}

# ddlProvince option values, credit card tool.
CARD_PROVINCES = {
    "AB": "1",
    "BC": "2",
    "MB": "3",
    "NB": "4",
    "NL": "5",
    "NS": "6",
    "ON": "7",
    "PE": "8",
    "QC": "9",
    "SK": "10",
    "NT": "11",
    "NU": "12",
    "YT": "13",
}
# ddlProvince option values, account tool (a different numbering).
ACCOUNT_PROVINCES = {
    "AB": "10",
    "BC": "11",
    "MB": "12",
    "NB": "13",
    "NL": "14",
    "NS": "15",
    "ON": "16",
    "PE": "17",
    "QC": "18",
    "SK": "19",
    "NT": "20",
    "NU": "21",
    "YT": "22",
}

# rblCurrency radio values.
CARD_CURRENCIES = {"CAD": "14", "USD": "15", "other": "20"}
ACCOUNT_CURRENCIES = {"CAD": "3", "USD": "4", "other": "9"}

# rblAccountType radio values.
ACCOUNT_TYPES = {"chequing": "1", "savings": "2"}

# cblDemographic checkbox values, in the order the form lists them (the
# index is part of the control name, cblDemographic$<index>). Choosing a
# group adds that group's products to the list: Ontario chequing went from
# 61 accounts to 69 with "senior" and 72 with "student" (checked live).
ACCOUNT_GROUPS = {
    "senior": (0, "25"),
    "gis_recipient": (1, "26"),
    "rdsp_beneficiary": (2, "27"),
    "youth": (3, "29"),
    "student": (4, "30"),
    "newcomer": (5, "28"),
    "indigenous": (6, "243"),
    "social_assistance": (7, "244"),
    "disability_tax_credit": (8, "245"),
}

# Reward categories as the credit card tool labels them in each language.
REWARD_LABELS = {
    "cash_back": ("Cash back", "Remise en argent"),
    "travel": ("Travel", "Voyages"),
    "groceries": ("Groceries", "Produits alimentaires"),
    "gas": ("Gas", "Essence"),
    "general_merchandise": ("General merchandise", "Fournitures de tout genre"),
}

FRESHNESS = (
    "Live from FCAC's comparison tool. Financial institutions supply and update the "
    "product details; FCAC publishes no update schedule."
)
CARDS_COVERAGE = (
    "Credit cards that financial institutions submit to FCAC's Credit Card Comparison "
    "Tool, not every card sold in Canada."
)
ACCOUNTS_COVERAGE = (
    "Chequing and savings accounts that financial institutions submit to FCAC's Account "
    "Comparison Tool, not every account offered in Canada."
)
