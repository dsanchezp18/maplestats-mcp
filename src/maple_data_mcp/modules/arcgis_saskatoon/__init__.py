"""City of Saskatoon Open Data Site (data-citysaskatoon.opendata.arcgis.com), an ArcGIS Hub deployment.

Confirmed live 2026-09-18 against the Hub Search API v3
(`/api/search/v1/collections/dataset/items`), the single-item detail
endpoint, the `/api/download/v1` export API, and the classic ArcGIS
REST FeatureServer/MapServer query API. Dataset content observed is
English-only — `lang` is a documented no-op.
"""

MODULE_NAME = "arcgis_saskatoon"
MODULE_DESCRIPTION = (
    "City of Saskatoon Open Data Site (data-citysaskatoon.opendata.arcgis.com): "
    "the City of Saskatoon's ArcGIS Hub open-data catalogue, with dataset search "
    "and detail, direct FeatureServer/MapServer row queries, and CSV/Shapefile/"
    "GeoJSON/KML download links."
)
MODULE_DESCRIPTION_FR = (
    "Site de données ouvertes de la Ville de Saskatoon (data-citysaskatoon."
    "opendata.arcgis.com) : catalogue de données ouvertes fondé sur ArcGIS Hub, "
    "avec recherche et détail des jeux de données, requêtes directes sur les "
    "couches FeatureServer/MapServer, et liens de téléchargement CSV/Shapefile/"
    "GeoJSON/KML."
)
