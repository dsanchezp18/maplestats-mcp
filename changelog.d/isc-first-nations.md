### Added

- Indigenous Services Canada and CIRNAC (`isc_`, 5 tools), in English and French.
  `isc_search_first_nations` finds a First Nation by name, band number or
  province among the 646 registry groups of ISC's registered population dataset
  (OGL - Canada); `isc_get_first_nation_profile` reads CIRNAC's First Nation
  Profiles: official name, address, tribal council, reserves with their
  hectares, membership authority, election system, chief and council, and
  geographic zone; `isc_get_registered_population` gives the population
  registered under the Indian Act by sex and residence for the latest month,
  with the yearly figures since 2023; `isc_list_drinking_water_advisories` lists
  long-term drinking water advisories on public systems, current and lifted
  since November 2015, from the file behind ISC's map; and
  `isc_list_short_term_advisories` lists short-term advisories south of 60
  (British Columbia's are the First Nations Health Authority's). Profiles and
  advisories fall under the Canada.ca terms (non-commercial reproduction with
  attribution).

### Changed

- The English discovery case "ocean water temperature buoy" now expects
  `dfo_iwls_search_stations`, its top result; `dfo_iwls_get_water_levels` had
  matched on "water" alone.
