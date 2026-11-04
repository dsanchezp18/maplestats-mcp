### Added

- `statcan_daily_get_upcoming_releases`: every release StatCan has scheduled for the next two
  weeks, from The Daily's Upcoming releases page, not only the major indicators the release
  calendar carries (annual surveys, studies, census tables). Each has its date, reference period,
  media lockup flag and StatCan contact. Also returns the list as a PDF and the link to the year's
  PDF of planned release dates for the major economic indicators.
- `statcan_daily_get_release_files`: the files behind a Daily release: its PDF, every table on its
  Tables tab (with the 8-digit product id), its surveys and their IMDB pages, the publications it
  links and its subjects. `previous` walks back up to 12 earlier releases of the same indicator.
  Releases from 2012 to 2017 cite old CANSIM numbers, which are matched to today's tables through
  the WDS inventory.
- `plan_query`'s topic for The Daily now includes both tools.
