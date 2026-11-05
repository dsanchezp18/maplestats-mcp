### Added

- `statcan_daily_get_release_calendar` and `statcan_daily_get_upcoming_releases` say what
  is known when nothing scheduled matches: `not_scheduled` gives the same release's last
  dates (the provincial and territorial economic accounts came out on 2025-11-06,
  2024-11-07 and 2023-11-08), any release of it already scheduled (the 2025 accounts on
  2026-11-05), and an estimate from the usual gap, labelled as an estimate and never as a
  date Statistics Canada announced.

### Fixed

- The release calendars ignore words that only ask the question ("next", "release",
  "date"): "next consumer price index release" matched nothing scheduled.
