"""City of Toronto Open Data portal (open.toronto.ca), CKAN Action API 3.

Covers catalogue search, dataset detail, organizations, resources,
licenses, and tags via the standard `/api/3/action/...` endpoints on
the portal's dedicated API host. Confirmed live this session against
557 datasets (the catalogue's actual `package_list` count, checked
directly rather than assumed) -- see client.py for field-level quirks
that differ from both generic CKAN documentation and the federal
portal's own deployment-specific behavior (modules/ckan_federal/).

This portal's public-facing UI domain (open.toronto.ca) is NOT the API
host -- the Action API lives at a separate infrastructure host
(ckan0.cf.opendata.inter.prod-toronto.ca), confirmed live. See
constants.py for both hosts and why each is used where.
"""

MODULE_NAME = "ckan_toronto"
MODULE_DESCRIPTION = (
    "City of Toronto Open Data portal (open.toronto.ca): full-text "
    "dataset search, dataset detail with resources, the publishing "
    "organization, individual resource metadata, licenses, and tags, "
    "via the standard CKAN Action API. Covers the City of Toronto's "
    "open-data catalogue (~550 datasets). English-only -- lang is "
    "accepted for interface consistency but has no effect (see tools.py)."
)
MODULE_DESCRIPTION_FR = (
    "Portail de données ouvertes de la Ville de Toronto (open.toronto.ca) : "
    "recherche de jeux de données en texte intégral, détail des jeux de "
    "données avec ressources, organisation responsable, métadonnées des "
    "ressources individuelles, licences et mots-clés, via l'API Action "
    "CKAN standard. Couvre le catalogue de données ouvertes de la Ville "
    "de Toronto (~550 jeux de données). Anglais seulement -- lang est "
    "accepté par cohérence d'interface mais n'a aucun effet (voir tools.py)."
)
