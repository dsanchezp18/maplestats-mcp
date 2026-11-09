### Added

- `docs_read_resource` and `docs_list_resources`: read any of the server's `docs://` pages (per-source gotchas, well-known series and categories, `docs://catalogue`, ...) through `call_tool`, for hosted clients that show the model only `search_tools`, `call_tool` and `plan_query` and never offer MCP resources. With `lang="fr"` an English page with a French version returns that version. `SERVER_INSTRUCTIONS` says so in one line.
- `docs://cmhc/rms-methodology` (French: `docs://cmhc/fr/methodologie-ell`): the CMHC Rental Market Survey's methodology from CMHC's own pages, with their URLs: October timing (the April survey ended in 2015), scope (privately initiated structures of 3 or more rental units in urban areas of 10,000 or more; the secondary rental market's Condo Apartment Survey in 17 CMAs), vacancy, availability (collected 2005 to 2017 only), turnover and rent definitions, the a/b/c/d reliability codes with CMHC's CV tables, and the release rules (4 or more responding entities, CV of 10 % or less for averages).
- `cmhc_get_table_data` results carry `flag_legend`: what each flag in the result means (a/b/c/d reliability, `**` suppressed, `++` not significant, `n/a`), in the call's language, since HMIP's own CSV notes give the legend only for some tables.

### Fixed

- The CMHC docs said a `-` cell is a counted zero and that `++` means not applicable; CMHC defines `-` as no units in the universe for the category and `++` as a rent change not statistically different from zero.
