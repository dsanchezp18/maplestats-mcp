WWW_DOMAIN = "www.aer.ca"
STATIC_DOMAIN = "static.aer.ca"
RATE_LIMIT_SOURCE = "aer"
# No published rate limit found; kept conservative like this project's
# other unpublished-limit legacy government portals.
RATE_LIMIT_PER_SECOND = 3.0
RATE_LIMIT_CAPACITY = 5.0

TIMEZONE = "America/Edmonton"

CACHE_TTL_DAILY_SECONDS = 6 * 60 * 60
CACHE_TTL_LINK_SECONDS = 24 * 60 * 60

# ST1 daily well-licence report -- confirmed live 2026-09-22 this must be
# fetched from static.aer.ca directly (see module docstring for why).
DAY_CODES = {
    "sunday": "SUN",
    "monday": "MON",
    "tuesday": "TUE",
    "wednesday": "WED",
    "thursday": "THU",
    "friday": "FRI",
    "saturday": "SAT",
}
WELL_LICENCE_DAILY_URL = f"https://{STATIC_DOMAIN}/prd/data/well-lic/WELLS{{day_code}}.TXT"

# Confirmed live 2026-09-22: the current year publishes one ZIP per
# month; every prior year publishes a single ZIP for the whole year.
# The path prefix also genuinely changes at the 2023/2024 boundary
# (2024 onward uses "/prd/data/well-lic/", 2023 and earlier use
# "/data/well-lic/" with no "prd" segment) -- confirmed by reading the
# real links on the ST1 archive page, not guessed.
WELL_LICENCE_MONTHLY_ZIP_URL = (
    f"https://{WWW_DOMAIN}/prd/data/well-lic/dwll{{year}}-{{month:02d}}.zip"
)
WELL_LICENCE_YEARLY_ZIP_URL_NEW = f"https://{WWW_DOMAIN}/prd/data/well-lic/dwll{{year}}.zip"
WELL_LICENCE_YEARLY_ZIP_URL_OLD = f"https://{WWW_DOMAIN}/data/well-lic/dwll{{year}}.zip"
WELL_LICENCE_YEARLY_URL_PATH_BOUNDARY_YEAR = 2024
# The ST1 archive page links yearly ZIPs from 2017 on; 2016 and earlier
# answer 404 on both path prefixes (checked live 2026-10-03).
WELL_LICENCE_FIRST_YEAR = 2017

# httpx asks for gzip by default, and static.aer.ca then answers HEAD with
# content-encoding: gzip and no Content-Length (live 2026-10-03: size_bytes
# was always null; with identity the 2025 ZIP reports 831951 bytes).
HEAD_HEADERS = {"Accept-Encoding": "identity"}

# ST3 monthly production volumes/prices -- confirmed live 2026-09-22
# against every "_current.xlsx" link on the ST3 report page.
PRODUCTION_PRODUCTS = {
    "butane": "Butane",
    "ethane": "Ethane",
    "gas": "Gas",
    "ngl": "NGL",
    "oil": "Oil",
    "propane": "Propane",
    "sulphur": "Sulphur",
    "oil_prices": "prices_oil",
}
PRODUCTION_VOLUMES_URL = f"https://{WWW_DOMAIN}/documents/sts/st3/{{product_path}}_current.xlsx"

# ST98 Alberta Energy Outlook. The report page links one "executive summary
# data" workbook per edition, at paths that change from year to year (read
# from the page live 2026-11-07, not guessed): every www.aer.ca link answers a
# 301 to the same path under static.aer.ca/prd/.
ST98_PAGE_URL = (
    f"https://{WWW_DOMAIN}/data-and-performance-reports/statistical-reports/"
    "alberta-energy-outlook-st98"
)
ST98_WORKBOOKS = {
    2022: f"https://{WWW_DOMAIN}/documents/sts/st98/2022/st98-2022-executive-summary-data.xlsx",
    2023: f"https://{WWW_DOMAIN}/documents/sts/ST98/2023/ST98_executive_summary-data.xlsx",
    2024: f"https://{WWW_DOMAIN}/documents/sts/st98/st98-2024-executive-summary-data.xlsx",
    2025: f"https://{WWW_DOMAIN}/documents/sts/st98/2025/st98-2025-executive-summary-data.xlsx",
    2026: f"https://{WWW_DOMAIN}/prd/documents/sts/ST98/2026/st98-2026-executive-summary-data.xlsx",
}
# The report (or, before 2026, its executive summary) each workbook belongs to.
ST98_REPORTS = {
    2022: f"https://{WWW_DOMAIN}/documents/sts/st98/2022/ST982022_ExecutiveSummary.pdf",
    2023: f"https://{WWW_DOMAIN}/documents/sts/ST98/2023/ST98_executive_summary.pdf",
    2024: f"https://{WWW_DOMAIN}/documents/sts/st98/st98-2024-executive-summary.pdf",
    2025: f"https://{WWW_DOMAIN}/documents/sts/st98/2025/st98-2025-executive-summary-final.pdf",
    2026: f"https://{WWW_DOMAIN}/prd/documents/sts/st98/2026/st98-2026-alberta-energy-outlook.pdf",
}
# Each workbook is 1.7-1.9 MB (2026-11-07).
ST98_MAX_WORKBOOK_BYTES = 8 * 1024 * 1024
ST98_MAX_SHEET_ROWS = 400
ST98_MAX_SHEET_COLUMNS = 250
# One edition a year, around June; a day keeps a corrected re-post visible.
CACHE_TTL_ST98_SECONDS = 24 * 60 * 60

