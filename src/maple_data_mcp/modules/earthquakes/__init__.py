"""Earthquakes Canada (NRCan) event catalogue via its FDSN web service.

earthquakescanada.nrcan.gc.ca/fdsnws/event/1/query follows the FDSN
event web-service standard. Built from that standard, then
verified live 2026-09-24 (see constants.py for the quirks found).
"""

MODULE_NAME = "earthquakes"
MODULE_DESCRIPTION = (
    "Earthquakes Canada (Natural Resources Canada) event catalogue: search "
    "earthquakes in and near Canada by date range, magnitude, region box or "
    "distance from a point, or look one up by event ID."
)
MODULE_DESCRIPTION_FR = (
    "Catalogue des séismes de Séismes Canada (Ressources naturelles Canada) : "
    "recherche des tremblements de terre au Canada et à proximité par période, "
    "magnitude, zone géographique ou distance d'un point, ou par identifiant "
    "d'événement."
)
