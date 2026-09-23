"""Constants for NRCan's National Energy Use Database (OEE) pages.

Confirmed live 2026-09-23:
- Every table is `showTable.cfm?type=..&sector=..&juris=..[&year=..]&rn=..&page=..`
  under `/corporate/statistics/neud/dpa/` (English) or
  `/organisme/statistiques/bnce/apd/` (French, same parameters).
- Product menus list tables as `<a>Table 1.1a</a>` followed by a sibling
  `<div>` holding the title. French menus do not carry the same links,
  so tables are always listed from the English menus.
- Comprehensive Energy Use Database menus are
  `menus/trends/comprehensive/trends_{sector}_{juris}.cfm`; the valid
  sector/jurisdiction pairs are discovered from its list page.
- SHEU tables follow every value with a quality letter (A-E, F, M, U).
- An HTML parser decodes `&sect` in `&sector=` as "§", so raw hrefs are
  read with that entity restored.
"""

EN_ROOT = "https://oee.nrcan.gc.ca/corporate/statistics/neud/dpa/"
FR_ROOT = "https://oee.nrcan.gc.ca/organisme/statistiques/bnce/apd/"
COMPREHENSIVE_LIST = "menus/trends/comprehensive_tables/list.cfm"
COMPREHENSIVE_MENU = "menus/trends/comprehensive/trends_{sector}_{jurisdiction}.cfm"

# product key -> (English name, French name, menu path relative to EN_ROOT)
SURVEYS: dict[str, tuple[str, str, str]] = {
    "sheu_2019": (
        "Survey of Household Energy Use (SHEU), 2019",
        "Enquête sur l'utilisation de l'énergie par les ménages (EUEM), 2019",
        "menus/sheu/2019/tables.cfm",
    ),
    "sheu_2015": (
        "Survey of Household Energy Use (SHEU), 2015",
        "Enquête sur l'utilisation de l'énergie par les ménages (EUEM), 2015",
        "menus/sheu/2015/tables.cfm",
    ),
    "sheu_cma_2019": (
        "SHEU by Census Metropolitan Area, 2019",
        "EUEM par région métropolitaine de recensement, 2019",
        "menus/sheu-cma/2019/tables.cfm",
    ),
    "sheu_cma_2015": (
        "SHEU by Census Metropolitan Area, 2015",
        "EUEM par région métropolitaine de recensement, 2015",
        "menus/sheu-cma/2015/tables.cfm",
    ),
    "murb_2018": (
        "Survey of Energy Consumption of Multi-Unit Residential Buildings, 2018",
        "Enquête sur la consommation d'énergie des immeubles résidentiels à logements multiples, 2018",
        "menus/murb/2018/tables.cfm",
    ),
    "scieu_2019": (
        "Survey of Commercial and Institutional Energy Use (SCIEU), 2019",
        "Enquête sur l'utilisation commerciale et institutionnelle d'énergie (EUCIE), 2019",
        "menus/scieu/2019/tables.cfm",
    ),
    "scieu_2014": (
        "Survey of Commercial and Institutional Energy Use (SCIEU), 2014",
        "Enquête sur l'utilisation commerciale et institutionnelle d'énergie (EUCIE), 2014",
        "menus/scieu/2014/tables.cfm",
    ),
    "scieu_2009": (
        "Survey of Commercial and Institutional Energy Use (SCIEU), 2009",
        "Enquête sur l'utilisation commerciale et institutionnelle d'énergie (EUCIE), 2009",
        "menus/scieu/2009/tables.cfm",
    ),
    "seca_2014": (
        "Survey of Energy Consumption of Arenas (SECA), 2014",
        "Enquête sur la consommation d'énergie des arénas, 2014",
        "menus/seca/2014/tables.cfm",
    ),
    "ice_2020": (
        "Industrial Consumption of Energy (ICE), 2000-2020",
        "Consommation industrielle d'énergie (CIE), 2000-2020",
        "menus/ice/2020/tables.cfm",
    ),
    "aham_2021": (
        "Energy Consumption of Major Household Appliances Shipped in Canada, 2021",
        "Consommation d'énergie des principaux appareils ménagers expédiés au Canada, 2021",
        "menus/aham/2021/tables.cfm",
    ),
}

SECTORS = {
    "agg": ("All sectors (aggregate)", "Tous les secteurs (total)"),
    "res": ("Residential", "Résidentiel"),
    "com": ("Commercial/institutional", "Commercial et institutionnel"),
    "id": ("Industrial", "Industriel"),
    "tran": ("Transportation", "Transports"),
    "agr": ("Agriculture", "Agriculture"),
}

JURISDICTIONS = {
    "ca": ("Canada", "Canada"),
    "atl": ("Atlantic provinces", "Provinces de l'Atlantique"),
    "nf": ("Newfoundland and Labrador", "Terre-Neuve-et-Labrador"),
    "pei": ("Prince Edward Island", "Île-du-Prince-Édouard"),
    "ns": ("Nova Scotia", "Nouvelle-Écosse"),
    "nb": ("New Brunswick", "Nouveau-Brunswick"),
    "qc": ("Quebec", "Québec"),
    "on": ("Ontario", "Ontario"),
    "mb": ("Manitoba", "Manitoba"),
    "sk": ("Saskatchewan", "Saskatchewan"),
    "ab": ("Alberta", "Alberta"),
    "bc": ("British Columbia", "Colombie-Britannique"),
    "bct": ("British Columbia and territories", "Colombie-Britannique et territoires"),
    "tr": ("Territories", "Territoires"),
}

TABLE_PARAMS = ("type", "sector", "juris", "year", "rn", "page")

RATE_LIMIT_SOURCE = "nrcan-energy-use"
RATE_LIMIT_PER_SECOND = 2.0
RATE_LIMIT_CAPACITY = 4.0

CACHE_TTL_MENU_SECONDS = 7 * 24 * 60 * 60
CACHE_TTL_TABLE_SECONDS = 24 * 60 * 60
