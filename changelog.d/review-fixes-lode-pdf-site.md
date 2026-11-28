### Fixed

- `statcan_lode_*`: a StatCan page that was not the LODE page (HTTP 406 or 409, which the
  shared client hands back instead of raising, or a maintenance or empty page sent with a
  200) was kept for a day. Every `statcan_lode_list_files` and `statcan_lode_query` call then
  said "No ZIP downloads found ... StatCan may have moved them", and
  `statcan_lode_list_databases` listed every database with no releases. Such a page is now an
  upstream error and is not kept, so the next call reads the page again.
- `statcan_lode_preview_member` and `statcan_lode_describe`: records whose number of fields
  differs from the header were passed over without a word, so a `match` lookup could say "No
  row matched" while records had never been compared. The result's notes now say how many
  records were skipped.
- `statcan_lode_query` and `statcan_lode_describe`: the unpacked copy of a ZIP was kept under
  its URL and member name alone, so a release published under the same link was never read
  once the first had been cached. The copy is now named for the archive's size and the
  member's as well, which the call reads anyway, so a rebuilt file is downloaded again.
- `statcan_reference_*` on PDF editions: a compound cut at the end of a line, "self-" over
  "employed" or "non-" over "farm", lost its hyphen ("selfemployed", "nonfarm"), so a search
  for "self-employed" missed the paragraph. The hyphen is kept when the first part only forms
  compounds (self-, non-, semi-, quasi-, sous-, demi-) or when the document hyphenates the
  same pair elsewhere; a word the typesetter split ("statis-" over "tics") is joined as before.
- Website, home page: the French demo had no French spacing (its text is JSON in a script, which
  the typography pass skips). It now spaces `?`, `:`, `%`, `$` and « » as the rest of the French
  site does, names the Parliamentary Budget Officer's outlook month in French (it read "June
  2026"), and marks the English Express Entry draw name as English. The budget question names
  its fiscal year, taken from the day the call was recorded, instead of a year typed into the
  build, which would have stopped it once the capture aged.
- Website, home page: the provinces-and-cities ring listed "Transit schedules" twelve times,
  "BC Transit real-time", "Data Kingston", "Nanaimo GIS" and five conservation authorities as
  if they were cities, and dropped Niagara Falls into Niagara. It now lists real place names,
  once each, comparing whole names.
- Website, French pages: chart axes cut month names to four letters ("avri.", "octo.",
  "nove.", "mars.") or three ("jui" for juin and juillet). They now use the standard
  abbreviations (janv., févr., mars, avr., mai, juin, juill., août, sept., oct., nov., déc.).
- Website, Toronto page: the trimmed-response comments read "+3 autre" in French where the
  English says "3 more"; they now agree in number ("autres").
