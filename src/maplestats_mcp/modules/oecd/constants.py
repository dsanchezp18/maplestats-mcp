"""Constants for the OECD Data Explorer module.

Endpoints, media types, limits and keys checked live on 2026-11-07 (see
client.py's module docstring).
"""

from __future__ import annotations

from dataclasses import dataclass

BASE_URL = "https://sdmx.oecd.org/public/rest/"
EXPLORER_URL = "https://data-explorer.oecd.org/vis"
SOURCE = "oecd"

# SDMX-CSV 2.0 with `labels=both` writes each code as "CAN: Canada" and each
# header as "REF_AREA: Reference area"; Accept-Language: fr gives French
# labels where the OECD has them. Structures come as SDMX-JSON.
DATA_ACCEPT = "application/vnd.sdmx.data+csv;version=2.0.0;labels=both"
STRUCTURE_ACCEPT = "application/vnd.sdmx.structure+json;version=1.0"

TERMS_URL = "https://www.oecd.org/en/about/terms-conditions.html"

# The OECD terms, section 3 "Data" (read 2026-11-07, last updated 2024-07-01).
# CC BY 4.0 covers OECD written content published since 2024-07-01; data have
# their own clause, with the same effect: any use, commercial included, with
# credit to the OECD, passed on to sub-licensees. Third-party data are
# excluded and are flagged in each dataset's metadata.
LICENCE = (
    "Source: OECD Data Explorer (https://data-explorer.oecd.org/). OECD Terms and Conditions, "
    f"section 3 Data ({TERMS_URL}): you may extract, copy, adapt and share the data for any "
    "purpose, commercial use included, crediting the OECD with the dataset's own citation or "
    "'OECD (year), (dataset name), (data source) DOI or URL (accessed on (date))', and passing "
    "that requirement on. Data owned by third parties or under specific terms are excluded: "
    "check the dataset's metadata."
)
LICENCE_FR = (
    "Source : Explorateur de données de l'OCDE (https://data-explorer.oecd.org/). Conditions "
    f"générales de l'OCDE, section 3 Données ({TERMS_URL}, en anglais) : vous pouvez extraire, "
    "copier, adapter et partager les données à toute fin, y compris commerciale, en citant "
    "l'OCDE avec la citation propre au jeu de données ou « OCDE (année), (nom du jeu), (source) "
    "DOI ou URL (consulté le (date)) », et en transmettant cette exigence. Les données "
    "appartenant à des tiers ou soumises à des conditions particulières sont exclues : "
    "vérifiez les métadonnées du jeu de données."
)
THIRD_PARTY_WARNING = (
    "Warning: this dataset's metadata mention third-party data or another owner ({reason}). "
    "The OECD terms exclude such data: check the owner's conditions before reusing it."
)
THIRD_PARTY_WARNING_FR = (
    "Attention : les métadonnées de ce jeu de données mentionnent des données de tiers ou un "
    "autre propriétaire ({reason}). Les conditions de l'OCDE excluent ces données : vérifiez "
    "les conditions du propriétaire avant de les réutiliser."
)

# API best practices page (dated 2026-03-18, read 2026-11-07): "60 data
# downloads per hour", over which requests are temporarily blocked;
# VPN and anonymised sources are refused. The server keeps its own budget a
# little below that, since a block stops every user of the hosted server.
DATA_DOWNLOADS_PER_HOUR = 60
DATA_BUDGET_PER_HOUR = 50
# Requests of any kind (structures too) are spaced at most 20 a minute.
RATE_LIMIT_SOURCE = "oecd"
RATE_LIMIT_PER_SECOND = 20 / 60
RATE_LIMIT_CAPACITY = 3.0
# After an HTTP 429 without Retry-After, no request is sent for this long.
COOLDOWN_SECONDS = 15 * 60

LIMITS = (
    "OECD API limits (best-practices page, 2026-03-18): 60 data downloads an hour per user, "
    "over which requests are temporarily blocked. This server spends at most "
    f"{DATA_BUDGET_PER_HOUR} an hour, spaces requests at most 20 a minute and caches answers "
    "(data 12 h, structures and the dataset list 24 h); a call that would exceed the budget "
    "fails with the wait instead of being sent. lastNObservations is refused (HTTP 413) on a "
    "few very large datasets."
)
LIMITS_FR = (
    "Limites de l'API de l'OCDE (page des bonnes pratiques, 2026-03-18) : 60 téléchargements "
    "de données par heure et par utilisateur, au-delà desquels les requêtes sont bloquées "
    f"temporairement. Ce serveur en utilise au plus {DATA_BUDGET_PER_HOUR} par heure, espace "
    "les requêtes (20 par minute au plus) et garde les réponses en cache (données 12 h, "
    "structures et liste des jeux 24 h) ; un appel qui dépasserait ce budget échoue en "
    "indiquant l'attente au lieu d'être envoyé. lastNObservations est refusé (HTTP 413) pour "
    "quelques très grands jeux de données."
)

