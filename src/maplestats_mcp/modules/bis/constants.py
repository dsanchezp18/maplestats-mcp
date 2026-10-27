"""Constants for the Bank for International Settlements statistics module.

Endpoints, media types and key layouts checked live on 2026-10-26 (see
client.py's module docstring).
"""

from __future__ import annotations

from dataclasses import dataclass

BASE_URL = "https://stats.bis.org/api/v2/"
SOURCE = "bis"
AGENCY = "BIS"

# The v2 API refuses SDMX-JSON for data (406) but serves SDMX-CSV 2.0;
# `labels=both` writes each code as "CA: Canada" and each column header as
# "REF_AREA:Reference area". Structures come as SDMX-JSON 1.0.0 only
# ("version=1.0" without the patch number answers 406).
DATA_ACCEPT = "application/vnd.sdmx.data+csv;version=2.0.0;labels=both"
STRUCTURE_ACCEPT = "application/vnd.sdmx.structure+json;version=1.0.0"

LICENCE = (
    "Source: Bank for International Settlements, BIS Data Portal "
    "(https://data.bis.org/). BIS terms (https://data.bis.org/help/legal): use of the "
    "statistics is unrestricted provided the BIS is cited as the source, the use is not "
    "misleading, translations are identified as such, and statistics included in a "
    "commercial product are not charged for separately."
)
LICENCE_FR = (
    "Source : Banque des règlements internationaux, portail de données de la BRI "
    "(https://data.bis.org/). Conditions de la BRI (https://data.bis.org/help/legal, en "
    "anglais) : l'utilisation des statistiques est libre si la BRI est citée comme "
    "source, si l'utilisation n'est pas trompeuse, si les traductions sont signalées "
    "comme telles et si les statistiques incluses dans un produit commercial ne sont pas "
    "facturées séparément."
)

# No published rate limit and no rate-limit headers on 2026-10-26; structure
# calls took 1 to 12 s (WS_EER's), so pace gently.
RATE_LIMIT_SOURCE = "bis"
RATE_LIMIT_PER_SECOND = 2.0
RATE_LIMIT_CAPACITY = 4.0

STRUCTURE_TIMEOUT_SECONDS = 60.0
DATA_TIMEOUT_SECONDS = 60.0

# Datasets are updated on the BIS release calendar (most quarterly, policy
# rates and exchange rates weekly or daily).
CACHE_TTL_CATALOGUE_SECONDS = 24 * 60 * 60
CACHE_TTL_STRUCTURE_SECONDS = 24 * 60 * 60
CACHE_TTL_DATA_SECONDS = 6 * 60 * 60

# A dimension of the banking datasets lists 244 areas; the cap keeps a
# description readable while covering every dimension seen on 2026-10-26.
MAX_CODES_PER_DIMENSION = 300
MAX_SERIES = 200
MAX_OBSERVATIONS = 10_000
MAX_LAST_N = 1_000
MAX_KEY_BOUND = 1_000_000

CANADA = "CA"
G7 = ("CA", "US", "GB", "FR", "DE", "IT", "JP")

EURO_AREA_MEMBERS = frozenset(
    {"AT", "BE", "CY", "DE", "EE", "ES", "FI", "FR", "GR", "HR", "IE", "IT", "LT", "LU", "LV",
     "MT", "NL", "PT", "SI", "SK"}
)  # fmt: skip

# Shortcuts accepted in `compare_with`, besides two-letter BIS area codes.
GROUP_ALIASES: dict[str, tuple[str, ...]] = {
    "G7": G7,
    "EURO_AREA": ("XM",),
}

