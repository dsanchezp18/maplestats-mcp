### Changed

- `reproduce_code` writes scripts for `wds_get_full_table_download` again (it refused
  them since 2026-11-18). StatCan's full-table zips still answer scripts from most
  networks (cloud hosts and the hosted server, 2026-11-20), so the R, Python and Stata
  scripts download the zip and, only where StatCan answers it with its captcha, rebuild
  the same rows through WDS; Julia and Power Query read the zip alone. Checked live: the
  same final table by either route, in English and French.
- `wds_get_full_table_download`'s WDS rebuild script writes the edition asked for
  (`lang="fr"`: French names and headers, `;` between fields; it wrote the English
  edition before), and its `members` may name dimensions and members in French. Its
  notes no longer say that no script relies on `download_url`.

### Fixed

- The WDS rebuild of a full table (`wds_get_full_table_download`'s script and
  `wds_query_table`'s fallback sizing) wrote the wrong REF_DATE for occasional tables
  (2,585 tables: a year, not a year and month), occasional daily ones (17-10-0009: the
  whole date) and periods with two ends (a fiscal year `1991/1992`, a span `1994/1998`),
  asked too few periods of biweekly and occasional daily tables, and failed on a
  year-only `start_period`. Checked byte for byte against StatCan's own files on
  2026-11-20 (17-10-0009, 13-10-0064, 35-10-0044, 37-10-0104, 13-10-0849 whole;
  18-10-0004 and 14-10-0287 slices; English and French), except StatCan's own
  `"units "` with a trailing space in 13-10-0064's English file.
- R scripts for a StatCan full table computed no scaled value (their comment said
  cansim added one, but R reads StatCan's CSV itself since 2026-11-18); they now add
  `value_normalized` (`valeur_normalisee` in French), like the other languages.
