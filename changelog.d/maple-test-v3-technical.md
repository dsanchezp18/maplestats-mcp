### Added

- Maple Test v3: 28 out-of-sample questions on technical data and documentation (survey
  scope and revision policies, units, NAICS and NOC codes, Valet series metadata, CMHC
  definitions, and dataset metadata and DataStore fields on five CKAN portals), keyed from
  the publishers' own APIs and pages (`build_key_v3.py`) and graded on the facts each
  answer must state (`python -m tests.maple_test run|grade --version v3`). The weekly key
  checks in `smoke.yml` and `maple-test.yml` now cover it.
