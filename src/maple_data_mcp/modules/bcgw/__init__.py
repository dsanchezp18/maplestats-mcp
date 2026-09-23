"""British Columbia's BC Geographic Warehouse (BCGW), served through
DataBC's public OGC WFS 2.0 endpoint at openmaps.gov.bc.ca.

Confirmed live 2026-09-22: this is a GeoServer WFS 2.0 deployment (the
service's own `GetCapabilities` response advertises the "GEOSERVER"
keyword), the same platform as NRCan's NBAC -- so this module reuses
`shared/wfs.py` unchanged rather than writing a new adaptor, per
AGENTS.md's adaptor-first philosophy.

BCGW holds thousands of layers; this module does not attempt to catalogue
them all. `bcgw_query_layer` is a generic escape hatch for any layer by
its `type_name` (an "OWNER_SCHEMA.TABLE_NAME" identifier, e.g.
"WHSE_MINERAL_TENURE.MTA_ACQUIRED_TENURE_SVW") -- discoverable from the
existing `ckan_*` catalogue tools (portal="bc"): a WFS/WMS-queryable BC dataset's
package carries a resource named "View WMS getCapabilities request
details" whose URL embeds the exact type_name right after
`openmaps.gov.bc.ca/geo/pub/`. Two curated, single-topic tools
(`bcgw_get_active_wildfires`, `bcgw_get_mining_tenure`) cover the two
domains most commonly asked for, with friendly parameter names mapped to
their real BCGW field names.
"""

MODULE_NAME = "bcgw"
MODULE_DESCRIPTION = (
    "BC Geographic Warehouse (BCGW), British Columbia's public geospatial "
    "data service (openmaps.gov.bc.ca), via standard OGC WFS 2.0: current "
    "wildfire perimeters/status, mining tenure (mineral/placer claims) by "
    "owner or area, and a generic layer-query tool reaching any of BCGW's "
    'thousands of layers by type_name (discoverable via ckan_* with portal="bc").'
)
MODULE_DESCRIPTION_FR = (
    "Entrepôt géographique de la Colombie-Britannique (BCGW), le service "
    "géospatial public de la C.-B. (openmaps.gov.bc.ca), via OGC WFS 2.0 "
    "standard : périmètres et statut des feux de forêt actuels, titres "
    "miniers (claims minéraux/placers) par propriétaire ou superficie, et "
    "un outil générique d'interrogation atteignant n'importe quelle des "
    'milliers de couches du BCGW par type_name (découvrable via ckan_* avec portal="bc").'
)