# One line per dataset, in English and French, for bis_list_datasets. The
# API's own names are short ("CPMI macro") and English only.
DATASET_NOTES: dict[str, tuple[str, str]] = {
    "BIS_REL_CAL": (
        "Release calendar of the BIS statistics.",
        "Calendrier de diffusion des statistiques de la BRI.",
    ),
    "WS_CBPOL": (
        "Central bank policy rates, about 40 central banks, daily and monthly, Canada from 1960.",
        (
            "Taux directeurs d'environ 40 banques centrales, quotidiens et mensuels, Canada "
            "depuis 1960."
        ),
    ),
    "WS_CBS_PUB": (
        (
            "Consolidated banking statistics: banks' worldwide claims by nationality of the "
            "reporting bank."
        ),
        (
            "Statistiques bancaires consolidées : créances mondiales des banques selon la "
            "nationalité de la banque déclarante."
        ),
    ),
    "WS_CBTA": (
        "Central bank total assets.",
        "Total de l'actif des banques centrales.",
    ),
    "WS_CPMI_CASHLESS": (
        (
            "CPMI cashless payments: volume and value of card, credit transfer, direct debit "
            "and cheque payments."
        ),
        (
            "Paiements scripturaux du CPIM : volume et valeur des paiements par carte, "
            "virement, prélèvement et chèque."
        ),
    ),
    "WS_CPMI_CT1": (
        "CPMI comparative tables, type 1.",
        "Tableaux comparatifs du CPIM, type 1.",
    ),
    "WS_CPMI_CT2": (
        "CPMI comparative tables, type 2.",
        "Tableaux comparatifs du CPIM, type 2.",
    ),
    "WS_CPMI_DEVICES": (
        "CPMI payment devices: cards, ATMs and point-of-sale terminals.",
        (
            "Instruments de paiement du CPIM : cartes, guichets automatiques et terminaux de "
            "point de vente."
        ),
    ),
    "WS_CPMI_INSTITUT": (
        "CPMI institutions offering payment services.",
        "Établissements offrant des services de paiement (CPIM).",
    ),
    "WS_CPMI_MACRO": (
        "CPMI macroeconomic context: population, GDP, banknotes and coins in circulation.",
        "Contexte macroéconomique du CPIM : population, PIB, billets et pièces en circulation.",
    ),
    "WS_CPMI_PARTICIP": (
        "CPMI participants in payment systems.",
        "Participants aux systèmes de paiement (CPIM).",
    ),
    "WS_CPMI_SYSTEMS": (
        (
            "CPMI payment systems: number and value of transactions by system (for Canada, "
            "the ACSS, Interac e-Transfer, CDS and CDCC), annual."
        ),
        (
            "Systèmes de paiement du CPIM : nombre et valeur des opérations par système (au "
            "Canada, le SACR, Virement Interac, la CDS et la CDCC), annuels."
        ),
    ),
    "WS_CPP": (
        "Commercial property prices.",
        "Prix de l'immobilier commercial.",
    ),
    "WS_CREDIT_GAP": (
        (
            "Credit-to-GDP ratios, trends and gaps (an early-warning indicator of banking "
            "stress), quarterly."
        ),
        (
            "Ratios crédit/PIB, tendances et écarts (indicateur avancé de tensions "
            "bancaires), trimestriels."
        ),
    ),
    "WS_DEBT_SEC2_PUB": (
        "International debt securities, BIS-compiled.",
        "Titres de créance internationaux, compilés par la BRI.",
    ),
    "WS_DER_OTC_TOV": (
        "OTC derivatives turnover (Triennial Survey).",
        "Volume des opérations sur dérivés de gré à gré (enquête triennale).",
    ),
    "WS_DPP": (
        "Detailed residential property prices, as published by each country.",
        "Prix détaillés de l'immobilier résidentiel, tels que publiés par chaque pays.",
    ),
    "WS_DSR": (
        (
            "Debt service ratios of households, non-financial corporations and the private "
            "sector, quarterly."
        ),
        (
            "Ratios du service de la dette des ménages, des sociétés non financières et du "
            "secteur privé, trimestriels."
        ),
    ),
    "WS_EER": (
        "Nominal and real effective exchange rates, broad (64 economies) and narrow baskets.",
        "Taux de change effectifs nominaux et réels, paniers large (64 économies) et étroit.",
    ),
    "WS_GLI": (
        "Global liquidity indicators: credit to non-banks by currency.",
        "Indicateurs de liquidité mondiale : crédit aux non-banques par monnaie.",
    ),
    "WS_LBS_D_PUB": (
        "Locational banking statistics: cross-border and local positions of banks by residence.",
        (
            "Statistiques bancaires territoriales : positions transfrontières et locales des "
            "banques selon la résidence."
        ),
    ),
    "WS_LONG_CPI": (
        "Consumer prices, long series (index and year-on-year change), monthly and annual.",
        (
            "Prix à la consommation, longues séries (indice et variation sur un an), "
            "mensuels et annuels."
        ),
    ),
    "WS_NA_SEC_C3": (
        "BIS debt securities statistics (table C3).",
        "Statistiques des titres de créance de la BRI (tableau C3).",
    ),
    "WS_NA_SEC_DSS": (
        "Debt securities statistics: issues by residence and sector.",
        "Statistiques des titres de créance : émissions selon la résidence et le secteur.",
    ),
    "WS_OTC_DERIV2": (
        "OTC derivatives outstanding.",
        "Encours des dérivés de gré à gré.",
    ),
    "WS_SPP": (
        (
            "Selected residential property prices, nominal and real, index and year-on-year "
            "change, quarterly."
        ),
        (
            "Prix choisis de l'immobilier résidentiel, nominaux et réels, indice et variation "
            "sur un an, trimestriels."
        ),
    ),
    "WS_TC": (
        (
            "Total credit to the non-financial sector, households, corporations and "
            "government, as a share of GDP or in currency, quarterly."
        ),
        (
            "Crédit total au secteur non financier, aux ménages, aux sociétés et aux "
            "administrations publiques, en pourcentage du PIB ou en monnaie, trimestriel."
        ),
    ),
    "WS_XRU": (
        "Bilateral exchange rates against the US dollar.",
        "Taux de change bilatéraux par rapport au dollar américain.",
    ),
    "WS_XTD_DERIV": (
        "Exchange-traded derivatives.",
        "Dérivés négociés en bourse.",
    ),
}


