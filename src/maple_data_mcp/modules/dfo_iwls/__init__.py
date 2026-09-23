"""Fisheries and Oceans Canada Integrated Water Level System (IWLS) API.

api-iwls.dfo-mpo.gc.ca, the Canadian Hydrographic Service's public
REST/JSON API behind the tides.gc.ca/marees.gc.ca pages. Confirmed live
2026-09-23: ~1,575 tide and water-level stations with bilingual
time-series names, official observed levels (`wlo`), predictions
(`wlp`), and high/low tide predictions (`wlp-hilo`). DFO's other data
(fisheries surveys, catch statistics) is on open.canada.ca and already
reachable through `ckan_*` (portal="federal", organization:dfo-mpo).
"""

MODULE_NAME = "dfo_iwls"
MODULE_DESCRIPTION = (
    "Fisheries and Oceans Canada tides and water levels (Canadian "
    "Hydrographic Service IWLS API): search ~1,575 tide stations, station "
    "details and datums, observed water levels, water-level predictions, "
    "and high/low tide times for any window of up to 7 days."
)
MODULE_DESCRIPTION_FR = (
    "Marées et niveaux d'eau de Pêches et Océans Canada (API SINE du "
    "Service hydrographique du Canada) : recherche parmi environ 1 575 "
    "stations marégraphiques, détail des stations et niveaux de référence, "
    "niveaux d'eau observés, prédictions de niveaux d'eau et heures des "
    "pleines et basses mers pour toute période d'au plus 7 jours."
)
