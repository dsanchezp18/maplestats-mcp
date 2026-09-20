"""Natural Resources Canada's National Burned Area Composite (NBAC), an OGC WFS deployment.

Confirmed live 2026-09-20 against the Canadian Wildland Fire
Information System (CWFIS) GeoServer instance
(cwfis.cfs.nrcan.gc.ca/geoserver, layer `public:nbac`). NBAC is a
national, annually-compiled polygon dataset of burned area for every
fire event mapped in Canada since 1972 (jointly produced by the Canada
Centre for Mapping and Earth Observation and the Canadian Forest
Service) -- see shared/wfs.py for the OGC WFS 2.0 platform quirks this
module relies on.
"""

MODULE_NAME = "nrcan_nbac"
MODULE_DESCRIPTION = (
    "Natural Resources Canada's National Burned Area Composite (NBAC): fire "
    "polygons, reported/adjusted start and end dates, and adjusted burned area (hectares) "
    "for every mapped fire event in Canada since 1972, filterable by year, province/"
    "territory, and fire id via an OGC WFS 2.0 CQL_FILTER query."
)
MODULE_DESCRIPTION_FR = (
    "Composite national des zones brûlées (CNZB) de Ressources naturelles Canada : "
    "polygones d'incendies, dates de début et de fin déclarées/ajustées, et "
    "superficie brûlée ajustée (hectares) pour chaque incendie cartographié "
    "au Canada depuis 1972, filtrable par année, province/territoire et identifiant "
    "d'incendie via une requête OGC WFS 2.0 CQL_FILTER."
)
