"""Constants for the US Bureau of Economic Analysis module (BEA Data API).

Parameters, response shapes, error codes and throttling read on 2026-11-07
from the BEA API user guide (apps.bea.gov/api/_pdf/bea_web_service_api_user_guide.pdf,
dated April 20, 2026) and the terms of service (apps.bea.gov/API/_pdf/bea_api_tos.pdf).
Not yet checked against live responses: the API refuses every request
without a UserID, and none was available when the module was written.
"""

from __future__ import annotations

BASE_URL = "https://apps.bea.gov/api/data/"
SOURCE = "bea"
KEY_PLACEHOLDER = "YOUR_BEA_API_KEY"
SIGNUP_URL = "https://apps.bea.gov/api/signup/"
SCHEDULE_URL = "https://www.bea.gov/news/schedule"

# User guide, "API Calling Limits": 100 requests, 100 MB and 30 errors per
# minute; exceeding one refuses the UserID for a timeout period ("currently
# one minute") with HTTP 429, a Retry-After header and APIErrorCode 7.
RATE_LIMIT_SOURCE = "bea"
RATE_LIMIT_PER_SECOND = 1.0
RATE_LIMIT_CAPACITY = 5.0
TIMEOUT_SECONDS = 60.0

CACHE_TTL_DATA_SECONDS = 6 * 60 * 60
CACHE_TTL_LIST_SECONDS = 24 * 60 * 60

MAX_ROWS = 5_000

LICENCE = (
    "Source: U.S. Bureau of Economic Analysis (https://www.bea.gov/). This product uses the "
    "Bureau of Economic Analysis (BEA) Data API but is not endorsed or certified by BEA. "
    "BEA statistics are works of the U.S. government; BEA asks that citations name it and "
    "the table, with the access date (https://www.bea.gov/help/guidelines-for-citing-bea). "
    "API terms: https://apps.bea.gov/API/_pdf/bea_api_tos.pdf."
)
LICENCE_FR = (
    "Source : Bureau of Economic Analysis des États-Unis (https://www.bea.gov/). Ce produit "
    "utilise l'API de données du Bureau of Economic Analysis (BEA), sans être approuvé ni "
    "certifié par le BEA. Les statistiques du BEA sont des œuvres du gouvernement des "
    "États-Unis ; le BEA demande que les citations le nomment avec le tableau et la date de "
    "consultation (https://www.bea.gov/help/guidelines-for-citing-bea, en anglais). "
    "Conditions de l'API : https://apps.bea.gov/API/_pdf/bea_api_tos.pdf."
)

# NIPA tables most comparisons need, for docstrings and notes (user guide
# appendix B lists every TableName).
NIPA_TABLES: dict[str, tuple[str, str]] = {
    "T10101": (
        "Percent change from preceding period in real GDP and its components",
        "Variation en pourcentage du PIB réel et de ses composantes",
    ),
    "T10105": ("Gross domestic product, current dollars", "Produit intérieur brut, dollars courants"),
    "T10106": ("Real GDP, chained dollars", "PIB réel, dollars enchaînés"),
    "T10111": (
        "Percent change from the same period a year earlier in real GDP",
        "Variation en pourcentage du PIB réel sur un an",
    ),
    "T20100": (
        "Personal income and its disposition", "Revenu personnel et son affectation",
    ),
    "T20600": (
        "Personal income and its disposition, monthly",
        "Revenu personnel et son affectation, mensuel",
    ),
    "T20804": (
        "Price indexes for personal consumption expenditures (PCE), monthly",
        "Indices des prix des dépenses de consommation personnelle (PCE), mensuels",
    ),
    "T40100": (
        "Foreign transactions in the NIPAs (exports and imports)",
        "Opérations avec le reste du monde (exportations et importations)",
    ),
}  # fmt: skip

# ITA indicators for trade with one country. The guide names BalGds; the
# others follow the same pattern and must be confirmed with
# bea_list_parameter_values(dataset="ITA", parameter="Indicator") once a key
# is available.
TRADE_INDICATORS = (
    "ExpGdsServ",
    "ImpGdsServ",
    "BalGdsServ",
    "ExpGds",
    "ImpGds",
    "BalGds",
    "ExpServ",
    "ImpServ",
    "BalServ",
)

DATASETS = {
    "NIPA",
    "NIUnderlyingDetail",
    "MNE",
    "FixedAssets",
    "ITA",
    "IIP",
    "InputOutput",
    "IntlServTrade",
    "IntlServSTA",
    "GDPbyIndustry",
    "Regional",
    "UnderlyingGDPbyIndustry",
    "APIDatasetMetaData",
}
