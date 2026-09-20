"""City of Airdrie Open Data (data-airdrie.opendata.arcgis.com), an ArcGIS Hub deployment.

Confirmed live 2026-09-19 against the Hub Search API v3
(`/api/search/v1/collections/dataset/items`), the single-item detail
endpoint, the `/api/download/v1` export API, and the classic ArcGIS
REST FeatureServer/MapServer query API. Dataset content observed is
English-only -- `lang` is a documented no-op.
"""

MODULE_NAME = "arcgis_airdrie"
MODULE_DESCRIPTION = "City of Airdrie Open Data (data-airdrie.opendata.arcgis.com): dataset search and detail, direct FeatureServer/MapServer row queries, and CSV/Shapefile/GeoJSON/KML download links."
MODULE_DESCRIPTION_FR = "Données ouvertes de la ville d'Airdrie (data-airdrie.opendata.arcgis.com) : recherche et détail des jeux de données, requêtes directes sur les couches FeatureServer/MapServer, et liens de téléchargement CSV/Shapefile/GeoJSON/KML."
