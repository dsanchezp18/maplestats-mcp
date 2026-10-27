"""Constants for the NWT Bureau of Statistics module.

statsnwt.ca was relaunched on a Drupal site before 2026-10-26 (checked live
that day): topic pages moved under /en/, the old paths answer 301 to them or
404, and the files moved to /sites/default/files/documents/. Pages link
Excel files with the agency's titles; some also offer an export of a table
shown on the page (/en/download-xlsx/...). The census and community survey
pages link their files on bearnet.gov.nt.ca/t2/stats/, a host that asks for
a login (HTTP 401); the same files answer on www.statsnwt.ca under the same
path without the /t2/stats prefix, so those links are rewritten. File names
keep their spaces, ampersands and apostrophes, so links are percent-encoded
before they are requested.

The Bureau's 290 entries on opendata.gov.nt.ca (`bureau-of-statistics`) are
links back to these HTML pages, so the CKAN tools cannot read the numbers;
289 of them carry the Open Government Licence - Northwest Territories. Its
attribution statement, when the provider gives none, is the one in LICENCE.
"""

from maplestats_mcp.shared.i18n import french_spacing

DOMAIN = "www.statsnwt.ca"
SITE = f"https://{DOMAIN}"
HOSTS = frozenset({DOMAIN, "statsnwt.ca"})
# Links on this host with this path prefix are read from DOMAIN without it.
STAGING_HOST = "bearnet.gov.nt.ca"
STAGING_PREFIX = "/t2/stats"
# An export of a table shown on a page; its path has no file extension.
TABLE_EXPORT_PREFIX = "/en/download-xlsx/"

# Slug -> (page path, English title, French title). The English titles are the
# agency's menu labels; pages that link no Excel file (multipliers, labour
# market, income assistance, living cost differentials, indicators, By the
# Numbers) are left out.
TOPICS: dict[str, tuple[str, str, str]] = {
    "gdp": ("/en/economy/gdp", "Gross domestic product", "Produit intérieur brut"),
    "business-dynamics": (
        "/en/business-dynamics",
        "Business dynamics and ownership (business conditions survey)",
        "Dynamique et propriété des entreprises (conditions des entreprises)",
    ),
    "exports-imports": (
        "/en/economy/exports-imports",
        "Exports and imports",
        "Exportations et importations",
    ),
    "investment": ("/en/economy/capital-expenditure", "Investment", "Investissements"),
    "retail-wholesale-trade": (
        "/en/economy/retail-wholesale-trade",
        "Retail and wholesale trade",
        "Commerce de détail et de gros",
    ),
    "oil-gas-minerals": (
        "/en/economy/oil-gas_minerals",
        "Oil, gas and minerals",
        "Pétrole, gaz et minéraux",
    ),
    "alcohol-cannabis": (
        "/en/economy/alcohol-cannabis-sales",
        "Alcohol and cannabis sales",
        "Ventes d'alcool et de cannabis",
    ),
    "kindergarten-grade-12": (
        "/en/education/junior-k-to-12",
        "Junior kindergarten to grade 12",
        "Prématernelle à la 12e année",
    ),
    "highest-schooling": (
        "/en/education/highest-level-of-schooling",
        "Highest level of schooling",
        "Plus haut niveau de scolarité",
    ),
    "post-secondary": (
        "/en/education/post-secondary-apprentices",
        "Post-secondary and apprentices",
        "Études postsecondaires et apprentis",
    ),
    "environment": ("/en/environment", "Environment", "Environnement"),
    "health-indicators": (
        "/en/health/general-health-indicators",
        "General health indicators",
        "Indicateurs généraux de santé",
    ),
    "lifestyle": (
        "/en/health/lifestyle-behaviour",
        "Lifestyle behaviour",
        "Habitudes de vie",
    ),
    "disability": (
        "/en/health/disability-activity-limitations",
        "Disability and activity limitations",
        "Incapacités et limitations d'activités",
    ),
    "housing": ("/en/housing/housing-conditions", "Housing conditions", "Conditions de logement"),
    "internet": ("/en/housing/internet-usage", "Internet usage", "Utilisation d'Internet"),
    "crime": (
        "/en/justice/police-reported-crime",
        "Police-reported crime",
        "Criminalité déclarée par la police",
    ),
    "labour-force": (
        "/en/labour-and-income/labour-force-activity",
        "Labour force activity",
        "Activité sur le marché du travail",
    ),
    "labour-supply": (
        "/en/labour-and-income/labour-supply",
        "Labour supply",
        "Offre de main-d'œuvre",
    ),
    "income": ("/en/labour-and-income/Income-Statistics", "Income", "Revenu"),
    "earnings-wages": (
        "/en/labour-and-income/earnings-wages",
        "Earnings and wages",
        "Rémunération et salaires",
    ),
    "language": ("/en/language", "Language", "Langues"),
    "population": (
        "/en/population/NWT-population-estimates",
        "Population estimates - NWT",
        "Estimations de la population – T.N.-O.",
    ),
    "population-communities": (
        "/en/population/community-population-estimates",
        "Population estimates - by community",
        "Estimations de la population par collectivité",
    ),
    "population-projections": (
        "/en/population/projections",
        "Population projections",
        "Projections démographiques",
    ),
    "vital-statistics": (
        "/en/population/vital-statistics",
        "Vital statistics",
        "Statistiques de l'état civil",
    ),
    "cpi": (
        "/en/prices-and-expenditures/consumer-price-index",
        "Consumer price index",
        "Indice des prix à la consommation",
    ),
    "community-price-index": (
        "/en/prices-and-expenditures/community-price-index",
        "Community price indexes",
        "Indices des prix des collectivités",
    ),
    "household-expenditures": (
        "/en/prices-and-expenditures/household-expenditures",
        "Household expenditures",
        "Dépenses des ménages",
    ),
    "market-basket-measure": (
        "/en/prices-and-expenditures/northern-market-basket-measure",
        "Northern market basket measure",
        "Mesure du panier de consommation du Nord",
    ),
    "traditional-activities": (
        "/en/traditional-activities",
        "Traditional activities",
        "Activités traditionnelles",
    ),
    "transportation": ("/en/transportation", "Transportation", "Transports"),
    "census": (
        "/en/Canadian-Census",
        "Census of Population, 1996 to 2021 (and the 2011 National Household Survey)",
        (
            "Recensement de la population, 1996 à 2021 (et l'Enquête nationale auprès des "
            "ménages de 2011)"
        ),
    ),
    "food-security": ("/en/Food_Security", "Food security", "Sécurité alimentaire"),
    "poverty-indicators": (
        "/en/Poverty_Indicators",
        "Poverty indicators",
        "Indicateurs de pauvreté",
    ),
    "profile-women": ("/en/Women", "Profile: women", "Profil : femmes"),
    "profile-seniors": ("/en/Seniors", "Profile: seniors", "Profil : aînés"),
    "surveys": (
        "/en/community_surveys",
        "NWT Community Survey",
        "Enquête sur les collectivités des T.N.-O.",
    ),
    "other-surveys": ("/en/other_surveys", "Other surveys", "Autres enquêtes"),
}

