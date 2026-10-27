"""Telecom prices and market indicators from the CRTC's Communications Market Reports.

The CRTC publishes its Communications Market Reports (CMR) data as Excel
workbooks under its open.canada.ca organization (Open Government Licence -
Canada), hosted on applications.crtc.gc.ca. The generic ckan_ tools can read
them, but plan prices sit in long sheets with bilingual labels that are not
consistent, the annual sector tables are wide year-by-column grids with
footnote rows and a 2020 change of scope marked "(MP)", and the quarterly
trends rows are unsorted; this module turns them into clean series. Checked
live 2026-10-27; see client.py and parsing.py.
"""

MODULE_NAME = "telecom_prices"
MODULE_DESCRIPTION = (
    "CRTC Communications Market Reports data, tools prefixed telecom_: average advertised "
    "monthly prices of mobile plans by data allowance (1 GB to 200 GB, talk-only) and of "
    "home Internet plans by speed, by province and urban or rural area, at year end since "
    "2016; the annual retail mobile and fixed Internet sector tables (revenue per GB, ARPU, "
    "data usage, subscribers, market shares of Bell, Rogers, TELUS and others, churn, plan "
    "size distribution) as tidy series; and the quarterly current-trends series (revenues, "
    "subscribers, data traffic) since 2014. The monthly cellular services CPI is "
    "Statistics Canada vector v1212387935 (wds_)."
)
MODULE_DESCRIPTION_FR = (
    "Données des Rapports sur le marché des communications du CRTC, outils préfixés "
    "telecom_ : prix mensuels moyens annoncés des forfaits mobiles selon la quantité de "
    "données (1 Go à 200 Go, voix seulement) et des forfaits Internet résidentiels selon "
    "la vitesse, par province et en milieu urbain ou rural, à la fin de chaque année depuis "
    "2016; les tableaux annuels des secteurs des services mobiles et Internet fixes de détail "
    "(revenu par Go, RMPU, utilisation de données, abonnés, parts de marché de Bell, Rogers, "
    "TELUS et des autres, taux de résiliation, répartition par taille de forfait) en séries "
    "propres; et les séries trimestrielles des tendances actuelles (revenus, abonnés, trafic "
    "de données) depuis 2014. L'IPC mensuel des services de téléphonie cellulaire est le "
    "vecteur v1212387935 de Statistique Canada (wds_)."
)