@dataclass(frozen=True)
class Indicator:
    """A preset series for bis_compare_countries: `key` has `{area}` in place
    of the reference-area code, in the dataset's dimension order."""

    dataset: str
    key: str
    label_en: str
    label_fr: str


# Every key checked live on 2026-10-26 for Canada and the United States.
INDICATORS: dict[str, Indicator] = {
    "policy_rate": Indicator(
        "WS_CBPOL",
        "M.{area}",
        "Central bank policy rate, monthly (per cent per year)",
        "Taux directeur de la banque centrale, mensuel (pour cent par année)",
    ),
    "household_debt_service_ratio": Indicator(
        "WS_DSR",
        "Q.{area}.H",
        "Debt service ratio, households and NPISHs (per cent of income)",
        "Ratio du service de la dette, ménages et ISBLSM (pour cent du revenu)",
    ),
    "private_debt_service_ratio": Indicator(
        "WS_DSR",
        "Q.{area}.P",
        "Debt service ratio, private non-financial sector (per cent of income)",
        "Ratio du service de la dette, secteur privé non financier (pour cent du revenu)",
    ),
    "credit_to_gdp_gap": Indicator(
        "WS_CREDIT_GAP",
        "Q.{area}.P.A.C",
        "Credit-to-GDP gap, private non-financial sector (percentage points)",
        "Écart du ratio crédit/PIB, secteur privé non financier (points de pourcentage)",
    ),
    "household_credit_to_gdp": Indicator(
        "WS_TC",
        "Q.{area}.H.A.M.770.A",
        "Credit to households and NPISHs (per cent of GDP)",
        "Crédit aux ménages et ISBLSM (pour cent du PIB)",
    ),
    "private_credit_to_gdp": Indicator(
        "WS_TC",
        "Q.{area}.P.A.M.770.A",
        "Credit to the private non-financial sector (per cent of GDP)",
        "Crédit au secteur privé non financier (pour cent du PIB)",
    ),
    "government_debt_to_gdp": Indicator(
        "WS_TC",
        "Q.{area}.G.A.N.770.A",
        "General government debt at nominal value (per cent of GDP)",
        "Dette des administrations publiques à la valeur nominale (pour cent du PIB)",
    ),
    "real_house_price_growth": Indicator(
        "WS_SPP",
        "Q.{area}.R.771",
        "Real residential property prices, year-on-year change (per cent)",
        "Prix réels de l'immobilier résidentiel, variation sur un an (pour cent)",
    ),
    "nominal_house_price_growth": Indicator(
        "WS_SPP",
        "Q.{area}.N.771",
        "Nominal residential property prices, year-on-year change (per cent)",
        "Prix nominaux de l'immobilier résidentiel, variation sur un an (pour cent)",
    ),
    "real_house_price_index": Indicator(
        "WS_SPP",
        "Q.{area}.R.628",
        "Real residential property prices (index, 2010 = 100)",
        "Prix réels de l'immobilier résidentiel (indice, 2010 = 100)",
    ),
    "cpi_inflation": Indicator(
        "WS_LONG_CPI",
        "M.{area}.771",
        "Consumer prices, year-on-year change, monthly (per cent)",
        "Prix à la consommation, variation sur un an, mensuelle (pour cent)",
    ),
    "real_effective_exchange_rate": Indicator(
        "WS_EER",
        "M.R.B.{area}",
        "Real effective exchange rate, broad basket (index)",
        "Taux de change effectif réel, panier large (indice)",
    ),
    "nominal_effective_exchange_rate": Indicator(
        "WS_EER",
        "M.N.B.{area}",
        "Nominal effective exchange rate, broad basket (index)",
        "Taux de change effectif nominal, panier large (indice)",
    ),
}
