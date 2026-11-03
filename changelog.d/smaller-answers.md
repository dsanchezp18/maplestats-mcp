### Changed

- `search_tools` answers are about 60% smaller ("unemployment rate by province": 15.7 KB
  to 6.6 KB). Each tool comes back with its name, title, description, input schema and
  annotations; the output schema is left out, and so are the description's `Keywords`
  and `Mots-clés` lines, which only serve the ranking. The ranking itself is unchanged:
  the index still reads the whole docstring.
- `wds_get_cube_metadata` returns a footnote that WDS repeats under several ids once,
  with the other ids in the new `same_text_ids` field, and `footnote_limit` now
  defaults to 10 distinct texts (it was 25 footnotes, repeats included).
  `provenance.limits` says when footnotes were cut; pass a larger `footnote_limit` for
  the rest. The answer for table 14-10-0287 went from 36.6 KB to 18.8 KB.
- `provenance.reproduce` is one short sentence, and the Statistics Canada licence in
  `provenance.licence` gives the licence name, link and attribution. The rule that
  adapted data must not be presented as endorsed by the publisher is stated once in the
  server instructions instead of in every result. Fitness-for-use caveats are unchanged.