CATALOGUE_TIMEOUT_SECONDS = 120.0
STRUCTURE_TIMEOUT_SECONDS = 60.0
DATA_TIMEOUT_SECONDS = 90.0

# Most OECD datasets are revised once or twice a year (best-practices page);
# the CLI and unit labour costs monthly or quarterly.
CACHE_TTL_CATALOGUE_SECONDS = 24 * 60 * 60
CACHE_TTL_STRUCTURE_SECONDS = 24 * 60 * 60
CACHE_TTL_DATA_SECONDS = 12 * 60 * 60

MAX_SEARCH_RESULTS = 50
MAX_DESCRIPTION_CHARS = 400
MAX_CODES_PER_DIMENSION = 300
MAX_SERIES = 200
MAX_ROWS = 10_000
MAX_LAST_N = 1_000
MAX_KEY_BOUND = 1_000_000

CANADA = "CAN"
G7 = ("CAN", "USA", "GBR", "FRA", "DEU", "ITA", "JPN")

# OECD members' ISO 3166 alpha-2 codes, so "US" or "GB" work beside "USA".
ISO2_TO_ISO3: dict[str, str] = {
    "AU": "AUS", "AT": "AUT", "BE": "BEL", "CA": "CAN", "CL": "CHL", "CO": "COL",
    "CR": "CRI", "CZ": "CZE", "DK": "DNK", "EE": "EST", "FI": "FIN", "FR": "FRA",
    "DE": "DEU", "GR": "GRC", "HU": "HUN", "IS": "ISL", "IE": "IRL", "IL": "ISR",
    "IT": "ITA", "JP": "JPN", "KR": "KOR", "LV": "LVA", "LT": "LTU", "LU": "LUX",
    "MX": "MEX", "NL": "NLD", "NZ": "NZL", "NO": "NOR", "PL": "POL", "PT": "PRT",
    "SK": "SVK", "SI": "SVN", "ES": "ESP", "SE": "SWE", "CH": "CHE", "TR": "TUR",
    "GB": "GBR", "UK": "GBR", "US": "USA",
}  # fmt: skip

GROUP_ALIASES: dict[str, tuple[str, ...]] = {"G7": G7}

# Aggregates are compared but never ranked against countries.
AGGREGATES = frozenset(
    {"OECD", "OECD_REP", "OECDE", "OECDXEA", "EA", "EA17", "EA20", "EU27_2020", "EU22OECD",
     "G7", "G20", "G4E", "NAFTA", "FEDOECD", "UNIOECD", "WLD", "DAE", "OTO"}
)  # fmt: skip


@dataclass(frozen=True)
class Indicator:
    """A preset series for oecd_compare_countries: `key` has `{area}` in place
    of the reference-area code, in the dataflow's dimension order."""

    agency: str
    dataflow: str
    key: str
    label_en: str
    label_fr: str
    default_last_n: int
    # The series' own unit label where the OECD's misleads (a growth rate
    # labelled "National currency per hour").
    unit_en: str | None = None
    unit_fr: str | None = None
    note_en: str | None = None
    note_fr: str | None = None


