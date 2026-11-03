### Fixed

- `ourcommons_*` in French: the House of Commons moved its French feeds to French paths
  on www.noscommunes.ca by 2026-11-02 (`/deputes/fr/recherche`, `/position-des-partis`,
  `/conseil-des-ministres`, `/{id}/fonctions`); the old `/members/fr/...` paths now
  redirect to a 404 page, so every French call failed. English feeds use the published
  `/Members/en/.../XML` form. The English ministry feed (`/Members/en/ministries/XML`)
  also answers the 404 page as of 2026-11-03 and is not fixed yet.
- Live smoke tests: the workflow reports a run that ends SKIPPED (exit 75: a source down,
  locked or reloading) as a warning and in the job summary instead of failing the job and
  opening the smoke-failure issue. The modules smoke test counts `[upstream_unavailable]`
  errors and an EPS reload as skips; the EPS smoke test skips only its load-date check
  while EPS reloads.
