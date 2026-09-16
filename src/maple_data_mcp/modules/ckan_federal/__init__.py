"""Government of Canada Open Data portal (open.canada.ca), CKAN Action API 3.

Covers catalogue search, dataset detail, organizations, resources, and
licenses via the standard `/data/api/3/action/...` endpoints. Confirmed
live this session against ~48,000 datasets (the catalogue's actual
`package_search` count with no filter, checked directly rather than
assumed) — see client.py for field-level quirks that differ from
generic CKAN documentation on this specific deployment.

Federal-only for now. schemas.py/client.py avoid hardcoding the base
URL anywhere but constants.py so a second CKAN portal (provincial or
municipal) can reuse the same shapes later without a rewrite, but no
multi-portal abstraction is built until a second portal actually
exists (see AGENTS.md's anti-premature-abstraction guidance).
"""

MODULE_NAME = "ckan_federal"
MODULE_DESCRIPTION = (
    "Government of Canada Open Data portal (open.canada.ca): full-text "
    "dataset search, dataset detail with resources, publishing "
    "organizations, individual resource metadata, and licenses, via the "
    "standard CKAN Action API. Covers the federal open-data catalogue "
    "(~48,000 datasets). All tools accept lang: en|fr."
)
MODULE_DESCRIPTION_FR = (
    "Portail du gouvernement du Canada sur les données ouvertes "
    "(open.canada.ca) : recherche de jeux de données en texte intégral, "
    "détail des jeux de données avec ressources, organisations "
    "responsables, métadonnées des ressources individuelles et licences, "
    "via l'API Action CKAN standard. Couvre le catalogue fédéral de "
    "données ouvertes (~48 000 jeux de données). Tous les outils "
    "acceptent lang : en|fr."
)
