"""City of Vancouver Open Data Portal (opendata.vancouver.ca), an Opendatasoft deployment.

Confirmed live 2026-09-19 against the Explore API V2
(`/api/v2/catalog/datasets`, `.../records`, `.../exports/<fmt>`). This
is the first Opendatasoft-platform source in this codebase (every
prior source is CKAN, Socrata, or ArcGIS Hub) -- see
shared/opendatasoft.py for the platform quirks this module relies on.
Dataset content observed is English-only -- `lang` is a documented
no-op.
"""

MODULE_NAME = "opendatasoft_vancouver"
MODULE_DESCRIPTION = (
    "City of Vancouver Open Data Portal (opendata.vancouver.ca): dataset search and "
    "detail, direct record queries with ODSQL filtering/sorting, and CSV/JSON/GeoJSON "
    "export download links. The only Opendatasoft-platform source in this codebase."
)
MODULE_DESCRIPTION_FR = (
    "Portail de données ouvertes de la Ville de Vancouver (opendata.vancouver.ca) : "
    "recherche et détail des jeux de données, requêtes directes sur les "
    "enregistrements avec filtrage/tri ODSQL, et liens de téléchargement CSV/"
    "JSON/GeoJSON. La seule source de la plateforme Opendatasoft dans ce projet."
)
