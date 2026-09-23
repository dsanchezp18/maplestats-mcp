"""Canadian provincial and municipal ArcGIS Hub open-data portals.

Confirmed live 2026-09-18 to 2026-09-20 against every portal in
constants.PORTALS: the Hub Search API v3
(`/api/search/v1/collections/dataset/items`), the single-item detail
endpoint, the `/api/download/v1` export API, and the classic ArcGIS
REST FeatureServer/MapServer query API. Content is English-only except
Manitoba, Saskatchewan, and Prince Edward Island, whose content is
bilingual within each field rather than split by language — `lang` is
a documented no-op on every portal.
"""

MODULE_NAME = "arcgis_hub"
MODULE_DESCRIPTION = (
    "Provincial and municipal ArcGIS Hub open-data portals (Manitoba, Saskatchewan, PEI, "
    "Ottawa, Halifax, Hamilton, Durham, York, Peel, Metro Vancouver, and 18 more): dataset "
    "search and detail, direct FeatureServer/MapServer row queries, and CSV/Shapefile/"
    "GeoJSON/KML download links. Call arcgis_hub_list_portals for every portal key."
)
MODULE_DESCRIPTION_FR = (
    "Portails de données ouvertes ArcGIS Hub provinciaux et municipaux (Manitoba, "
    "Saskatchewan, Î.-P.-É., Ottawa, Halifax, Hamilton, Durham, York, Peel, Metro Vancouver "
    "et 18 autres) : recherche et détail des jeux de données, requêtes directes sur les "
    "couches FeatureServer/MapServer, et liens de téléchargement CSV/Shapefile/GeoJSON/KML. "
    "Appelez arcgis_hub_list_portals pour la liste des clés de portail."
)
