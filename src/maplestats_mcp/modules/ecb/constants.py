"""Constants for the European Central Bank Data Portal module.

Endpoints, keys and terms checked live on 2026-11-07 (see client.py's module
docstring). No key or registration.
"""

from __future__ import annotations

from dataclasses import dataclass

BASE_URL = "https://data-api.ecb.europa.eu/service/"
PORTAL_URL = "https://data.ecb.europa.eu/data/datasets/"
SOURCE = "ecb"
AGENCY = "ECB"

# ESCB reuse policy (https://www.ecb.europa.eu/stats/ecb_statistics/
# governance_and_quality_framework/html/usage_policy.en.html, read 2026-11-07):
# free reuse, commercial included, with the source quoted ("Source: ECB
# statistics"), statistics not modified; third-party data need the
# originator's permission.
LICENCE = (
    "Source: ECB statistics, European Central Bank Data Portal (https://data.ecb.europa.eu/). "
    "ESCB reuse policy (https://www.ecb.europa.eu/stats/ecb_statistics/"
    "governance_and_quality_framework/html/usage_policy.en.html): free of charge for "
    "commercial and non-commercial use, provided the source is quoted and the statistics are "
    "not modified; data the ECB takes from third parties need their originator's permission."
)
LICENCE_FR = (
    "Source : statistiques de la BCE, portail de données de la Banque centrale européenne "
    "(https://data.ecb.europa.eu/). Politique de réutilisation du SEBC "
    "(https://www.ecb.europa.eu/stats/ecb_statistics/governance_and_quality_framework/html/"
    "usage_policy.en.html, en anglais) : gratuite pour un usage commercial ou non, si la "
    "source est citée et les statistiques ne sont pas modifiées ; les données que la BCE "
    "tient de tiers exigent l'autorisation de leur auteur."
)

# No published rate limit and no rate-limit headers on 2026-11-07.
RATE_LIMIT_SOURCE = "ecb"
RATE_LIMIT_PER_SECOND = 2.0
RATE_LIMIT_CAPACITY = 4.0

STRUCTURE_TIMEOUT_SECONDS = 90.0
DATA_TIMEOUT_SECONDS = 60.0

CACHE_TTL_CATALOGUE_SECONDS = 24 * 60 * 60
CACHE_TTL_STRUCTURE_SECONDS = 24 * 60 * 60
CACHE_TTL_DATA_SECONDS = 2 * 60 * 60

DATA_ACCEPT = "text/csv"
STRUCTURE_ACCEPT = "application/vnd.sdmx.structure+xml;version=2.1"

MAX_CODES_PER_DIMENSION = 300
MAX_SERIES = 50
MAX_ROWS = 10_000
MAX_LAST_N = 5_000
MAX_LISTED_SERIES = 200
# Structures run to 23 MB (FM); a larger answer is refused, not parsed.
MAX_STRUCTURE_BYTES = 60_000_000
MAX_SERIES_LIST_BYTES = 30_000_000

