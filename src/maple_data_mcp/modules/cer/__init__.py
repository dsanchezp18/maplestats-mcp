"""Canada Energy Regulator (CER) open data.

The CER publishes its open data as bilingual CSV files under
cer-rec.gc.ca/open/ (English) and /ouvert/ (French), catalogued on
open.canada.ca under the `cer-rec` organization (84 datasets, checked
live 2026-09-23): pipeline throughput and capacity for every major
pipeline, crude oil, natural gas, NGL, LNG and refined product exports,
pipeline tolls, incidents, refinery runs, frontier production, and the
Canada's Energy Future scenario data. This module lists those files and
queries their rows directly.
"""

MODULE_NAME = "cer"
MODULE_DESCRIPTION = (
    "Canada Energy Regulator open data: find CER CSV files (pipeline "
    "throughput and capacity, oil/gas/NGL/LNG/refined product exports, "
    "pipeline tolls, incidents, refinery runs, Canada's Energy Future "
    "projections) and query their rows with column filters and date "
    "ranges, in English or French."
)
MODULE_DESCRIPTION_FR = (
    "Données ouvertes de la Régie de l'énergie du Canada : fichiers CSV "
    "de la Régie (débits et capacité des pipelines, exportations de "
    "pétrole, de gaz, de LGN, de GNL et de produits raffinés, droits "
    "pipeliniers, incidents, pétrole brut traité, Avenir énergétique du "
    "Canada) et interrogation de leurs lignes avec filtres par colonne et "
    "par période, en français ou en anglais."
)
