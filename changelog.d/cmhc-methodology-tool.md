### Added

- `cmhc_get_methodology`: CMHC's survey methodology and definitions as a tool,
  for the Rental Market Survey (reliability codes and their CV thresholds,
  suppression, the release rule of 4 or more responding entities, vacancy and
  availability) and, new, the Starts and Completions Survey and Market Absorption
  Survey (start, completion, absorbed: sold and completed, when a unit counts as
  sold, unabsorbed units, SAAR, dwelling types), in English or French. The Rental
  Market Survey text was only a `docs://` resource, which `search_tools` does not
  find, and the absorption survey's was not in the server: in the Maple Test, both
  kinds of question were answered from memory. The new text is also served as
  `docs://cmhc/starts-absorption-methodology` (French:
  `docs://cmhc/fr/methodologie-mises-en-chantier`).

### Changed

- `cmhc_get_table_data`, its `flag_legend` and the CMHC fitness note now point to
  `cmhc_get_methodology` instead of the `docs://cmhc/rms-methodology` resource.
