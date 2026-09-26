"""Canadian Grain Commission (CGC) grain statistics.

The CGC publishes its statistics as CSV files on grainscanada.gc.ca, not
through an API. The federal CKAN records under organization `cgc-ccg` point
at some of these files but stop at crop year 2024-25 and are not
DataStore-active, so current data is only reachable here. Checked live
2026-09-26:

- Grain Statistics Weekly: one long-format CSV per crop year (2013-14 on),
  replaced each Thursday with every week so far. Twelve worksheets
  (primary, process and terminal elevators, feed grains, producer cars,
  imported grains, stock summary), in thousands of tonnes.
- Exports of grain from licensed facilities: one CSV of monthly exports by
  grain, grade, elevator type, port region and destination country,
  January 2013 onward.

Terms: Open Government Licence - Canada (the CKAN records' licence).
"""

MODULE_NAME = "cgc"
MODULE_DESCRIPTION = (
    "Canadian Grain Commission (grainscanada.gc.ca, tools prefixed cgc_): Grain "
    "Statistics Weekly by crop year from 2013-14 (producer deliveries, shipments "
    "and stocks at primary and process elevators by province, terminal receipts, "
    "exports, stocks and disposition by port and grade, feed grains, producer "
    "cars, imported grains, stock summary; thousands of tonnes, updated each "
    "Thursday) and monthly grain exports from licensed facilities by grain, "
    "grade, port and destination country since January 2013. Filters, weekly or "
    "summed results, English or French labels."
)
MODULE_DESCRIPTION_FR = (
    "Commission canadienne des grains (grainscanada.gc.ca, outils préfixés cgc_) : "
    "Statistiques hebdomadaires sur le grain par campagne agricole depuis 2013-2014 "
    "(livraisons des producteurs, expéditions et stocks aux silos primaires et de "
    "transformation par province, arrivages, exportations, stocks et écoulement aux "
    "silos terminaux par port et grade, grains fourragers, wagons de producteurs, "
    "grains importés, sommaire des stocks; milliers de tonnes, mis à jour chaque "
    "jeudi) et exportations mensuelles de grain à partir d'installations agréées "
    "par grain, grade, port et pays de destination depuis janvier 2013. Filtres, "
    "résultats hebdomadaires ou additionnés, libellés en français ou en anglais."
)
