"""Ontario Data Catalogue (data.ontario.ca), CKAN Action API 3.

Ontario's catalogue has bilingual metadata fields, populated tags, and a
small set of real CKAN groups. The client chooses translated values from
the record rather than relying on a language query parameter, which the
Action API does not consistently honor.
"""

MODULE_NAME = "ckan_on"
MODULE_DESCRIPTION = (
    "Ontario Data Catalogue (data.ontario.ca): bilingual CKAN dataset "
    "search and detail, organizations, resources, licenses, tags, and "
    "groups."
)
MODULE_DESCRIPTION_FR = (
    "Catalogue de données de l'Ontario (data.ontario.ca) : recherche et "
    "détail bilingues de jeux de données CKAN, organisations, ressources, "
    "licences, mots-clés et groupes."
)
