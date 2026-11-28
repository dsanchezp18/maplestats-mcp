### Fixed

- `wds_get_series_as_of`: when a member name repeats and the real-time table words the
  parent differently ("Goods" against "Goods-producing industries"), no candidate was left
  under the parent and the call failed even when exactly one candidate had the member's
  classification code. When the parent leaves no candidate, the code now picks among all
  of them; the call still fails, and lists the candidates, unless exactly one matches. A
  refusal or "no revision history" message in French also failed with a KeyError when WDS
  sent no French name for a member or a dimension; it now shows the English name.
- `statcan_reference_get_section_text`: when the time ran out before a scanned page's work
  began (the wait for the OCR engine used it), the note said the time "ran out while it
  was reading page N". It now says it ran out before OCR could start reading that page,
  in English and French; a stop inside the page keeps the earlier wording.
- Scanned-PDF reading (OCR): the hash of the file that keys the page cache was computed on
  the server's event loop, so a scan of several MB held every other call for the length of
  the hash. It is now computed in the worker pool; the cache key is unchanged.
- `wds_query_series`, `wds_query_table`, `eurostat_query_dataset` and
  `oecd_query_dataset`: the `mixed_adjustment` refusal still listed only "seasonally
  adjusted, unadjusted or trend-cycle" although a calendar adjusted value mixed with an
  unadjusted one also triggers it. The message now names calendar adjusted, in English and
  French.
- Chat demo, "Download CSV": a number written for reading, with thousands commas or a
  percent sign (`-1,234.5`, `-5%`), was treated as a formula and got a leading apostrophe,
  so a spreadsheet read it as text. It stays a number; anything else that starts with `=`,
  `+`, `-`, `@`, a tab or a carriage return (`-Infinity`, `-1+2`, `-1,23`) is still
  neutralized.
