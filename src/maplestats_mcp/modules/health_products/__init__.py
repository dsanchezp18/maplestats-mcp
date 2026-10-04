"""Health Canada health products APIs (health-products.canada.ca/api).

Four keyless JSON APIs under the Open Government Licence - Canada, one
sub-folder each: the Drug Product Database (`dpd/`, tools hc_drug_*),
the Licensed Natural Health Products Database (`lnhpd/`, hc_nhp_*), the
Medical Devices Active Licence Listing (`mdall/`, hc_device_*) and the
Canada Vigilance adverse reaction database (`vigilance/`, hc_vigilance_*),
whose monthly extract is read as a stream with byte ceilings. `api.py`
holds the shared request, provenance and streaming code.
"""

MODULE_NAME = "health_products"
MODULE_DESCRIPTION = (
    "Health Canada health products, tools prefixed hc_: the Drug Product Database "
    "(hc_drug_: search drug products by DIN, brand, company, active ingredient, status, "
    "schedule or ATC class; full product records with ingredients and strengths, "
    "schedules, routes, dosage forms, packaging and status history), licensed natural "
    "health products (hc_nhp_: search by product or company, NPN records with medicinal "
    "ingredients, doses, purposes and risks), medical device licences (hc_device_: "
    "licences, devices and identifiers by name or company, updated daily) and Canada "
    "Vigilance adverse reaction reports (hc_vigilance_: one report with its drugs, code "
    "tables, and a reaction-term search over the monthly extract), in English or French."
)
MODULE_DESCRIPTION_FR = (
    "Produits de santé de Santé Canada, outils préfixés hc_ : Base de données sur les "
    "produits pharmaceutiques (hc_drug_ : recherche par DIN, marque, entreprise, "
    "ingrédient actif, statut, annexe ou classe ATC; fiches complètes avec ingrédients et "
    "concentrations, annexes, voies d'administration, formes posologiques, emballage et "
    "statut), produits de santé naturels homologués (hc_nhp_ : recherche par produit ou "
    "entreprise, fiches NPN avec ingrédients médicinaux, doses, usages et risques), "
    "homologations d'instruments médicaux (hc_device_ : homologations, instruments et "
    "identifiants par nom ou entreprise, mis à jour chaque jour) et déclarations d'effets "
    "indésirables de Canada Vigilance (hc_vigilance_ : une déclaration et ses produits, "
    "tables de codes, recherche par terme d'effet dans l'extrait mensuel), en français ou "
    "en anglais."
)
