"""City of Regina Open Data portal (openregina.ca), CKAN Action API 3.

Covers catalogue search, dataset detail, organizations, resources,
licenses, tags, and groups via the standard `/api/3/action/...`
endpoints. Confirmed live this session against 1,379 datasets (the
catalogue's actual `organization_list` package_count, checked directly
rather than assumed).

Unlike ckan_toronto, this deployment genuinely uses CKAN groups, and
unlike ckan_bc, `group_list` is public here (no authentication
workaround needed) -- see client.py for every field-level quirk
confirmed live.
"""

MODULE_NAME = "ckan_regina"
MODULE_DESCRIPTION = (
    "City of Regina Open Data portal (openregina.ca): full-text dataset search, "
    "dataset detail with resources, the publishing organization, individual "
    "resource metadata, licenses, tags, and curated thematic groups, via the "
    "standard CKAN Action API. Covers the City of Regina's open-data catalogue "
    "(~1,400 datasets). English-only -- lang is accepted for interface "
    "consistency but has no effect (see tools.py)."
)
MODULE_DESCRIPTION_FR = (
    "Portail de données ouvertes de la Ville de Regina (openregina.ca) : "
    "recherche de jeux de données en texte intégral, détail des jeux de "
    "données avec ressources, organisation responsable, métadonnées des "
    "ressources individuelles, licences, mots-clés et groupes thématiques "
    "organisés, via l'API Action CKAN standard. Couvre le catalogue de "
    "données ouvertes de la Ville de Regina (environ 1 400 jeux de données). "
    "Anglais seulement -- lang est accepté par cohérence d'interface mais "
    "n'a aucun effet (voir tools.py)."
)