# No published rate limit; two requests a second keeps a cold search of every
# page (39 requests) under a minute.
RATE_LIMIT_SOURCE = "nwt-stats"
RATE_LIMIT_PER_SECOND = 2.0
RATE_LIMIT_CAPACITY = 4.0

CACHE_TTL_PAGE_SECONDS = 6 * 60 * 60
CACHE_TTL_FILE_SECONDS = 6 * 60 * 60

# The largest file seen is a 350 KB labour force workbook.
MAX_FILE_BYTES = 25 * 1024 * 1024
FILES_LIMIT_DEFAULT = 100
FILES_LIMIT_MAX = 500
ROWS_LIMIT_DEFAULT = 50
ROWS_LIMIT_MAX = 500
TITLE_MAX_CHARS = 300

PROVENANCE_SOURCE = "nwt-bureau-of-statistics"
LICENCE_URL = "https://www.gov.nt.ca/en/open-government-licence-northwest-territories"
TERMS_URL = "http://www.fin.gov.nt.ca/terms-use"
LICENCE = {
    "en": "Two statements apply. (1) Open Government Licence - Northwest Territories, which "
    "the territory's open data catalogue lists for these files (reuse allowed, including "
    "commercial, with attribution). Attribution: Contains information licensed under the "
    f"Open Government Licence - Northwest Territories. {LICENCE_URL} "
    "(2) The general terms of use linked from statsnwt.ca ask users to request permission "
    f"before commercial use. {TERMS_URL} Check which applies to your use.",
    "fr": french_spacing(
        "Deux énoncés s'appliquent. (1) Licence du gouvernement ouvert – Territoires du "
        "Nord-Ouest, que le catalogue de données ouvertes du territoire indique pour ces "
        "fichiers (réutilisation permise, y compris commerciale, avec attribution). "
        "Attribution : « Contient des renseignements visés par la Licence du gouvernement "
        f"ouvert – Territoires du Nord-Ouest. » {LICENCE_URL} "
        "(2) Les conditions générales d'utilisation liées depuis statsnwt.ca demandent "
        f"d'obtenir une autorisation avant tout usage commercial. {TERMS_URL} Vérifiez lequel "
        "s'applique à votre usage."
    ),
}
