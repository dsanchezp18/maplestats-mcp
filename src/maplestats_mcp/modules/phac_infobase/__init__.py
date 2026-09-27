"""Public Health Agency of Canada (PHAC) Health Infobase data files.

health-infobase.canada.ca hosts PHAC's surveillance dashboards. Most load
plain CSV files from /src/data/..., which this module reads through a
curated catalogue (catalogue.py) of 55 files: respiratory virus
surveillance (laboratory detections, FluWatch+, CNISP sentinel
hospitals), wastewater, opioid and stimulant harms, supervised
consumption sites, substance use surveys, measles, mpox, tuberculosis,
notifiable diseases, vaccine adverse events, chronic disease and health
status indicators, and the archived COVID-19 files. Confirmed live
2026-09-26. PHAC's open.canada.ca datasets remain reachable through
ckan_*; only a handful of these files are listed there.

Dashboards with no downloadable data are not catalogued: the Canadian
Chronic Disease Surveillance System data tool and the current CCDI,
perinatal health, positive mental health, suicide and health
inequalities tools (server-rendered charts), the STBBI surveillance
dashboard (HTML tables), and Notifiable Diseases Online (data inside
its page scripts).
"""

MODULE_NAME = "phac_infobase"
MODULE_DESCRIPTION = (
    "PHAC Health Infobase: list, describe and query the data files behind "
    "the Public Health Agency of Canada's surveillance dashboards "
    "(respiratory virus detections and FluWatch+, wastewater, opioid and "
    "stimulant harms, supervised consumption sites, substance use surveys, "
    "measles, mpox, tuberculosis, notifiable diseases, vaccine adverse "
    "events, chronic disease indicators, archived COVID-19 data), filtered "
    "by column values, province and date range, in English or French."
)
MODULE_DESCRIPTION_FR = (
    "Santé Infobase de l'ASPC : liste, description et interrogation des "
    "fichiers de données des tableaux de bord de surveillance de l'Agence "
    "de la santé publique du Canada (détections de virus respiratoires et "
    "ÉpiGrippe+, eaux usées, méfaits liés aux opioïdes et aux stimulants, "
    "sites de consommation supervisée, enquêtes sur la consommation de "
    "substances, rougeole, mpox, tuberculose, maladies à déclaration "
    "obligatoire, manifestations cliniques après la vaccination, "
    "indicateurs de maladies chroniques, données COVID-19 archivées), "
    "filtrées par valeur de colonne, province et période, en français ou "
    "en anglais."
)
