"""City of Winnipeg Open Data (data.winnipeg.ca), Socrata (SODA) platform.

Confirmed live 2026-09-19 against the cross-domain discovery API
(api.us.socrata.com, 235 datasets), the per-domain Views API, and the
SODA row-query API. The portal is English-only at the dataset level.
Same shared/socrata.py adaptor as modules/socrata_ns and
modules/socrata_nb — see those modules' docstrings for the two
platform-wide quirks (search_context required alongside domains;
discovery vs. Views/SODA error-shape split) this module relies on
without repeating them here.
"""

MODULE_NAME = "socrata_winnipeg"
MODULE_DESCRIPTION = (
    "City of Winnipeg Open Data (data.winnipeg.ca): Winnipeg's Socrata open-data "
    "catalogue, with dataset search and detail, categories, tags, and direct "
    "SoQL row queries. English-only."
)
MODULE_DESCRIPTION_FR = (
    "Données ouvertes de la Ville de Winnipeg (data.winnipeg.ca) : catalogue "
    "de données ouvertes de Winnipeg fondé sur Socrata, avec recherche et "
    "détail des jeux de données, catégories, mots-clés et requêtes SoQL "
    "directes sur les lignes. Uniquement en anglais."
)
