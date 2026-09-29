"""Canadian Wildland Fire Information System (CWFIS), Natural Resources Canada.

Confirmed live 2026-09-29. Two upstreams: the CWFIS GeoServer OGC WFS 2.0
(cwfis.cfs.nrcan.gc.ca/geoserver, the same deployment nrcan_nbac uses for the
burned-area composite, which this module deliberately does not duplicate) and
the national situation-report JSON API (api.cwfif.nrcan.gc.ca) that the
CWFIS website itself calls.
"""

MODULE_NAME = "cwfis"
MODULE_DESCRIPTION = (
    "Canadian Wildland Fire Information System (NRCan): satellite fire hotspots "
    "(last 24 hours or archive since 1994), current-season estimated fire perimeters, "
    "daily fire weather stations with Fire Weather Index (FWI) components, station "
    "fire-weather forecasts, fire danger class at a point, the National Fire Database "
    "of large fires (200 ha and over, 1980-2023) and the weekly national wildfire "
    "situation reports (fires, area burned, preparedness level, 1998 onward)."
)
MODULE_DESCRIPTION_FR = (
    "Système canadien d'information sur les feux de végétation (RNCan) : points chauds "
    "satellitaires (dernières 24 heures ou archives depuis 1994), périmètres estimés de la "
    "saison en cours, stations météo avec indices de l'Indice Forêt-Météo (IFM), prévisions "
    "météo-incendie par station, classe de danger d'incendie à un point, Base de données "
    "nationale sur les feux (grands feux de 200 ha et plus, 1980-2023) et rapports "
    "hebdomadaires nationaux sur la situation des feux (nombre, superficie, niveau de "
    "préparation, depuis 1998)."
)
