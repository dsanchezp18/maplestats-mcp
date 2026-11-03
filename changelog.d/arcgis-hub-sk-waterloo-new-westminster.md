### Added

- `arcgis_hub_*`: three portals. `portal="sk"` is the Saskatchewan GeoHub
  (geohub.saskatchewan.ca, 129 provincial geospatial datasets), back after its
  2026-10-03 removal: saskatchewan.ca's terms of use exclude its sub-sites, and
  most items carry the Government of Saskatchewan Standard Unrestricted Use
  Data Licence v2.0, which allows commercial use. `portal="waterloo"` is the
  City of Waterloo (data.waterloo.ca, Waterloo Open Data User Licence),
  distinct from the Region of Waterloo's `portal="waterloo_region"`; its
  catalogue also lists Kitchener, Region and Cambridge items under their own
  licences. `portal="new_westminster"` is the City of New Westminster
  (opendata.newwestcity.ca, Open Government Licence - City of New Westminster
  v1.0); searches default to Feature Service, as the site has only the "all"
  collection.
- `plan_query`: "Waterloo" alone now maps to the City of Waterloo and the
  Region's portal, "Region of Waterloo" to the Region only; New Westminster
  and the Saskatchewan GeoHub are mapped too.

### Changed

- The City of Hamilton (open.hamilton.ca) and Niagara Open Data
  (niagaraopendata.ca, the Region's CKAN catalogue) were checked again on
  2026-11-03 and stay out: both answer automated requests with a Cloudflare
  challenge.
