"""Patented Medicine Prices Review Board (PMPRB).

PMPRB publishes no data files: its annual reports (2018 to 2024 on
canada.ca) carry their statistics as HTML tables, each chart with a
"Figure description" text version holding the numbers, and the list of
patented medicines reported for 2020 and 2021 is one HTML table per
company. Checked live 2026-09-27 in English and French; see client.py.
Canada.ca terms allow non-commercial reproduction with attribution.
"""

MODULE_NAME = "pmprb"
MODULE_DESCRIPTION = (
    "Patented Medicine Prices Review Board annual reports on canada.ca, tools prefixed "
    "pmprb_: every table and chart data table in the 2018 to 2024 reports (Patented "
    "Medicines Price Index against CPI since 2005, foreign-to-Canadian list price ratios "
    "for the PMPRB11 and OECD countries, patented medicine sales since 1990, sales drivers, "
    "R&D spending and R&D-to-sales ratios by company, province and type of research, price "
    "review outcomes), read from the HTML in English or French with numbers parsed; and the "
    "2020 and 2021 lists of patented medicines reported (DIN, brand, ingredient, ATC, "
    "company, price review status). No data files exist behind these pages. NPDUIS drug "
    "plan data is CIHI's (cihi_)."
)
MODULE_DESCRIPTION_FR = (
    "Rapports annuels du Conseil d'examen du prix des médicaments brevetés (CEPMB) sur "
    "canada.ca, outils préfixés pmprb_ : chaque tableau et tableau de données de figure des "
    "rapports 2018 à 2024 (indice des prix des médicaments brevetés comparé à l'IPC depuis "
    "2005, ratios des prix étrangers aux prix canadiens pour le CEPMB11 et l'OCDE, ventes de "
    "médicaments brevetés depuis 1990, dépenses de R-D et ratios R-D/ventes par entreprise, "
    "province et type de recherche, résultats de l'examen des prix), en français ou en "
    "anglais, nombres convertis; et les listes 2020 et 2021 des médicaments brevetés "
    "(DIN, marque, ingrédient, ATC, entreprise, statut de l'examen du prix)."
)
