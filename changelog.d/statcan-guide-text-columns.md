### Fixed

- `statcan_reference_get_section_text` and `statcan_reference_get_publication`
  read the bilingual pages of 15-203-X (Provincial Gross Domestic Product by
  Industry), printed with English and French side by side, a column at a time,
  and keep only the column in `lang`: pages 188 to 196 (the gross output and
  selected factor incomes approaches) now read as clean English, or as clean
  French with `lang="fr"`, instead of lines of both interleaved with accented
  words split ("constitu ées"). Such a page is laid out again with pypdf's
  layout mode to find the gutter; a table across the page stays as it was, and
  one-column PDFs are read as before. The result says how many pages had a
  column dropped. Extracting all 277 pages takes about 4 s longer (13 s
  instead of 9 s, measured on a busy machine).
- PDF section headings: a table's labels and wrapped cells ("Vanity
  Industries", "NFLD. - T.-N.", "Government Business Total") are no longer
  taken for headings, since a heading must now be followed by running text;
  headings with one word in lower case ("Approach based on Selected Factor
  Incomes", "Perspective on the use of the Income and Expenditure Accounts")
  and, on two-column pages, French headings in sentence case are.
- A query whose words are stems ("gross" is searched as "gros") now gets its
  phrase bonus, counted five times at most, so the "Gross Output Approach"
  heading on page 192 of 15-203-X ranks above the statistical tables that repeat
  "gross output" in every row.
- 13-017-X's 2008 edition links the PDF of the whole edition from its side menu
  only; it is now found (`pdf_url`). When a query reads the 40-page cap of an
  edition with more pages than that and such a PDF, the PDF (one download,
  every page) is searched too: matches on pages already read stay cited by
  their HTML page, the others by their PDF page (`#page=N`). The provenance
  says so. Queries that stop early are unchanged ("supplementary labour
  income" reads 5 pages, "provincial allocation" about 30).
- `statcan_reference_get_section_text`'s description no longer says a query
  searches every page of the edition; it says up to 40 pages, then the whole
  PDF where there is one.
