"""County of Grande Prairie Open Data (county-of-grande-prairie-open-data-cogp.hub.arcgis.com), an ArcGIS Hub deployment.

Confirmed live 2026-09-19 against the Hub Search API v3
(`/api/search/v1/collections/dataset/items`), the single-item detail
endpoint, the `/api/download/v1` export API, and the classic ArcGIS
REST FeatureServer/MapServer query API. Dataset content observed is
English-only -- `lang` is a documented no-op.
"""

MODULE_NAME = "arcgis_grande_prairie_county"
MODULE_DESCRIPTION = "County of Grande Prairie Open Data (county-of-grande-prairie-open-data-cogp.hub.arcgis.com): dataset search and detail, direct FeatureServer/MapServer row queries, and CSV/Shapefile/GeoJSON/KML download links. Distinct from the City of Grande Prairie's own portal (arcgis_grande_prairie_) -- confirmed live these are two separate governments with two separate catalogues. Confirmed live 2026-09-19 that at least one catalogue item (Fire Permit Zones) points at a broken `/arcgisadmin/rest/services/...` service url that returns HTTP 500 on any request; every other item checked used the working `/arcgis/rest/services/...` path on the same self-hosted opendataservices.countygp.ab.ca domain -- this is a portal-side data-quality issue in that one item's metadata, not a client bug."
MODULE_DESCRIPTION_FR = "Données ouvertes du comté de Grande Prairie (county-of-grande-prairie-open-data-cogp.hub.arcgis.com) : recherche et détail des jeux de données, requêtes directes sur les couches FeatureServer/MapServer, et liens de téléchargement CSV/Shapefile/GeoJSON/KML. Distinct du portail de la ville de Grande Prairie (arcgis_grande_prairie_)."
