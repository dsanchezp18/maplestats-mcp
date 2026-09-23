"""Canadian Socrata (SODA) open-data portals: Nova Scotia, New Brunswick,
Calgary, Edmonton, and Winnipeg.

Confirmed live 2026-09-18 against the cross-domain discovery API
(api.us.socrata.com), the per-domain Views API, and the SODA row-query
API. Unlike this codebase's CKAN portals, Socrata exposes dataset rows
directly through a queryable API (SoQL). Content is English-only except
New Brunswick, whose content is bilingual within each field — `lang` is
a documented no-op on every portal.
"""

MODULE_NAME = "socrata"
MODULE_DESCRIPTION = (
    "Socrata open-data portals for Nova Scotia, New Brunswick, Calgary, Edmonton, and "
    "Winnipeg: dataset search and detail, categories, tags, and direct SoQL row queries. "
    "Call socrata_list_portals for every portal key."
)
MODULE_DESCRIPTION_FR = (
    "Portails de données ouvertes Socrata de la Nouvelle-Écosse, du Nouveau-Brunswick, de "
    "Calgary, d'Edmonton et de Winnipeg : recherche et détail des jeux de données, "
    "catégories, mots-clés et requêtes SoQL directes sur les lignes. Appelez "
    "socrata_list_portals pour la liste des clés de portail."
)
