"""Canadian Institute for Health Information (CIHI) Indicator Library.

CIHI retired Your Health System and the Health Indicators Interactive
Tool in favour of the Indicator Library (cihi.ca/en/indicators), where
each of ~200 health-system indicators has a page and a downloadable XLSX
data table in English and French. The interactive tables are embedded
Qlik Sense (websocket engine), so this module reads the published XLSX
files instead. Confirmed live 2026-09-23.
"""

MODULE_NAME = "cihi"
MODULE_DESCRIPTION = (
    "Canadian Institute for Health Information Indicator Library: search "
    "~200 health-system indicators (hospital mortality and readmissions, "
    "wait times, ED visits, health spending, patient outcomes), read an "
    "indicator's description and data availability, and query its data "
    "table by place, reporting level, time frame and breakdown, in English "
    "or French."
)
MODULE_DESCRIPTION_FR = (
    "Répertoire des indicateurs de l'Institut canadien d'information sur "
    "la santé (ICIS) : recherche parmi quelque 200 indicateurs du système "
    "de santé (mortalité et réadmissions à l'hôpital, temps d'attente, "
    "visites aux urgences, dépenses de santé, résultats pour les patients), "
    "description et disponibilité des données d'un indicateur, et "
    "interrogation de son tableau de données par lieu, niveau de "
    "déclaration, période et ventilation, en français ou en anglais."
)
