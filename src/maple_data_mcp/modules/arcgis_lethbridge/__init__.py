"""Lethbridge Open Data Catalogue (opendata.lethbridge.ca), an ArcGIS Hub deployment.

Confirmed live 2026-09-19 against the Hub Search API v3
(`/api/search/v1/collections/dataset/items`), the single-item detail
endpoint, the `/api/download/v1` export API, and the classic ArcGIS
REST FeatureServer/MapServer query API. Dataset content observed is
English-only -- `lang` is a documented no-op.
"""

MODULE_NAME = "arcgis_lethbridge"
MODULE_DESCRIPTION = "City of Lethbridge Open Data Catalogue (opendata.lethbridge.ca): dataset search and detail, direct FeatureServer/MapServer row queries, and CSV/Shapefile/GeoJSON/KML download links."
MODULE_DESCRIPTION_FR = "Catalogue de données ouvertes de la ville de Lethbridge (opendata.lethbridge.ca) : recherche et détail des jeux de données, requêtes directes sur les couches FeatureServer/MapServer, et liens de téléchargement CSV/Shapefile/GeoJSON/KML."