# The workbooks label each block only "Figure 8", so titles come from the
# figure captions of the edition's report. 2022-2025 share one numbering
# (checked against each executive summary PDF; 2025 adds "base case vs.
# tariff case" columns); the 2026 workbook has 15 figures against the
# report's 7, so its titles describe each block's own headers and values
# (Figure 5 is WTI: US$84/bbl in 2026, against the report's WCS US$71).
_ST98_TITLES_2022_2025 = {
    "figure_1": ("Canadian oil price differentials", "Écarts de prix du pétrole canadien"),
    "figure_2": (
        "Marketable natural gas percentage of production, Canada",
        "Part de la production de gaz naturel commercialisable, Canada",
    ),
    "figure_3": (
        "Oil and equivalent percentage of production, Canada",
        "Part de la production de pétrole et équivalents, Canada",
    ),
    "figure_4": ("Price of West Texas Intermediate (WTI)", "Prix du West Texas Intermediate (WTI)"),
    "figure_5": ("Henry Hub natural gas price", "Prix du gaz naturel au Henry Hub"),
    "figure_6": (
        "Alberta oil and gas, oil sands, and emerging resources capital expenditure",
        (
            "Dépenses en immobilisations de l'Alberta : pétrole et gaz, sables bitumineux et "
            "ressources émergentes"
        ),
    ),
    "figure_7": (
        "Total primary energy production in Alberta",
        "Production totale d'énergie primaire en Alberta",
    ),
    "figure_8": (
        "Alberta supply of crude oil and equivalent",
        "Offre de pétrole brut et équivalents en Alberta",
    ),
    "figure_9": (
        "Percentage of mined and in situ bitumen sent for upgrading in Alberta",
        (
            "Part du bitume extrait par exploitation minière et in situ envoyé à la valorisation "
            "en Alberta"
        ),
    ),
    "figure_10": ("Primary energy demand in Alberta", "Demande d'énergie primaire en Alberta"),
    "figure_11": (
        "Primary energy removals from Alberta",
        "Sorties d'énergie primaire de l'Alberta",
    ),
    "figure_12": ("Total oil removals from Alberta", "Sorties totales de pétrole de l'Alberta"),
    "figure_13": (
        "Historical drilling activity in Alberta",
        "Activité de forage historique en Alberta",
    ),
}
ST98_TITLES: dict[int, dict[str, tuple[str, str]]] = {
    2022: _ST98_TITLES_2022_2025,
    2023: _ST98_TITLES_2022_2025,
    2024: _ST98_TITLES_2022_2025,
    2025: _ST98_TITLES_2022_2025,
    2026: {
        "figure_1": (
            "WTI and WCS crude oil prices and the WTI-WCS differential, monthly",
            "Prix du pétrole brut WTI et WCS et écart WTI-WCS, mensuels",
        ),
        "figure_2": _ST98_TITLES_2022_2025["figure_2"],
        "figure_3": _ST98_TITLES_2022_2025["figure_3"],
        "figure_4": (
            "North American crude oil production: Alberta, rest of Canada, U.S. and Mexico",
            (
                "Production de pétrole brut en Amérique du Nord : Alberta, reste du Canada, "
                "États-Unis et Mexique"
            ),
        ),
        "figure_5": _ST98_TITLES_2022_2025["figure_4"],
        "figure_6": _ST98_TITLES_2022_2025["figure_5"],
        "figure_7": _ST98_TITLES_2022_2025["figure_6"],
        "figure_8": _ST98_TITLES_2022_2025["figure_7"],
        "figure_9": _ST98_TITLES_2022_2025["figure_8"],
        "figure_10": _ST98_TITLES_2022_2025["figure_9"],
        "figure_11": _ST98_TITLES_2022_2025["figure_10"],
        "figure_12": _ST98_TITLES_2022_2025["figure_11"],
        "figure_13": _ST98_TITLES_2022_2025["figure_12"],
        "figure_14": _ST98_TITLES_2022_2025["figure_13"],
        "figure_15": (
            "Surface-location wells drilled in Alberta",
            "Puits forés par emplacement en surface en Alberta",
        ),
    },
}
