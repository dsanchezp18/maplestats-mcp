### Added

- Every result's `provenance` has a new `commercial_use` field saying whether the
  publisher's terms allow commercial reuse without asking: `allowed`,
  `not_allowed` (non-commercial use only, or written permission needed, as for
  the Canada.ca terms, CIHI, CMHC, the PBO, the AER, the CBSA's Customs Tariff,
  CREA, the Institut de la statistique du Québec and Parliament), `varies`
  (CKAN, ArcGIS Hub, Socrata, Borealis and other platforms whose datasets or
  feeds each carry their own licence) or `unknown` (terms silent, conflicting or
  not found). It comes from one table next to the licence texts in
  `shared/licences.py`, checked against each publisher's terms page, not from
  parsing the text; `provenance.licence` is unchanged. Null where no licence
  applies, as for `plan_query`.
