"""Alberta Economic Dashboard (economicdashboard.alberta.ca) data API.

The dashboard's charts read a public, unauthenticated JSON API at
api.economicdata.alberta.ca, found in its web-component bundles and
confirmed live 2026-09-23. It exposes ~260 curated data tables (many
named after the StatCan table they mirror, e.g. UnemploymentRates_14100287,
plus Alberta-only series such as AESO power generation, rig counts,
accommodation, bankruptcies and exports by HS code) and the dashboard's
own indicator catalogue. Content is English-only.
"""

MODULE_NAME = "ab_economic"
MODULE_DESCRIPTION = (
    "Alberta Economic Dashboard (Government of Alberta): list its ~260 "
    "curated economic data tables, inspect a table's columns and filter "
    "values, fetch filtered time series (labour, CPI, GDP, energy, "
    "exports, housing, population, business), and browse the dashboard's "
    "key-indicator catalogue with last-update dates. English-only content."
)
MODULE_DESCRIPTION_FR = (
    "Tableau de bord économique de l'Alberta (gouvernement de l'Alberta) : "
    "liste de ses quelque 260 tableaux de données économiques, colonnes et "
    "valeurs de filtre d'un tableau, séries chronologiques filtrées "
    "(emploi, IPC, PIB, énergie, exportations, logement, population, "
    "entreprises) et catalogue des indicateurs clés avec leur date de mise "
    "à jour. Contenu uniquement en anglais."
)
