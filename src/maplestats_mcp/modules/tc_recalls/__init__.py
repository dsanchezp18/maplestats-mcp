"""Transport Canada Motor Vehicle Safety Recalls Database API.

data.tc.gc.ca/v1.3/api/{eng|fra}/vehicle-recall-database, confirmed live
2026-09-23: recall search by make, model and model-year range, and a
bilingual summary per recall number (category, system, notification
type, units affected, issue/risk/action text, affected models and
years). Transport Canada's other data (collisions, aviation, rail) is
on open.canada.ca and reachable through `ckan_*` (portal="federal").
"""

MODULE_NAME = "tc_recalls"
MODULE_DESCRIPTION = (
    "Transport Canada motor vehicle safety recalls: search recalls by "
    "make, model and model year, and get a recall's full summary (issue, "
    "safety risk, corrective action, units affected, affected models and "
    "years) in English or French."
)
MODULE_DESCRIPTION_FR = (
    "Rappels de sécurité des véhicules automobiles de Transports Canada : "
    "recherche des rappels par marque, modèle et année-modèle, et sommaire "
    "complet d'un rappel (problème, risque pour la sécurité, mesure "
    "corrective, unités touchées, modèles et années visés) en français ou "
    "en anglais."
)
