"""Prince Edward Island's open-data portal (data.princeedwardisland.ca), an ArcGIS Hub deployment.

Confirmed live 2026-09-18 against the Hub Search API v3
(`/api/search/v1/collections/dataset/items`), the single-item detail
endpoint, the `/api/download/v1` export API, and the classic ArcGIS
REST FeatureServer/MapServer query API. Content is bilingual within
each field (English/French mixed across dataset titles and
descriptions, not split by language) rather than exposed through a
language-specific endpoint — `lang` is a documented no-op.
"""

MODULE_NAME = "arcgis_pe"
MODULE_DESCRIPTION = (
    "Prince Edward Island's open-data portal (data.princeedwardisland.ca): PEI's ArcGIS "
    "Hub open-data catalogue, with dataset search and detail, direct FeatureServer/"
    "MapServer row queries, and CSV/Shapefile/GeoJSON/KML download links."
)
MODULE_DESCRIPTION_FR = (
    "Portail de données ouvertes de l'Île-du-Prince-Édouard (data.princeedwardisland.ca) : "
    "catalogue de données ouvertes fondé sur ArcGIS Hub, avec recherche et détail des "
    "jeux de données, requêtes directes sur les couches FeatureServer/MapServer, et "
    "liens de téléchargement CSV/Shapefile/GeoJSON/KML."
)
