### Added

- `plan_query`: four topics for administrative records, in English and French:
  building permits and construction (StatCan table 34-10-0292, CMHC starts, and
  permit records for Calgary, Edmonton, Winnipeg, Vancouver, Toronto, Montreal,
  Laval, Regina, Halifax, Surrey, Victoria and five more Ontario cities), business
  licences (city licence registers and StatCan's Canadian Business Counts),
  restaurant and food premises inspections (Toronto DineSafe, Montreal, Quebec's
  MAPAQ counts, Fraser Health through Surrey) and planning and development
  applications (rezonings, development permits, site plans). Each step names the
  portal and dataset to read with the existing readers, checked live on 2026-10-27,
  and the step for a city named in the question comes first.

### Changed

- `plan_query`: a question about building permits now leads with the building
  permits topic rather than housing; housing still follows it.
