"""Town of Aurora Data Hub (town-of-aurora-data-hub-aurora.hub.arcgis.com), an ArcGIS Hub deployment.

Confirmed live 2026-09-19 against the Hub Search API v3
(`/api/search/v1/collections/dataset/items`), the single-item detail
endpoint, the `/api/download/v1` export API, and the classic ArcGIS
REST FeatureServer/MapServer query API. Dataset content observed is
English-only -- `lang` is a documented no-op.
"""

MODULE_NAME = "arcgis_aurora"
MODULE_DESCRIPTION = "Town of Aurora Data Hub (town-of-aurora-data-hub-aurora.hub.arcgis.com): dataset search and detail, direct FeatureServer/MapServer row queries, and CSV/Shapefile/GeoJSON/KML download links. Confirmed live 2026-09-19 that the similarly-named opendata-cityofaurora.hub.arcgis.com is a different city (Aurora, Illinois, hosted by Esri on that city's behalf) and not this source."
MODULE_DESCRIPTION_FR = "Portail de données de la ville d'Aurora, Ontario (town-of-aurora-data-hub-aurora.hub.arcgis.com) : recherche et détail des jeux de données, requêtes directes sur les couches FeatureServer/MapServer, et liens de téléchargement CSV/Shapefile/GeoJSON/KML. Confirmé en direct le 2026-09-19 que le domaine au nom similaire opendata-cityofaurora.hub.arcgis.com appartient à une autre ville (Aurora, Illinois) et n'est pas cette source."
