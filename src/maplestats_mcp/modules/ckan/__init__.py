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
    "organizations, resources, licenses, tags, groups, row-level "
    "DataStore queries, and a reader for the Excel (.xlsx, .xls) and CSV "
    "files of file-only resources (about half the tabular datasets on the "
    "federal, Ontario and BC portals have no DataStore; not Toronto, whose portal does not permit automated file downloads): sheets, "
    "guessed header row, filters and paging, with the licence, source and "
    "a warning when the licence is not open. Portals are selected with a "
    "`portal` key."
)
MODULE_DESCRIPTION_FR = (
    "Catalogues de données ouvertes CKAN : gouvernement du Canada "
    "(ouvert.canada.ca), Ontario, Colombie-Britannique, Alberta, Québec, "
    "Territoires du Nord-Ouest, Yukon, Montréal, Toronto et Regina. "
    "Recherche et détail des jeux de données, organisations, ressources, "
    "licences, mots-clés, groupes, requêtes DataStore au niveau des "
    "lignes et lecture des fichiers Excel (.xlsx, .xls) et CSV des "
    "ressources sans DataStore (environ la moitié des jeux de données "
    "tabulaires des portails fédéral, ontarien et britanno-colombien ; pas "
    "Toronto, dont le portail ne permet pas le téléchargement automatisé des fichiers) : feuilles, ligne d'en-tête devinée, filtres et pagination, "
    "avec la licence, la source et un avertissement quand la licence n'est "
    "pas ouverte. Les portails sont choisis au moyen d'une clé `portal`."
)
