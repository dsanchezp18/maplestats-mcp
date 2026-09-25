"""Open Data Newfoundland and Labrador's custom HTML catalogue.

This portal is not CKAN, Socrata, or ArcGIS Hub. Its public catalogue is a
small set of HTML pages: separate tabular/spatial listings, a tag-filtered
listing, and one metadata page per dataset. The routes and field labels in
this module were checked against live pages on 2026-09-18.

The portal is English-only. ``lang`` remains part of every tool's interface
for consistency with the rest of MapleStats MCP, but it does not alter the
response.
"""

MODULE_NAME = "nl_opendata"
MODULE_DESCRIPTION = (
    "Open Data Newfoundland and Labrador (opendata.gov.nl.ca): HTML catalogue "
    "search over tabular and spatial datasets, dataset metadata, topic tags, "
    "and links to downloadable CSV, XLS, TXT, KMZ, and shapefile files. "
    "The portal is English-only and has no documented JSON catalogue API."
)
MODULE_DESCRIPTION_FR = (
    "Données ouvertes de Terre-Neuve-et-Labrador (opendata.gov.nl.ca) : "
    "recherche HTML dans les jeux de données tabulaires et spatiaux, "
    "métadonnées, mots-clés thématiques et liens vers les fichiers CSV, XLS, "
    "TXT, KMZ et shapefile. Le portail est uniquement en anglais et ne fournit "
    "pas d'API JSON de catalogue documentée."
)
