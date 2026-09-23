"""Open Alberta (open.alberta.ca), CKAN Action API 3.

The portal is English-only at the dataset level. It has a populated tag
vocabulary but no CKAN groups, so the module exposes tags but does not
invent a group tool for an endpoint that returns an empty list.
"""

MODULE_NAME = "ckan_ab"
MODULE_DESCRIPTION = (
    "Open Alberta (open.alberta.ca): Alberta's CKAN open-data catalogue, "
    "with dataset search and detail, organizations, resources, licenses, "
    "tags, and DataStore row queries. English-only. Confirmed live: "
    "DataStore-active resources here currently answer HTTP 500 from "
    "datastore_search (a portal-side issue, surfaced as UpstreamError)."
)
MODULE_DESCRIPTION_FR = (
    "Open Alberta (open.alberta.ca) : catalogue albertain de données "
    "ouvertes fondé sur CKAN, avec recherche et détail des jeux de données, "
    "organisations, ressources, licences, mots-clés et requêtes DataStore. "
    "Uniquement en anglais. Confirmé en direct : les ressources DataStore "
    "répondent actuellement HTTP 500 à datastore_search (problème du portail)."
)
