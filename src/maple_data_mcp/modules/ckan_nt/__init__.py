"""Northwest Territories Open Data portal (opendata.gov.nt.ca), CKAN Action API 3.

Covers catalogue search, dataset detail, organizations, tags, groups,
resources, and licenses via the standard `/api/3/action/...` endpoints.
Confirmed live this session against a real, small territorial-government
catalogue -- 341 total datasets (package_search with no filter, checked
directly rather than assumed) -- see client.py for field-level quirks
that differ from both generic CKAN documentation and this codebase's
existing modules/ckan_federal/ reference.

This portal differs from ckan_federal in two ways significant enough to
change the tool surface:

1. It actually uses CKAN tags (151 live) and groups (15 live, each a
   meaningful topic category with a description and package_count) --
   confirmed live via tag_list/group_list, the opposite of federal's
   confirmed-empty result for both. ckan_nt_list_tags and
   ckan_nt_list_groups are defined here as a result (see schemas.py).
2. It is English-only in practice -- confirmed live: no package, resource,
   organization, or license record carries a `_translated` dict or
   `_fra`-suffixed field anywhere, and `/fr/...`-prefixed paths 404. lang
   is still accepted on every tool per this project's convention, but it
   has no effect here; see tools.py's module docstring.
"""

MODULE_NAME = "ckan_nt"
MODULE_DESCRIPTION = (
    "Northwest Territories Open Data portal (opendata.gov.nt.ca): "
    "full-text dataset search, dataset detail with resources, tags, and "
    "groups, publishing organizations, topic groups, individual resource "
    "metadata, and licenses, via the standard CKAN Action API. Covers the "
    "NWT territorial-government open-data catalogue (~341 datasets). "
    "lang is accepted for consistency but has no effect: the portal is "
    "English-only."
)
MODULE_DESCRIPTION_FR = (
    "Portail de données ouvertes des Territoires du Nord-Ouest "
    "(opendata.gov.nt.ca) : recherche de jeux de données en texte "
    "intégral, détail des jeux de données avec ressources, mots-clés et "
    "groupes, organisations responsables, groupes thématiques, métadonnées "
    "des ressources individuelles et licences, via l'API Action CKAN "
    "standard. Couvre le catalogue de données ouvertes du gouvernement "
    "territorial des T.N.-O. (~341 jeux de données). lang est accepté par "
    "cohérence mais n'a aucun effet : le portail est uniquement en anglais."
)
