"""CKAN open-data catalogues: one tool family for every Canadian CKAN portal.

Replaces ten per-portal modules (ckan_federal, ckan_on, ckan_bc,
ckan_ab, ckan_qc, ckan_nt, ckan_yt, ckan_montreal, ckan_toronto,
ckan_regina) whose code differed only in configuration. Per-portal
quirks are recorded as data in constants.PORTALS.
"""

MODULE_NAME = "ckan"
MODULE_DESCRIPTION = (
    "CKAN open-data catalogues: Government of Canada (open.canada.ca), "
    "Ontario, British Columbia, Alberta, Québec, Northwest Territories, "
    "Yukon, Montréal, Toronto, and Regina. Dataset search and detail, "
    "organizations, resources, licenses, tags, groups, and row-level "
    "DataStore queries, selected with a `portal` key."
)
MODULE_DESCRIPTION_FR = (
    "Catalogues de données ouvertes CKAN : gouvernement du Canada "
    "(ouvert.canada.ca), Ontario, Colombie-Britannique, Alberta, Québec, "
    "Territoires du Nord-Ouest, Yukon, Montréal, Toronto et Regina. "
    "Recherche et détail des jeux de données, organisations, ressources, "
    "licences, mots-clés, groupes et requêtes DataStore au niveau des "
    "lignes, choisis au moyen d'une clé `portal`."
)
