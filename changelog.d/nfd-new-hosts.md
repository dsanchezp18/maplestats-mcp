### Fixed

- `nfd_*` tools: the National Forestry Database moved from nfdp.ccfm.org to
  national-forestry-database.ca (French pages on
  base-donnees-national-forets.ca), and every tool refused the redirect to the
  new host. The module now reads the new hosts over http (their https
  certificate chain is incomplete) and still accepts the old one. A link that
  ends on the NFIS "not found" page, as the fire tables' comments links did on
  2026-10-26, is reported as a missing file instead of a refused redirect.
