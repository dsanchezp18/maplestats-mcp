"""Constants for the Federal Reserve Board statistical releases module.

Release files, series ids and terms checked live on 2026-11-07 (see client.py's
module docstring).
"""

from __future__ import annotations

from dataclasses import dataclass

SITE = "https://www.federalreserve.gov"
SOURCE = "fed"

# The Board's disclaimer (https://www.federalreserve.gov/disclaimer.htm, read
# 2026-11-07): Board information is public domain and may be copied without
# permission; cite the Board. Material from other sources carries its own terms.
LICENCE = (
    "Source: Board of Governors of the Federal Reserve System (https://www.federalreserve.gov/). "
    "Public domain: information on the Board's website may be copied and distributed without "
    "permission; cite the Board as the source (https://www.federalreserve.gov/disclaimer.htm). "
    "Material the Board takes from other sources keeps that source's terms."
)
LICENCE_FR = (
    "Source : Conseil des gouverneurs de la Réserve fédérale (https://www.federalreserve.gov/). "
    "Domaine public : l'information du site du Conseil peut être copiée et diffusée sans "
    "autorisation ; citez le Conseil comme source (https://www.federalreserve.gov/"
    "disclaimer.htm, en anglais). Les données que le Conseil tient d'autres sources restent "
    "soumises aux conditions de ces sources."
)

# The Board hosts no rate guidance and no robots.txt (404 on 2026-11-07); a
# release file is one request, cached for hours, so one request a second is ample.
RATE_LIMIT_SOURCE = "fed"
RATE_LIMIT_PER_SECOND = 1.0
RATE_LIMIT_CAPACITY = 2.0
DOWNLOAD_TIMEOUT_SECONDS = 120.0

# Releases change at most daily (H.15, H.10, policy rates); the files are
# re-read after this long.
CACHE_TTL_RELEASE_SECONDS = 6 * 60 * 60

# Largest file on 2026-11-07: H.4.1, a 9.1 MB zip holding a 127 MB XML file.
# The caps refuse anything far larger rather than read it into memory.
MAX_ZIP_BYTES = 30_000_000
MAX_XML_BYTES = 400_000_000

MAX_SERIES = 25
MAX_ROWS = 10_000
MAX_LAST_N = 5_000
MAX_SEARCH_RESULTS = 100

# Observation statuses that carry no value (the value field holds -9999).
EMPTY_STATUSES = frozenset({"ND", "NA", "NC"})


@dataclass(frozen=True)
class Release:
    """A Board release whose complete data the release page offers as one XML zip."""

    code: str  # the DDP code, upper case (file names use it in lower case)
    name_en: str
    name_fr: str
    about_en: str
    about_fr: str
    page: str  # release page path on federalreserve.gov

    @property
    def data_url(self) -> str:
        code = self.code.lower()
        return f"{SITE}/releases/{code}/data/FRB_{code}_xml.zip"

    @property
    def page_url(self) -> str:
        return SITE + self.page


