"""Government of Canada Recalls and Safety Alerts (recalls-rappels.canada.ca).

One bilingual site for Health Canada (drugs, natural health products,
medical devices, consumer products, cannabis), CFIA (food) and Transport
Canada (vehicle notices). Search and counts run over the site's daily
open-data dump (34,131 notices, 1991 onward, including archived ones);
a single notice's full details (affected products table, lots, what to
do, recall date) come from its page. Transport Canada's own vehicle
recall API, with make, model and year search, is `tc_recalls_*`.
"""

MODULE_NAME = "recalls"
MODULE_DESCRIPTION = (
    "Government of Canada recalls and safety alerts (Health Canada, CFIA, Transport "
    "Canada): search food, health product, consumer product and vehicle notices by "
    "keyword, agency, category, class and date; count them by year or category; and get "
    "one notice's affected products, lots, hazard and what to do, in English or French."
)
MODULE_DESCRIPTION_FR = (
    "Rappels et avis de sécurité du gouvernement du Canada (Santé Canada, ACIA, "
    "Transports Canada) : recherche des avis sur les aliments, les produits de santé, "
    "les produits de consommation et les véhicules par mot-clé, organisme, catégorie, "
    "classe et date; décompte par année ou catégorie; et détails d'un avis (produits "
    "visés, lots, danger, que faire) en français ou en anglais."
)
