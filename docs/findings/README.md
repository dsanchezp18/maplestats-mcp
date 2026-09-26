# Findings

What each source turned out to need, checked against live responses. The
status of each source is in [`ROADMAP.md`](../../ROADMAP.md).

## Documents

- [CAPP Statistics Handbook](capp-statistics-handbook.md)
- [Competition Bureau Canada](competition-bureau.md)
- [Federal sources](federal-sources.md)
- [Municipal sources](municipal-sources.md)
- [Provincial sources](provincial-sources.md)
- [Census and specialized federal sources](specialized-federal-sources.md)
- [Territorial sources](territorial-sources.md)

## Coverage snapshot (2026-09-22)

Current implementation snapshot (2026-09-22): shipped modules cover
Statistics Canada, the Bank of Canada, federal CKAN, IRCC Express Entry,
Environment and Climate Change Canada / MSC GeoMet, CMHC, ISED (Corporations
Canada lookup + Spectrum Management System + CIPO Canadian Trademarks
Database search), Elections Canada (CKAN bulk/ DataStore data plus a
dedicated `elections_financial_returns` module for candidate campaign
financial returns), CRA's digital economy GST/HST registry, Health Canada
and ESDC (via `ckan_*`), NRCan's National Burned Area Composite, Alberta
(CKAN plus a dedicated `aer` module for Alberta Energy Regulator statistical
reports), British Columbia (CKAN plus a dedicated `bcgw` module for the BC
Geographic Warehouse's WFS layers), Ontario, Quebec (CKAN, including MSSS
ER-wait-time and health-installation DataStore resources), Nova Scotia, New
Brunswick, Manitoba, Saskatchewan, Prince Edward Island, Newfoundland and
Labrador, the Northwest Territories, Yukon, Montreal, Toronto, Regina,
Hamilton, London, Kitchener, Windsor, Saskatoon, Victoria, Surrey, Calgary,
Edmonton, Winnipeg, Ottawa, Halifax, Mississauga, Peel Region, Durham
Region, the Region of Waterloo, Metro Vancouver, York Region, Markham,
Newmarket, Aurora, Medicine Hat, the City and County of Grande Prairie, St.
Albert, Lethbridge, Airdrie, Strathcona County, and Vancouver (Laval and
Gatineau are covered through the existing Quebec CKAN module, not a
dedicated one). CRA, OSFI, and CRTC's own data are likewise already covered
through the federal CKAN module -- see the Census and specialized federal
agencies section below for what each turned out to need (or not need). All
10 provinces and 2 of 3 territories are now shipped (Nunavut is Blocked).
The rows below are the source-of-truth for remaining work; each row has its
own status.
