### Added

- `statcan_reference_get_publication`: a StatCan publication's editions and
  table of contents from its catalogue number ("71-543-G", "62-553-X",
  "13-017-X", "62F0014M2021011", any case) or a www150.statcan.gc.ca
  publication URL. It reads the catalogue page (/n1/en/catalogue/<number>)
  for the editions, newest first, then the chosen edition's main page for its
  title, release date, PDF link and sections: the page's own headings and the
  edition's other pages (chapters, appendices, glossary). `edition=` picks an
  older one ("2020001", "2020"); a PDF-only edition (15-203-X) says so and
  gives the link.
- `statcan_reference_get_section_text`: the text of a guide or methodology
  publication, to quote and cite instead of answering from memory: one
  section (`section=`, an id or title from `statcan_reference_get_publication`
  or a page URL), or the sections best matching `query=` across up to 40 pages
  of the edition ("involuntary part-time" finds the definition in Section 3 of
  the Guide to the Labour Force Survey; "owned accommodation" chapter 10 of the
  CPI Reference Paper). Plain text with headings and tables kept and menus,
  footers and modals dropped, cut at `max_chars` (6,000 by default) with
  `next_start_char` to read on; each section carries its own URL and the
  result the edition's release date. English and French (`lang="fr"` reads the
  `-fra.htm` pages). Only www150.statcan.gc.ca and www.statcan.gc.ca are
  fetched, redirects included; pages are cached for a day.
- `plan_query` points definition and methodology questions about the LFS, the
  CPI and GDP and the national accounts to `statcan_reference_get_section_text`.

### Changed

- `statcan_reference_search_documents` and `statcan_surveys_get_survey_metadata`
  say that their results hold titles, descriptions or metadata only, and point
  to `statcan_reference_get_section_text` for a guide's text.