# Every key checked live on 2026-11-07 for Canada (scripts/smoke_test_oecd.py
# runs each against the G7).
INDICATORS: dict[str, Indicator] = {
    "real_gdp_growth": Indicator(
        "OECD.ECO.MAD",
        "DSD_EO@DF_EO",
        "{area}.GDPV_ANNPCT.A",
        "Real GDP growth, Economic Outlook history and projections (per cent)",
        "Croissance du PIB réel, historique et projections des Perspectives économiques (%)",
        8,
    ),
    "inflation": Indicator(
        "OECD.ECO.MAD",
        "DSD_EO@DF_EO",
        # Each country has one of the two on 2026-11-07: the national CPI for
        # Canada, the US and Japan, the HICP for European countries.
        "{area}.CPI_YTYPCT+CPIH_YTYPCT.A",
        "Headline inflation, Economic Outlook history and projections (per cent)",
        "Inflation globale, historique et projections des Perspectives économiques (%)",
        8,
        note_en=(
            "Headline inflation is the national consumer price index for Canada, the United "
            "States and Japan and the harmonised index (HICP) for European countries, as the "
            "OECD publishes it."
        ),
        note_fr=(
            "L'inflation globale est l'indice national des prix à la consommation pour le "
            "Canada, les États-Unis et le Japon, et l'indice harmonisé (IPCH) pour les pays "
            "européens, comme l'OCDE la publie."
        ),
    ),
    "unemployment_rate": Indicator(
        "OECD.ECO.MAD",
        "DSD_EO@DF_EO",
        "{area}.UNR.A",
        "Unemployment rate, Economic Outlook history and projections (per cent of labour force)",
        "Taux de chômage, historique et projections des Perspectives économiques (% de la "
        "population active)",
        8,
    ),
    "government_balance": Indicator(
        "OECD.ECO.MAD",
        "DSD_EO@DF_EO",
        "{area}.NLGQ.A",
        "General government net lending, Economic Outlook history and projections "
        "(per cent of GDP)",
        "Capacité de financement des administrations publiques, historique et projections des "
        "Perspectives économiques (% du PIB)",
        8,
    ),
    "government_debt": Indicator(
        "OECD.ECO.MAD",
        "DSD_EO@DF_EO",
        "{area}.GGFLQ.A",
        "General government gross financial liabilities, Economic Outlook history and "
        "projections (per cent of GDP)",
        "Passifs financiers bruts des administrations publiques, historique et projections des "
        "Perspectives économiques (% du PIB)",
        8,
    ),
    "current_account": Indicator(
        "OECD.ECO.MAD",
        "DSD_EO@DF_EO",
        "{area}.CBGDPR.A",
        "Current account balance, Economic Outlook history and projections (per cent of GDP)",
        "Solde du compte courant, historique et projections des Perspectives économiques "
        "(% du PIB)",
        8,
    ),
    "gdp_per_hour_worked": Indicator(
        "OECD.SDD.TPS",
        "DSD_PDB@DF_PDB",
        "{area}.A.GDPHRS._T.USD_PPP_H.V.N._Z.PPP",
        "Labour productivity: GDP per hour worked, current prices and PPPs (US dollars)",
        "Productivité du travail : PIB par heure travaillée, prix et PPA courants (dollars US)",
        10,
    ),
    "labour_productivity_growth": Indicator(
        "OECD.SDD.TPS",
        "DSD_PDB@DF_PDB",
        "{area}.A.GDPHRS._T.XDC_H.L.GY._Z._Z",
        "Labour productivity growth: GDP per hour worked, volume, year on year (per cent)",
        "Croissance de la productivité du travail : PIB par heure travaillée en volume, sur un "
        "an (%)",
        10,
        unit_en="Per cent, year on year",
        unit_fr="Pourcentage, sur un an",
    ),
    "gdp_per_capita": Indicator(
        "OECD.SDD.TPS",
        "DSD_PDB@DF_PDB",
        "{area}.A.GDPPOP._T.USD_PPP_PS.LR.N._Z.PPP",
        "GDP per capita, constant prices and PPPs (US dollars)",
        "PIB par habitant, prix et PPA constants (dollars US)",
        10,
    ),
    "unit_labour_cost_growth": Indicator(
        "OECD.SDD.TPS",
        "DSD_PDB@DF_PDB_ULC_Q",
        "{area}.Q.ULCE._T.PA.V.GY.S.NC",
        "Unit labour costs, total economy, year on year, seasonally adjusted (per cent)",
        "Coûts unitaires de main-d'œuvre, ensemble de l'économie, sur un an, désaisonnalisés (%)",
        12,
    ),
    "ppp_gdp": Indicator(
        "OECD.SDD.NAD",
        "DSD_NAMAIN10@DF_TABLE4",
        "A.{area}.S1.S1.PPP_B1GQ.F21._Z._Z.XDC_USD._Z.N.T001",
        "Purchasing power parity for GDP (national currency per US dollar)",
        "Parité de pouvoir d'achat du PIB (monnaie nationale par dollar US)",
        10,
    ),
    "tax_to_gdp": Indicator(
        "OECD.CTP.TPS",
        "DSD_REV_COMP_OECD@DF_RSOECD",
        "{area}.TAX_REV.S13._T._T.PT_B1GQ.A",
        "Total tax revenue, general government, Revenue Statistics (per cent of GDP)",
        "Recettes fiscales totales des administrations publiques, Statistiques des recettes "
        "publiques (% du PIB)",
        10,
    ),
    "real_house_price_index": Indicator(
        "OECD.ECO.MPD",
        "DSD_AN_HOUSE_PRICES@DF_HOUSE_PRICES",
        "{area}.Q.RHP.IX",
        "Real house price index, seasonally adjusted (2015 = 100)",
        "Indice des prix réels des logements, désaisonnalisé (2015 = 100)",
        20,
    ),
    "house_price_to_income": Indicator(
        "OECD.ECO.MPD",
        "DSD_AN_HOUSE_PRICES@DF_HOUSE_PRICES",
        "{area}.Q.HPI_YDH.IX",
        "House price-to-income ratio, seasonally adjusted (index, 2015 = 100)",
        "Ratio prix des logements/revenu, désaisonnalisé (indice, 2015 = 100)",
        20,
    ),
    "house_price_to_rent": Indicator(
        "OECD.ECO.MPD",
        "DSD_AN_HOUSE_PRICES@DF_HOUSE_PRICES",
        "{area}.Q.HPI_RPI.IX",
        "House price-to-rent ratio, seasonally adjusted (index, 2015 = 100)",
        "Ratio prix des logements/loyers, désaisonnalisé (indice, 2015 = 100)",
        20,
    ),
    "composite_leading_indicator": Indicator(
        "OECD.SDD.STES",
        "DSD_STES@DF_CLI",
        "{area}.M.LI.IX._Z.AA.IX._Z.H",
        "Composite leading indicator, amplitude adjusted (long-term average = 100)",
        "Indicateur composite avancé, amplitude ajustée (moyenne de long terme = 100)",
        24,
    ),
}
