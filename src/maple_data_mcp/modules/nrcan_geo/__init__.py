"""NRCan geolocation and the Canadian Geographical Names Database.

Two public, bilingual NRCan JSON APIs, confirmed live 2026-09-23:
- Geolocator (geolocator.api.geo.ca, the successor of the geogratis
  geolocation service, whose old URL now redirects and answers 500):
  places, street addresses, postal codes and FSAs to coordinates.
- Canadian Geographical Names Database (geogratis.gc.ca/services/
  geoname): official place names with type, status, province, map
  sheet and coordinates, searchable by text, point radius or bounding
  box. Datasets such as CanVec stay on `ckan_*` (portal="federal").
"""

MODULE_NAME = "nrcan_geo"
MODULE_DESCRIPTION = (
    "Natural Resources Canada geolocation and place names: locate a "
    "place, address or postal code (Geolocator), and search the Canadian "
    "Geographical Names Database for official names of cities, lakes, "
    "rivers, mountains and parks by text, province, feature type, point "
    "radius or bounding box, in English or French."
)
MODULE_DESCRIPTION_FR = (
    "Géolocalisation et noms géographiques de Ressources naturelles "
    "Canada : localiser un lieu, une adresse ou un code postal "
    "(Géolocalisateur), et rechercher dans la Base de données "
    "toponymiques du Canada les noms officiels de villes, lacs, rivières, "
    "montagnes et parcs par texte, province, type d'entité, rayon autour "
    "d'un point ou zone rectangulaire, en français ou en anglais."
)
