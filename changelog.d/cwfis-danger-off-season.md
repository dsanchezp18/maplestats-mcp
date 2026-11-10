### Fixed

- `cwfis_get_fire_danger` no longer says a point in Canada is outside the grid
  when the fire season has ended there. Outside the season regions drop off the
  national fire danger map (on 2026-11-10 it covered Ottawa but not Kelowna,
  Edmonton or Whitehorse); the error now says so, and that no current rating
  does not mean no risk.
