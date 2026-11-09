### Added

- `statcan_surveys_get_survey_metadata` reads the whole IMDB record, not only its status, frequency, description and subjects. `methodology` holds the eleven sections as text (`target_population`, `instrument_design`, `sampling`, `data_sources`, `error_detection`, `imputation`, `estimation`, `quality_evaluation`, `disclosure_control`, `revisions_and_seasonal_adjustment`, `data_accuracy`), and short fields give the record's `reference_period` and `collection_period`, whether response is `mandatory` or `voluntary` (`response`), how data are obtained (`collection_methods`), the design (`survey_design`) and the sentences that give the sample's size (`sample_size`). A new optional `section` argument (one name or a list) returns those sections in full and no others; without it every section is cut to about 900 characters at a sentence end, `trimmed_sections` names the cut ones and `provenance.limits` says how to get them whole.

### Fixed

- `statcan_surveys_get_survey_metadata` with `lang="fr"`: `status` and `frequency` were always empty, because the French record labels them "Statut" and "Fréquence".
