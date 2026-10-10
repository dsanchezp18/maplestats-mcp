"""CRA registered charities lookup, from the annual "List of charities" (T3010) datasets.

Confirmed live 2026-10-10 on open.canada.ca: each year's list is a CKAN package titled
"<year> List of charities" (organization cra-arc, Open Government Licence - Canada) whose
resources are DataStore-active, so rows are read through `datastore_search` rather than
downloaded. The module resolves the newest year's "Identification", "General information"
and "Charities Businesses Directors/Officers" resources by name on first use.
"""

MODULE_NAME = "cra_charities"
MODULE_DESCRIPTION = (
    "CRA registered charities lookup (T3010 annual 'List of charities' on open.canada.ca, "
    "tools prefixed cra_charities_): search charities by name, city, province or "
    "designation, look one up by business number (legal name, address, designation, "
    "category codes, latest fiscal period end and programs), and list its directors and "
    "officers. Terms: Open Government Licence - Canada. Not CRA's live Charities Listing: "
    "the list is the latest published annual file, so a recent registration or revocation "
    "may not appear, and a charity's absence does not prove it is not registered."
)
MODULE_DESCRIPTION_FR = (
    "Recherche d'organismes de bienfaisance enregistrés de l'ARC (fichier annuel « Liste "
    "des organismes de bienfaisance » T3010 sur ouvert.canada.ca, outils préfixés "
    "cra_charities_) : recherche par nom, ville, province ou désignation, fiche d'un "
    "organisme par numéro d'entreprise (nom légal, adresse, désignation, codes de "
    "catégorie, fin du dernier exercice et programmes) et liste de ses administrateurs et "
    "dirigeants. Licence : Licence du gouvernement ouvert - Canada. Ne remplace pas la "
    "Liste des organismes de bienfaisance en direct de l'ARC : le fichier est le dernier "
    "fichier annuel publié, une inscription ou une révocation récente peut donc manquer, "
    "et l'absence d'un organisme ne prouve pas qu'il n'est pas enregistré."
)
