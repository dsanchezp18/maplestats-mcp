"""Metro Vancouver Open Data Portal (open-data-portal-metrovancouver.hub.arcgis.com), an ArcGIS Hub deployment.

Confirmed live 2026-09-19 against the Hub Search API v3
(`/api/search/v1/collections/dataset/items`), the single-item detail
endpoint, the `/api/download/v1` export API, and the classic ArcGIS
REST FeatureServer/MapServer query API. Dataset content observed is
English-only -- `lang` is a documented no-op.
"""

MODULE_NAME = "arcgis_metro_vancouver"
MODULE_DESCRIPTION = "Metro Vancouver Open Data Portal (open-data-portal-metrovancouver.hub.arcgis.com): dataset search and detail, direct FeatureServer/MapServer row queries, and CSV/Shapefile/GeoJSON/KML download links."
MODULE_DESCRIPTION_FR = "Portail de données ouvertes de Metro Vancouver (open-data-portal-metrovancouver.hub.arcgis.com) : recherche et détail des jeux de données, requêtes directes sur les couches FeatureServer/MapServer, et liens de téléchargement CSV/Shapefile/GeoJSON/KML."
