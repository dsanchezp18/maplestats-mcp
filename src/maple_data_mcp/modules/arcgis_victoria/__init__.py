"""City of Victoria Open Data Portal (opendata.victoria.ca), an ArcGIS Hub deployment.

Confirmed live 2026-09-18 against the Hub Search API v3
(`/api/search/v1/collections/dataset/items`), the single-item detail
endpoint, the `/api/download/v1` export API, and the classic ArcGIS
REST FeatureServer/MapServer query API. Dataset content observed is
English-only — `lang` is a documented no-op.
"""

MODULE_NAME = "arcgis_victoria"
MODULE_DESCRIPTION = (
    "City of Victoria Open Data Portal (opendata.victoria.ca): the City of "
    "Victoria, BC's ArcGIS Hub open-data catalogue (VicMap), with dataset search "
    "and detail, direct FeatureServer/MapServer row queries, and CSV/Shapefile/"
    "GeoJSON/KML download links."
)
MODULE_DESCRIPTION_FR = (
    "Portail de données ouvertes de la Ville de Victoria (opendata.victoria.ca) : "
    "catalogue de données ouvertes (VicMap) fondé sur ArcGIS Hub, avec recherche "
    "et détail des jeux de données, requêtes directes sur les couches "
    "FeatureServer/MapServer, et liens de téléchargement CSV/Shapefile/GeoJSON/KML."
)
