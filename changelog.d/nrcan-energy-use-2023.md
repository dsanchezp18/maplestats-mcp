### Fixed

- `nrcan_energy_use_get_table`: Comprehensive Energy Use Database titles read
  "Residential Sector - Alberta - Table 1: ..." instead of the glued
  "Residential SectorAlberta1Table 1: ...". The database now runs to 2023 and
  the tools return it (no year bound in the client); the docstrings say so and
  explain page=0 (2000 and the latest six years) and page=1. oee.nrcan.gc.ca
  answers again, so the live smoke test runs these tools and reads a 2023 table.
