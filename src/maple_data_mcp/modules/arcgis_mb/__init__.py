"""Data MB (geoportal.gov.mb.ca), Manitoba's ArcGIS Hub deployment.

Confirmed live 2026-09-18 against the Hub Search API v3
(`/api/search/v1/collections/dataset/items`), the single-item detail
endpoint, the `/api/download/v1` export API, and the classic ArcGIS
REST FeatureServer/MapServer query API. Content is bilingual within
each field (English/French mixed across dataset titles and
descriptions, not split by language) rather than exposed through a
language-specific endpoint — `lang` is a documented no-op.
"""

MODULE_NAME = "arcgis_mb"
MODULE_DESCRIPTION = (
    "Data MB (geoportal.gov.mb.ca): Manitoba's ArcGIS Hub open-data catalogue, with "
    "dataset search and detail, direct FeatureServer/MapServer row queries, and "
    "CSV/Shapefile/GeoJSON/KML download links."
)
MODULE_DESCRIPTION_FR = (
    "Data MB (geoportal.gov.mb.ca) : catalogue de données ouvertes du Manitoba fondé "
    "sur ArcGIS Hub, avec recherche et détail des jeux de données, requêtes directes "
    "sur les couches FeatureServer/MapServer, et liens de téléchargement CSV/"
    "Shapefile/GeoJSON/KML."
)