# Every file answered 200 on 2026-11-07. Not included: the Financial Accounts
# (Z.1; a 38 MB zip holding a 620 MB XML file), H.3 and E.2 (no file on their
# release pages, 404) and the discontinued FOR ratios.
RELEASES: dict[str, Release] = {
    r.code: r
    for r in (
        Release(
            "H15",
            "Selected Interest Rates (H.15)",
            "Taux d'intérêt choisis (H.15)",
            (
                "Daily, weekly and monthly federal funds rate, Treasury bill and constant-"
                "maturity yields, commercial paper, the bank prime loan rate and the discount "
                "rate."
            ),
            (
                "Taux des fonds fédéraux, rendements des bons et des titres du Trésor à "
                "échéance constante, papier commercial, taux préférentiel et taux d'escompte, "
                "quotidiens, hebdomadaires et mensuels."
            ),
            "/releases/h15/",
        ),
        Release(
            "PRATES",
            "Policy Rates",
            "Taux directeurs",
            "Interest rate on reserve balances (IORB), and the earlier IOER and IORR rates.",
            ("Taux d'intérêt sur les soldes de réserve (IORB), et les anciens taux IOER et IORR."),
            "/releases/h15/",
        ),
        Release(
            "H10",
            "Foreign Exchange Rates (G.5 / H.10)",
            "Taux de change (G.5 / H.10)",
            (
                "Noon buying rates in New York for 23 currencies, including the Canadian "
                "dollar, daily (H.10), monthly (G.5) and annual, and the nominal and real "
                "trade-weighted dollar indexes."
            ),
            (
                "Taux acheteurs de midi à New York pour 23 monnaies, dont le dollar canadien, "
                "quotidiens (H.10), mensuels (G.5) et annuels, et les indices nominaux et "
                "réels du dollar pondérés par les échanges."
            ),
            "/releases/h10/",
        ),
        Release(
            "G17",
            "Industrial Production and Capacity Utilization (G.17)",
            "Production industrielle et utilisation des capacités (G.17)",
            (
                "Monthly industrial production indexes by industry and market group, capacity "
                "and capacity utilization rates, motor vehicle assemblies and electric power use."
            ),
            (
                "Indices mensuels de la production industrielle par industrie et par groupe de "
                "marché, capacité et taux d'utilisation des capacités, assemblages de véhicules "
                "automobiles et consommation d'électricité."
            ),
            "/releases/g17/",
        ),
        Release(
            "H6",
            "Money Stock Measures (H.6)",
            "Agrégats monétaires (H.6)",
            "M1, M2 and their components, monthly and weekly, and the monetary base.",
            "M1, M2 et leurs composantes, mensuels et hebdomadaires, et la base monétaire.",
            "/releases/h6/",
        ),
        Release(
            "G19",
            "Consumer Credit (G.19)",
            "Crédit à la consommation (G.19)",
            (
                "Consumer credit outstanding, revolving and nonrevolving, by holder, and terms "
                "of credit (interest rates on car loans, credit cards and personal loans)."
            ),
            (
                "Encours du crédit à la consommation, renouvelable et non renouvelable, par "
                "détenteur, et conditions du crédit (taux d'intérêt des prêts automobiles, des "
                "cartes de crédit et des prêts personnels)."
            ),
            "/releases/g19/",
        ),
        Release(
            "DSR",
            "Household Debt Service Ratios",
            "Ratios du service de la dette des ménages",
            "Quarterly household debt service ratio, mortgage and consumer, seasonally adjusted.",
            (
                "Ratio trimestriel du service de la dette des ménages, hypothécaire et à la "
                "consommation, désaisonnalisé."
            ),
            "/releases/housedebt/",
        ),
        Release(
            "H8",
            "Assets and Liabilities of Commercial Banks in the U.S. (H.8)",
            "Actif et passif des banques commerciales aux États-Unis (H.8)",
            "Weekly and monthly balance sheets of US commercial banks: loans, securities, deposits.",
            (
                "Bilans hebdomadaires et mensuels des banques commerciales américaines : prêts, "
                "titres, dépôts."
            ),
            "/releases/h8/",
        ),
        Release(
            "H41",
            "Factors Affecting Reserve Balances (H.4.1)",
            "Facteurs influant sur les soldes de réserve (H.4.1)",
            "The Federal Reserve's weekly balance sheet: securities held, loans, reserve balances.",
            (
                "Bilan hebdomadaire de la Réserve fédérale : titres détenus, prêts, soldes de "
                "réserve."
            ),
            "/releases/h41/",
        ),
        Release(
            "CP",
            "Commercial Paper",
            "Papier commercial",
            "Commercial paper rates, outstandings and issuance volumes.",
            "Taux, encours et volumes d'émission du papier commercial.",
            "/releases/cp/",
        ),
        Release(
            "G20",
            "Finance Companies (G.20)",
            "Sociétés de financement (G.20)",
            "Finance company receivables (consumer, real estate, business) and terms of credit.",
            (
                "Créances des sociétés de financement (consommation, immobilier, entreprises) et "
                "conditions du crédit."
            ),
            "/releases/g20/",
        ),
        Release(
            "CHGDEL",
            "Charge-off and Delinquency Rates",
            "Taux de radiation et de défaillance",
            "Quarterly charge-off and delinquency rates on loans and leases at commercial banks.",
            (
                "Taux trimestriels de radiation et de défaillance des prêts et crédits-bails des "
                "banques commerciales."
            ),
            "/releases/chargeoff/",
        ),
        Release(
            "SLOOS",
            "Senior Loan Officer Opinion Survey on Bank Lending Practices",
            "Enquête auprès des responsables du crédit sur les pratiques de prêt des banques",
            "Net shares of banks tightening standards and reporting stronger loan demand.",
            (
                "Proportions nettes de banques qui resserrent leurs critères d'octroi et qui "
                "signalent une demande de prêts plus forte."
            ),
            "/data/sloos.htm",
        ),
        Release(
            "SCOOS",
            "Senior Credit Officer Opinion Survey on Dealer Financing Terms",
            "Enquête auprès des responsables du crédit sur les conditions de financement des courtiers",
            "Dealer financing terms for securities financing and OTC derivatives, quarterly.",
            (
                "Conditions de financement des courtiers pour le financement de titres et les "
                "dérivés de gré à gré, trimestrielles."
            ),
            "/data/scoos.htm",
        ),
    )
}

