### Added

- `statcan_pumf_tabulate`: standard errors and CVs for the Labour Force Survey PUMF
  (71M0001X), which ships no bootstrap weights. The server builds the calibrated
  Poisson bootstrap that the LFS PUMF User Guide 2025 prescribes (sections 6.1 and
  6.2, Appendix A): 1,000 replicate weights calibrated to the 220 province, age group
  and gender domains of Appendix B, with a fixed seed so a table repeats exactly. It
  works for totals, shares and means. On the October 2026 file, unemployment by
  province matches Table 14-10-0287 and the standard errors fall within 0% to 15% of
  the published ones.
- `statcan_pumf_tabulate`: each cell has a new `quality` field: acceptable, marginal
  or unacceptable, per the LFS guide's Table 5 (5 or more respondents; CV under 15%,
  15% to 35%, above 35%). Cells are flagged, not suppressed. The field is null where
  a guide's rule has not been checked.
- `statcan_pumf_tabulate` and `statcan_pumf_get_codebook` read SAS (`.sas7bdat`), SPSS
  (`.sav`, `.zsav`) and Stata (`.dta`) data files when a ZIP has no CSV or
  fixed-width file, such as the Canada's Core Public Infrastructure Survey PUMF
  (34-25-0001, 2020 and 2022). With no codebook file in the ZIP, the variables come
  from the data file itself. The file is converted once, in chunks, to a cached CSV.
  The new dependency is `pyreadstat` (Apache-2.0, over the MIT ReadStat library),
  because DuckDB 2.0 has no reader for these formats. On the 86 MB CCPI 2022 file the
  first table took 31 s with a 194 MB peak process memory, and later tables took 4 s.
