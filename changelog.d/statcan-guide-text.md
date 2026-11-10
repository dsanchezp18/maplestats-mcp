### Added

- `statcan_reference_get_publication`: a StatCan publication's editions and
  table of contents from its catalogue number ("71-543-G", "62-553-X",
  "13-017-X", "62F0014M2021011", any case) or a www150.statcan.gc.ca
  publication URL. It reads the catalogue page (/n1/en/catalogue/<number>)
  for the editions, newest first, then the chosen edition's main page for its
  title, release date, PDF link and sections: the page's own headings and the
  edition's other pages (chapters, appendices, glossary). `edition=` picks an
  older one ("2020001", "2020"). A PDF-only edition (15-203-X, the Guide to the
  Labour Force Survey up to 2006) is read from the PDF: its sections are the
  PDF's bookmarks, or its pages ("page=192") when it has none.
- `statcan_reference_get_section_text`: the text of a guide or methodology
  publication, to quote and cite instead of answering from memory: one
  section (`section=`, an id or title from `statcan_reference_get_publication`,
  a page id from an earlier result, or a page URL), or the sections best
  matching `query=` across up to 40 pages of the edition ("involuntary
  part-time" finds the definition in Section 3 of the Guide to the Labour Force
  Survey; "owned accommodation" chapter 10 of the CPI Reference Paper). A query
  reads first the pages whose titles hold its words and stops once enough
  sections hold every word: "owned accommodation" reads 6 of the CPI Reference
  Paper's 15 pages in about 2.5 s instead of 6 s. Plain text with headings and
  tables kept and menus, footers and modals dropped, cut at `max_chars` (6,000
  by default) with `next_start_char` to read on; each section carries its own
  URL and the result the edition's release date. PDF-only editions, or a PDF
  URL given as the publication, are read with pypdf (up to 25 MB and 400
  pages): pages and the headings inside them as sections, each cited as
  `<pdf>#page=N`, the same query and paging, and a note that line breaks,
  columns and tables may come out imperfect ("gross output approach" finds the
  provincial GDP allocation methods on page 192 of 15-203-X). English and
  French (`lang="fr"` reads the `-fra.htm` pages). Only www150.statcan.gc.ca and
  www.statcan.gc.ca are fetched, redirects included; pages and extracted PDF
  text are cached for a day.
- `statcan_reference_get_section_text` says where a concept is defined when it
  is not in the guide being searched: the supplementary unemployment rates R1
  to R8 in table 14-10-0077-01's footnotes (not in any edition of the LFS
  guide), and the provincial allocation of GDP by industry in 15-203-X.
- `plan_query` points definition and methodology questions about the LFS, the
  CPI and GDP and the national accounts to `statcan_reference_get_section_text`,
  questions on R1 to R8 to table 14-10-0077-01's footnotes
  (`wds_get_cube_metadata`), and the provincial allocation methods (gross
  output, selected factor incomes) to 15-203-X.
- pypdf (BSD-3-Clause, pure Python) is a new dependency, for PDF text.

### Changed

- `statcan_reference_search_documents` and `statcan_surveys_get_survey_metadata`
  say that their results hold titles, descriptions or metadata only, and point
  to `statcan_reference_get_section_text` for a guide's text.