# Searched when no release is named: the comparators for Canada's own figures.
DEFAULT_SEARCH = ("H15", "PRATES", "H10", "G17")


@dataclass(frozen=True)
class Indicator:
    release: str
    series: str
    label_en: str
    label_fr: str
    pair_en: str
    pair_fr: str


# Each series checked live on 2026-11-07 (release files of that day).
INDICATORS: dict[str, Indicator] = {
    "cad_per_usd": Indicator(
        "H10",
        "RXI_N.B.CA",
        "Canadian dollars per US dollar, noon buying rate in New York, business days",
        "Dollars canadiens par dollar américain, taux acheteur de midi à New York, jours ouvrables",
        "Bank of Canada daily rate FXUSDCAD (boc_get_series).",
        "Taux quotidien FXUSDCAD de la Banque du Canada (boc_get_series).",
    ),
    "cad_per_usd_monthly": Indicator(
        "H10",
        "RXI_N.M.CA",
        "Canadian dollars per US dollar, monthly average",
        "Dollars canadiens par dollar américain, moyenne mensuelle",
        "Bank of Canada monthly average FXMUSDCAD (boc_get_series).",
        "Moyenne mensuelle FXMUSDCAD de la Banque du Canada (boc_get_series).",
    ),
    "broad_dollar_index": Indicator(
        "H10",
        "JRXWTFB_N.B",
        "Nominal broad dollar index (trade-weighted), business days",
        "Indice large nominal du dollar (pondéré par les échanges), jours ouvrables",
        "Bank of Canada Canadian Effective Exchange Rate index CEER (boc_search_series).",
        "Indice de taux de change effectif du dollar canadien (TCEC) de la Banque du Canada "
        "(boc_search_series).",
    ),
    "fed_funds_rate": Indicator(
        "H15",
        "RIFSPFF_N.B",
        "Effective federal funds rate, business days (per cent per year)",
        "Taux effectif des fonds fédéraux, jours ouvrables (pour cent par année)",
        "CORRA, the Canadian overnight repo rate average (boc_get_series AVG.INTWO), and the "
        "Bank of Canada's target for the overnight rate (V39079).",
        "Le CORRA, taux moyen des opérations de pension à un jour au Canada (boc_get_series "
        "AVG.INTWO), et la cible de la Banque du Canada pour le taux du financement à un "
        "jour (V39079).",
    ),
    "fed_funds_rate_monthly": Indicator(
        "H15",
        "RIFSPFF_N.M",
        "Effective federal funds rate, monthly average (per cent per year)",
        "Taux effectif des fonds fédéraux, moyenne mensuelle (pour cent par année)",
        "The Bank of Canada's target for the overnight rate (boc_get_series V39079).",
        "La cible de la Banque du Canada pour le taux du financement à un jour "
        "(boc_get_series V39079).",
    ),
    "interest_on_reserve_balances": Indicator(
        "PRATES",
        "RESBM_N.D",
        "Interest rate on reserve balances (IORB), daily (per cent)",
        "Taux d'intérêt sur les soldes de réserve (IORB), quotidien (pour cent)",
        "The Bank of Canada's deposit rate, the floor of its operating band (boc_search_series).",
        "Le taux de rémunération des dépôts de la Banque du Canada, plancher de sa fourchette "
        "opérationnelle (boc_search_series).",
    ),
    "prime_rate": Indicator(
        "H15",
        "RIFSPBLP_N.M",
        "Bank prime loan rate, monthly (per cent per year)",
        "Taux préférentiel des banques, mensuel (pour cent par année)",
        "Canada's chartered bank prime business rate (boc_search_series 'prime rate').",
        "Le taux préférentiel des banques à charte du Canada (boc_search_series « taux "
        "préférentiel »).",
    ),
    "treasury_2y": Indicator(
        "H15",
        "RIFLGFCY02_N.B",
        "2-year Treasury constant maturity yield, business days (per cent per year)",
        "Rendement du Trésor à 2 ans, échéance constante, jours ouvrables (pour cent par année)",
        "Government of Canada 2-year benchmark bond yield (boc_get_series BD.CDN.2YR.DQ.YLD).",
        "Rendement de l'obligation de référence du gouvernement du Canada à 2 ans "
        "(boc_get_series BD.CDN.2YR.DQ.YLD).",
    ),
    "treasury_10y": Indicator(
        "H15",
        "RIFLGFCY10_N.B",
        "10-year Treasury constant maturity yield, business days (per cent per year)",
        "Rendement du Trésor à 10 ans, échéance constante, jours ouvrables (pour cent par année)",
        "Government of Canada 10-year benchmark bond yield (boc_get_series BD.CDN.10YR.DQ.YLD).",
        "Rendement de l'obligation de référence du gouvernement du Canada à 10 ans "
        "(boc_get_series BD.CDN.10YR.DQ.YLD).",
    ),
    "industrial_production": Indicator(
        "G17",
        "IP.B50001.S",
        "Industrial production, total index (2017 = 100), seasonally adjusted, monthly",
        "Production industrielle, indice total (2017 = 100), désaisonnalisée, mensuelle",
        "Statistics Canada's monthly GDP by industry, industrial production aggregate (table "
        "36-10-0434-01).",
        "Le PIB mensuel par industrie de Statistique Canada, agrégat de la production "
        "industrielle (tableau 36-10-0434-01).",
    ),
    "manufacturing_production": Indicator(
        "G17",
        "IP.B00004.S",
        "Industrial production, manufacturing (SIC) (2017 = 100), seasonally adjusted, monthly",
        "Production industrielle, fabrication (SIC) (2017 = 100), désaisonnalisée, mensuelle",
        "Statistics Canada's monthly GDP by industry, manufacturing (table 36-10-0434-01).",
        "Le PIB mensuel par industrie de Statistique Canada, fabrication (tableau 36-10-0434-01).",
    ),
    "capacity_utilization": Indicator(
        "G17",
        "CAPUTL.B50001.S",
        "Capacity utilization, total industry, seasonally adjusted, monthly (per cent)",
        "Taux d'utilisation des capacités, ensemble de l'industrie, désaisonnalisé, mensuel "
        "(pour cent)",
        "Statistics Canada's quarterly industrial capacity utilization rates (table "
        "16-10-0109-01).",
        "Les taux trimestriels d'utilisation de la capacité industrielle de Statistique Canada "
        "(tableau 16-10-0109-01).",
    ),
    "m2_money_stock": Indicator(
        "H6",
        "M2.M",
        "M2 money stock, seasonally adjusted, monthly (billions of dollars)",
        "Masse monétaire M2, désaisonnalisée, mensuelle (milliards de dollars)",
        "Bank of Canada monetary aggregates, M2++ (boc_search_series 'M2++').",
        "Les agrégats monétaires de la Banque du Canada, M2++ (boc_search_series « M2++ »).",
    ),
    "consumer_credit": Indicator(
        "G19",
        "DTCTL.M",
        "Total consumer credit owned and securitized, seasonally adjusted, monthly (millions of "
        "dollars)",
        "Encours total du crédit à la consommation, détenu et titrisé, désaisonnalisé, mensuel "
        "(millions de dollars)",
        "Bank of Canada household credit, consumer credit (boc_search_series 'consumer credit').",
        "Le crédit aux ménages de la Banque du Canada, crédit à la consommation "
        "(boc_search_series « crédit à la consommation »).",
    ),
    "household_debt_service_ratio": Indicator(
        "DSR",
        "DSR_RATIO",
        "Household debt service ratio, seasonally adjusted, quarterly (per cent of disposable "
        "income)",
        "Ratio du service de la dette des ménages, désaisonnalisé, trimestriel (pour cent du "
        "revenu disponible)",
        "Statistics Canada's household debt service ratio (table 11-10-0065-01), or "
        "bis_compare_countries household_debt_service_ratio for the same BIS definition.",
        "Le ratio du service de la dette des ménages de Statistique Canada (tableau "
        "11-10-0065-01), ou bis_compare_countries household_debt_service_ratio pour une "
        "définition commune (BRI).",
    ),
}