# One line per dataset, English and French, for the datasets most asked for.
DATASET_NOTES: dict[str, tuple[str, str]] = {
    "FM": (
        (
            "Financial market data: ECB key interest rates (deposit facility, main refinancing, "
            "marginal lending), government bond yields, money market rates."
        ),
        (
            "Données des marchés financiers : taux directeurs de la BCE (facilité de dépôt, "
            "opérations principales de refinancement, facilité de prêt marginal), rendements des "
            "obligations d'État, taux du marché monétaire."
        ),
    ),
    "EST": (
        "Euro short-term rate (€STR), daily, with volumes and percentiles.",
        "Taux à court terme de l'euro (€STR), quotidien, avec volumes et percentiles.",
    ),
    "EXR": (
        (
            "Exchange rates: euro foreign exchange reference rates (including EUR/CAD and "
            "EUR/USD), daily, monthly, quarterly and annual, and effective exchange rates."
        ),
        (
            "Taux de change : taux de référence de l'euro (dont EUR/CAD et EUR/USD), quotidiens, "
            "mensuels, trimestriels et annuels, et taux de change effectifs."
        ),
    ),
    "HICP": (
        (
            "Harmonised Index of Consumer Prices, COICOP 2018 (from 2026): euro area and member "
            "states, index and annual rates, headline and core."
        ),
        (
            "Indice des prix à la consommation harmonisé, COICOP 2018 (depuis 2026) : zone euro et "
            "États membres, indice et taux annuels, global et de base."
        ),
    ),
    "ICP": (
        (
            "Harmonised Index of Consumer Prices, previous classification; ends in December 2025 "
            "(use HICP)."
        ),
        (
            "Indice des prix à la consommation harmonisé, ancienne classification ; s'arrête en "
            "décembre 2025 (utiliser HICP)."
        ),
    ),
    "BSI": (
        (
            "Balance sheet items of monetary financial institutions: monetary aggregates M1, M2, "
            "M3, loans to households and firms, deposits."
        ),
        (
            "Postes du bilan des institutions financières monétaires : agrégats monétaires M1, M2, "
            "M3, prêts aux ménages et aux entreprises, dépôts."
        ),
    ),
    "MIR": (
        "MFI interest rates on loans and deposits (mortgage rates, business loan rates).",
        (
            "Taux d'intérêt des IFM sur les prêts et les dépôts (taux hypothécaires, taux des prêts "
            "aux entreprises)."
        ),
    ),
    "YC": (
        "Euro area government yield curve, daily.",
        "Courbe des rendements des obligations d'État de la zone euro, quotidienne.",
    ),
    "BLS": (
        "Euro area Bank Lending Survey: credit standards and loan demand.",
        (
            "Enquête sur la distribution du crédit bancaire dans la zone euro : critères d'octroi "
            "et demande de prêts."
        ),
    ),
    "RPP": (
        "Residential property prices.",
        "Prix de l'immobilier résidentiel.",
    ),
    "SPF": (
        "Survey of Professional Forecasters: inflation, growth and unemployment expectations.",
        (
            "Enquête auprès des prévisionnistes professionnels : attentes d'inflation, de croissance "
            "et de chômage."
        ),
    ),
    "MPD": (
        "Macroeconomic projections of Eurosystem and ECB staff.",
        "Projections macroéconomiques des services de l'Eurosystème et de la BCE.",
    ),
    "BOP": (
        "Euro area balance of payments and international investment position.",
        "Balance des paiements et position extérieure globale de la zone euro.",
    ),
    "GST": (
        "Government finance statistics: deficit, debt, revenue and expenditure.",
        "Statistiques de finances publiques : déficit, dette, recettes et dépenses.",
    ),
    "CISS": (
        "Composite Indicator of Systemic Stress.",
        "Indicateur composite de tension systémique.",
    ),
    "STS": (
        "Short-term statistics: industrial production, retail trade, unemployment.",
        "Statistiques conjoncturelles : production industrielle, commerce de détail, chômage.",
    ),
}


@dataclass(frozen=True)
class Indicator:
    dataset: str
    key: str
    label_en: str
    label_fr: str
    pair_en: str
    pair_fr: str


