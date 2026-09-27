"""Financial Consumer Agency of Canada (FCAC): product comparison tools.

FCAC publishes no open data files: its 36 datasets on open.canada.ca are
corporate reports (annual, fees, access to information), all HTML pages
(checked 2026-09-26). Its survey microdata (Monthly Financial Well-being
Monitor, Canadian Financial Capability Survey) is released on request
only, and the well-being dashboard is a Power BI embed. The one
regularly updated, product-level data FCAC publishes is in its two
comparison tools, which financial institutions keep current: the Credit
Card Comparison Tool and the Account Comparison Tool (chequing and
savings accounts). This module reads both. See client.py for how the
ASP.NET WebForms tools are driven.
"""

MODULE_NAME = "fcac"
MODULE_DESCRIPTION = (
    "Financial Consumer Agency of Canada comparison tools (itools-ioutils.fcac-acfc.gc.ca, "
    "tools prefixed fcac_): credit cards offered in a province (about 95 in Ontario: "
    "annual fees, purchase, cash advance and balance transfer rates, foreign conversion "
    "fee, minimum income, rewards, insurance) and chequing and savings accounts (monthly "
    "fees and how to waive them, included transactions, interest rate tiers, withdrawal, "
    "transfer, overdraft, NSF and other fees, low-cost and no-cost accounts). Data comes "
    "from the financial institutions and is read live (EN/FR); only products submitted "
    "to FCAC are listed."
)
MODULE_DESCRIPTION_FR = (
    "Outils de comparaison de l'Agence de la consommation en matière financière du "
    "Canada (outils préfixés fcac_) : cartes de crédit offertes dans une province (frais "
    "annuels, taux d'intérêt sur les achats, avances de fonds et transferts de solde, "
    "frais de conversion, revenu minimum, récompenses, assurances) et comptes-chèques et "
    "comptes d'épargne (frais mensuels, opérations comprises, taux d'intérêt, frais de "
    "retrait, de virement, de découvert et d'insuffisance de fonds, comptes à frais "
    "modiques ou sans frais). Données fournies par les institutions financières, lues en "
    "direct (FR/EN)."
)
