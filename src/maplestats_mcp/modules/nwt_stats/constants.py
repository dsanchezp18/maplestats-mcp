"""Constants for the NWT Bureau of Statistics module.

Fetched live on 2026-10-03. statsnwt.ca is a static site with no API: the
topic pages under the home page's menu link 633 distinct Excel files (603
.xlsx and 23 legacy .xls, a few with a `?v=` cache-busting query), plus one
statistical profile per community on the pages under
/community-data/infrastructure/. File names keep their spaces, ampersands and
apostrophes, so links are percent-encoded before they are requested.

The Bureau's 290 entries on opendata.gov.nt.ca (`bureau-of-statistics`) are
links back to these HTML pages, so the CKAN tools cannot read the numbers;
289 of them carry the Open Government Licence - Northwest Territories. Its
attribution statement, when the provider gives none, is the one in LICENCE.
"""

DOMAIN = "www.statsnwt.ca"
SITE = f"https://{DOMAIN}"
HOSTS = frozenset({DOMAIN, "statsnwt.ca"})

# Slug -> (page path, English title, French title). The English titles are the
# agency's menu labels; pages that link no Excel file (multipliers, labour
# market outlooks, income assistance, living cost differentials, current
# indicators, By the Numbers) are left out.
TOPICS: dict[str, tuple[str, str, str]] = {
    "gdp": ("/economy/gdp/", "Gross domestic product", "Produit intérieur brut"),
    "business-dynamics": (
        "/economy/BusinessDynamics/index.php",
        "Business dynamics and ownership (business conditions survey)",
        "Dynamique et propriété des entreprises (conditions des entreprises)",
    ),
    "exports-imports": (
        "/economy/exports_imports/",
        "Exports and imports",
        "Exportations et importations",
    ),
    "investment": ("/economy/investment/", "Investment", "Investissements"),
    "retail-wholesale-trade": (
        "/economy/retail-wholesale-trade/",
        "Retail and wholesale trade",
        "Commerce de détail et de gros",
    ),
    "manufacturing": ("/economy/manufacturing/", "Manufacturing", "Fabrication"),
    "oil-gas": ("/economy/oil-gas/", "Oil and gas", "Pétrole et gaz"),
    "minerals": ("/economy/minerals/", "Minerals", "Minéraux"),
    "kindergarten-grade-12": (
        "/education/kindergarten-to-grade-12/index.html",
        "Junior kindergarten to grade 12",
        "Prématernelle à la 12e année",
    ),
    "highest-schooling": (
        "/education/highest-level/index.html",
        "Highest level of schooling",
        "Plus haut niveau de scolarité",
    ),
    "post-secondary": (
        "/education/post-secondary-apprentices/index.html",
        "Post-secondary and apprentices",
        "Études postsecondaires et apprentis",
    ),
    "environment": ("/environment/", "Environment", "Environnement"),
    "health-indicators": (
        "/health/health-conditions/",
        "General health indicators",
        "Indicateurs généraux de santé",
    ),
    "lifestyle": (
        "/health/alcohol-drug-use/",
        "Lifestyle behaviour",
        "Habitudes de vie",
    ),
    "disability": (
        "/health/disabled/index.html",
        "Disability and activity limitations",
        "Incapacités et limitations d'activités",
    ),
    "housing": ("/Housing/housing-conditions/", "Housing conditions", "Conditions de logement"),
    "internet": ("/Housing/internet_usage.html", "Internet usage", "Utilisation d'Internet"),
    "crime": (
        "/justice/police-reported-crime/index.html",
        "Police-reported crime",
        "Criminalité déclarée par la police",
    ),
    "labour-force": (
        "/labour-income/labour-force-activity/",
        "Labour force activity",
        "Activité sur le marché du travail",
    ),
    "labour-supply": (
        "/labour-income/labour-supply/index.html",
        "Labour supply",
        "Offre de main-d'œuvre",
    ),
    "income": ("/labour-income/income/index.html", "Income", "Revenu"),
    "earnings-wages": (
        "/labour-income/earnings-and-wages/",
        "Earnings and wages",
        "Rémunération et salaires",
    ),
    "language": ("/language/", "Language", "Langues"),
    "population": (
        "/population/population-estimates/",
        "Population estimates - NWT",
        "Estimations de la population - T.N.-O.",
    ),
    "population-communities": (
        "/population/population-estimates/bycommunity.php",
        "Population estimates - by community",
        "Estimations de la population par collectivité",
    ),
    "population-projections": (
        "/population/community-projections/",
        "Population projections",
        "Projections démographiques",
    ),
    "vital-statistics": (
        "/population/vital-statistics/",
        "Vital statistics",
        "Statistiques de l'état civil",
    ),
    "cpi": (
        "/prices-expenditures/cpi/",
        "Consumer price index",
        "Indice des prix à la consommation",
    ),
    "community-price-index": (
        "/prices-expenditures/community-price-index/",
        "Community price indexes",
        "Indices des prix des collectivités",
    ),
    "household-expenditures": (
        "/prices-expenditures/household_expenditures/",
        "Household expenditures",
        "Dépenses des ménages",
    ),
    "market-basket-measure": (
        "/prices-expenditures/market_basket_measure/",
        "Market basket measure",
        "Mesure du panier de consommation",
    ),
    "traditional-activities": (
        "/Traditional%20Activities/",
        "Traditional activities",
        "Activités traditionnelles",
    ),
    "transportation": ("/Transportation/index.html", "Transportation", "Transports"),
    "census-2021": ("/census/2021/", "2021 Census", "Recensement de 2021"),
    "census-2016": ("/census/2016/", "2016 Census", "Recensement de 2016"),
    "census-2011": (
        "/census/2011/",
        "2011 Census and National Household Survey",
        "Recensement de 2011 et Enquête nationale auprès des ménages",
    ),
    "census-2006": ("/census/2006/", "2006 Census", "Recensement de 2006"),
    "census-2001": ("/census/2001/", "2001 Census", "Recensement de 2001"),
    "census-1996": ("/census/1996/", "1996 Census", "Recensement de 1996"),
    "alcohol-cannabis": (
        "/Alcohol-Cannabis/index.php",
        "Alcohol and cannabis",
        "Alcool et cannabis",
    ),
    "community-data": (
        "/community-data/index.html",
        "Community data (statistical profile of each community)",
        "Données des collectivités (profil statistique de chaque collectivité)",
    ),
    "food-security": ("/food-security/index.html", "Food security", "Sécurité alimentaire"),
    "poverty-indicators": (
        "/Poverty%20Indicators/index.html",
        "Poverty indicators",
        "Indicateurs de pauvreté",
    ),
    "profile-women": ("/Profiles/Women/index.html", "Profile: women", "Profil : femmes"),
    "profile-seniors": ("/Profiles/Seniors/index.html", "Profile: seniors", "Profil : aînés"),
    "statistics-quarterly": (
        "/publications/statistics-quarterly/index.php",
        "Statistics Quarterly",
        "Statistiques trimestrielles",
    ),
    "socio-economic-scan": (
        "/publications/socio-economic_scan/",
        "Socio-economic scan",
        "Portrait socioéconomique",
    ),
    "community-statistics-summary": (
        "/publications/summary_comm_stats/index.html",
        "Summary of NWT community statistics",
        "Sommaire des statistiques des collectivités des T.N.-O.",
    ),
    "surveys": (
        "/recent_surveys/",
        "Surveys (NWT Community Survey and others)",
        "Enquêtes (Enquête sur les collectivités des T.N.-O. et autres)",
    ),
}

# Topics whose files sit one page deeper: the topic page links these subpages
# (one per community), and each subpage links that community's profile.
SUBPAGE_PREFIXES: dict[str, str] = {"community-data": "/community-data/infrastructure/"}

# No published rate limit; two requests a second keeps a cold search of every
# page (about 85 requests) under a minute.
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
    "fr": "Deux énoncés s'appliquent. (1) Licence du gouvernement ouvert - Territoires du "
    "Nord-Ouest, que le catalogue de données ouvertes du territoire indique pour ces "
    "fichiers (réutilisation permise, y compris commerciale, avec attribution). "
    "Attribution : Contient des renseignements visés par la licence du gouvernement "
    f"ouvert des Territoires du Nord-Ouest. {LICENCE_URL} "
    "(2) Les conditions d'utilisation générales liées à statsnwt.ca demandent d'obtenir "
    f"une permission avant tout usage commercial. {TERMS_URL} Vérifiez lequel s'applique "
    "à votre usage.",
}
