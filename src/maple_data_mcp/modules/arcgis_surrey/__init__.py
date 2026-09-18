"""City of Surrey Open Data Catalog (opendata-surrey.hub.arcgis.com), an ArcGIS Hub deployment.

Confirmed live 2026-09-18 against the Hub Search API v3
(`/api/search/v1/collections/dataset/items`), the single-item detail
endpoint, the `/api/download/v1` export API, and the classic ArcGIS
REST FeatureServer/MapServer query API. `data.surrey.ca` (this
portal's older CKAN-era URL) now 301-redirects here, confirmed live —
this is the current, canonical portal. Dataset content observed is
English-only — `lang` is a documented no-op.
"""

MODULE_NAME = "arcgis_surrey"
MODULE_DESCRIPTION = (
    "City of Surrey Open Data Catalog (opendata-surrey.hub.arcgis.com): the City "
    "of Surrey, BC's ArcGIS Hub open-data catalogue, with dataset search and "
    "detail, direct FeatureServer/MapServer row queries, and CSV/Shapefile/"
    "GeoJSON/KML download links."
)
MODULE_DESCRIPTION_FR = (
    "Catalogue de données ouvertes de la Ville de Surrey (opendata-surrey.hub."
    "arcgis.com) : catalogue de données ouvertes fondé sur ArcGIS Hub, avec "
    "recherche et détail des jeux de données, requêtes directes sur les couches "
    "FeatureServer/MapServer, et liens de téléchargement CSV/Shapefile/GeoJSON/KML."
)