# Every key checked live on 2026-11-07.
INDICATORS: dict[str, Indicator] = {
    "deposit_facility_rate": Indicator(
        "FM",
        "B.U2.EUR.4F.KR.DFR.LEV",
        "ECB deposit facility rate, dates of changes (per cent per year)",
        "Taux de la facilité de dépôt de la BCE, dates des changements (pour cent par année)",
        "The Bank of Canada's target for the overnight rate (boc_get_series V39079).",
        "La cible de la Banque du Canada pour le taux du financement à un jour "
        "(boc_get_series V39079).",
    ),
    "main_refinancing_rate": Indicator(
        "FM",
        "B.U2.EUR.4F.KR.MRR_FR.LEV",
        "ECB main refinancing operations rate, dates of changes (per cent per year)",
        "Taux des opérations principales de refinancement de la BCE, dates des changements "
        "(pour cent par année)",
        "The Bank of Canada's target for the overnight rate (boc_get_series V39079).",
        "La cible de la Banque du Canada pour le taux du financement à un jour "
        "(boc_get_series V39079).",
    ),
    "marginal_lending_rate": Indicator(
        "FM",
        "B.U2.EUR.4F.KR.MLFR.LEV",
        "ECB marginal lending facility rate, dates of changes (per cent per year)",
        "Taux de la facilité de prêt marginal de la BCE, dates des changements (pour cent par "
        "année)",
        "The Bank of Canada's bank rate, the ceiling of its operating band (boc_search_series).",
        "Le taux d'escompte de la Banque du Canada, plafond de sa fourchette opérationnelle "
        "(boc_search_series).",
    ),
    "estr": Indicator(
        "EST",
        "B.EU000A2X2A25.WT",
        "Euro short-term rate (€STR), volume-weighted trimmed mean, business days (per cent)",
        "Taux à court terme de l'euro (€STR), moyenne tronquée pondérée, jours ouvrables "
        "(pour cent)",
        "CORRA, the Canadian overnight repo rate average (boc_get_series AVG.INTWO).",
        "Le CORRA, taux moyen des opérations de pension à un jour au Canada (boc_get_series "
        "AVG.INTWO).",
    ),
    "eur_cad": Indicator(
        "EXR",
        "D.CAD.EUR.SP00.A",
        "Canadian dollars per euro, ECB reference rate (2.15 pm CET), daily",
        "Dollars canadiens par euro, taux de référence de la BCE (14 h 15 HEC), quotidien",
        "Bank of Canada daily rate FXEURCAD (boc_get_series).",
        "Taux quotidien FXEURCAD de la Banque du Canada (boc_get_series).",
    ),
    "eur_cad_monthly": Indicator(
        "EXR",
        "M.CAD.EUR.SP00.A",
        "Canadian dollars per euro, ECB reference rate, monthly average",
        "Dollars canadiens par euro, taux de référence de la BCE, moyenne mensuelle",
        "Bank of Canada monthly average FXMEURCAD (boc_get_series).",
        "Moyenne mensuelle FXMEURCAD de la Banque du Canada (boc_get_series).",
    ),
    "eur_usd": Indicator(
        "EXR",
        "D.USD.EUR.SP00.A",
        "US dollars per euro, ECB reference rate (2.15 pm CET), daily",
        "Dollars américains par euro, taux de référence de la BCE (14 h 15 HEC), quotidien",
        "Bank of Canada daily rates FXEURCAD and FXUSDCAD (boc_get_series).",
        "Taux quotidiens FXEURCAD et FXUSDCAD de la Banque du Canada (boc_get_series).",
    ),
    "hicp_inflation": Indicator(
        "HICP",
        "M.U2.N.000000.4D0.ANR",
        "Euro area HICP inflation, all items, annual rate of change (per cent), monthly",
        "Inflation de l'IPCH de la zone euro, ensemble, taux annuel (pour cent), mensuel",
        "Statistics Canada's CPI, all items, 12-month change (table 18-10-0004-01).",
        "L'IPC de Statistique Canada, ensemble, variation sur 12 mois (tableau 18-10-0004-01).",
    ),
    "hicp_core_inflation": Indicator(
        "HICP",
        "M.U2.N.XEF000.4D0.ANR",
        "Euro area HICP excluding energy, food, alcohol and tobacco, annual rate (per cent), "
        "monthly",
        "IPCH de la zone euro hors énergie, alimentation, alcool et tabac, taux annuel (pour "
        "cent), mensuel",
        "The Bank of Canada's core inflation measures CPI-trim and CPI-median "
        "(boc_search_series 'CPI-trim').",
        "Les mesures de l'inflation fondamentale de la Banque du Canada, IPC-tronq et IPC-méd "
        "(boc_search_series « IPC-tronq »).",
    ),
    "m3_growth": Indicator(
        "BSI",
        "M.U2.Y.V.M30.X.I.U2.2300.Z01.A",
        "Euro area M3, annual growth rate (per cent), monthly",
        "M3 de la zone euro, taux de croissance annuel (pour cent), mensuel",
        "Bank of Canada monetary aggregates, M2++ (boc_search_series 'M2++').",
        "Les agrégats monétaires de la Banque du Canada, M2++ (boc_search_series « M2++ »).",
    ),
    "household_loan_growth": Indicator(
        "BSI",
        "M.U2.Y.U.A20T.A.I.U2.2250.Z01.A",
        "Adjusted loans to euro area households, annual growth rate (per cent), monthly",
        "Prêts ajustés aux ménages de la zone euro, taux de croissance annuel (pour cent), mensuel",
        "Bank of Canada household credit (boc_search_series 'household credit').",
        "Le crédit aux ménages de la Banque du Canada (boc_search_series « crédit aux ménages »).",
    ),
    "mortgage_rate": Indicator(
        "MIR",
        "M.U2.B.A2C.A.R.A.2250.EUR.N",
        "Euro area bank rate on new loans to households for house purchase (per cent per "
        "year), monthly",
        "Taux des banques de la zone euro sur les nouveaux prêts aux ménages pour l'achat d'un "
        "logement (pour cent par année), mensuel",
        "Canadian chartered banks' mortgage rates (boc_search_series 'mortgage rate').",
        "Les taux hypothécaires des banques à charte canadiennes (boc_search_series « taux "
        "hypothécaire »).",
    ),
    "euro_area_10y_yield": Indicator(
        "FM",
        "M.U2.EUR.4F.BB.U2_10Y.YLD",
        "Euro area 10-year government benchmark bond yield (per cent per year), monthly",
        "Rendement de l'obligation d'État de référence à 10 ans de la zone euro (pour cent par "
        "année), mensuel",
        "Government of Canada 10-year benchmark bond yield (boc_get_series BD.CDN.10YR.DQ.YLD).",
        "Rendement de l'obligation de référence du gouvernement du Canada à 10 ans "
        "(boc_get_series BD.CDN.10YR.DQ.YLD).",
    ),
}
