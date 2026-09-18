"""Government of New Brunswick Open Data (gnb.socrata.com), Socrata (SODA) platform.

Confirmed live 2026-09-18 against the same discovery/Views/SODA surface
as modules/socrata_ns/. Unlike Nova Scotia, New Brunswick's content is
bilingual within a single field (e.g. a dataset name like "Senior
Executive Expenses / Frais ... de l'exécutif supérieur"), not split
across separate English/French fields or a `lang`-selectable endpoint —
so `lang` is a documented no-op here, the same class of quirk already
seen on this codebase's French-only CKAN portals (see
modules/ckan_qc/__init__.py).
"""

MODULE_NAME = "socrata_nb"
MODULE_DESCRIPTION = (
    "Government of New Brunswick Open Data (gnb.socrata.com): New Brunswick's "
    "Socrata open-data catalogue, with dataset search and detail, categories, "
    "tags, and direct SoQL row queries. Content is bilingual within each "
    "field (English / French together); lang is a documented no-op."
)
MODULE_DESCRIPTION_FR = (
    "Données ouvertes du gouvernement du Nouveau-Brunswick (gnb.socrata.com) : "
    "catalogue de données ouvertes du Nouveau-Brunswick fondé sur Socrata, avec "
    "recherche et détail des jeux de données, catégories, mots-clés et requêtes "
    "SoQL directes sur les lignes. Le contenu est bilingue au sein de chaque "
    "champ (anglais et français ensemble) ; lang est un no-op documenté."
)
