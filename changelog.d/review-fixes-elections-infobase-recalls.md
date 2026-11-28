### Fixed

- `elections_results_get_table`: the `province` filter looked for the text inside the
  bilingual province name, so "AB" returned Newfoundland and Labrador, "ON" returned
  Ontario and Yukon, "NT" returned Ontario, and "NL" and "YT" returned an empty
  success. It now takes a province code (AB, ON, NL), an SGC code (48, 35) or the
  English or French name, as `elections_results_get_historical` already did.
- `elections_results_get_table`: on the `candidates` and `district_results` tables
  the `party` filter searched the candidate's name together with the party, so
  "Green" also returned candidates surnamed Green, Greene or Greenwood. It now reads
  the party part of the cell. A party with a single candidate in the whole table
  cannot be told apart from that candidate's name, so for it the filter still
  searches the whole cell.
- `elections_provincial_get_results`, `elections_provincial_get_voting_areas`: the
  `party` filter found one party code inside another, so "SP" also returned the
  Saskatchewan Progress Party ("SPP"), "PC" also returned Manitoba's "CPC-M", and
  Manitoba's "lib" (the Liberals' code) also returned the Libertarian Party, whose
  name contains it. Text that is the code of any party in the election now names only
  the parties with that code (Quebec's dotted codes still match one abbreviation at a
  time: "CAQ" for "C.A.Q.-E.F.L."); any other text is still a piece of a party's name.
  A plain code with a hyphen is no longer split, so "M" and "CPC" no longer find
  "CPC-M" (use "CPC-M" or "communist").
- `elections_provincial_get_results`: in the Saskatchewan 2011 workbook two candidates
  with one party code in the same constituency (two independents, say) were merged
  into one row carrying both candidates' votes and one of the names. Each candidate
  now keeps their own votes.
- `gc_infobase_query`, `gc_infobase_list_files`: `organization` and `query` now ignore
  accents, so "Sante Canada" finds "Santé Canada" instead of answering with no
  matching rows.
- `recalls_search`: an English plural was cut to a stem its singular does not share
  ("batteries" to "batterie", "candies" to "candie", "boxes" to "boxe"), so the plural
  missed notices that say "battery", "candy" or "box". The singular and the plural
  now find each other for -ies and -y words and for -es plurals of -ss, -x, -sh, -zz,
  -tch, -nch, -rch, -o and "lens" words ("boxes", "glasses", "watches", "tomatoes",
  "lenses"). Singulars in -se and -che ("nurses", "houses", "aches") are not cut
  further, so they do not find "nursing", "household" or "spinach".
- `elections_financial_returns_search_candidates`: an entry of the portal's candidate
  list that is not written "Last, First / Party / Electoral District" was left out
  with no word of it, though `total_found` still counted it. The result's
  `provenance.coverage` now gives how many were left out and the first three, with
  their client ids and their text (each cut to about 100 characters), and `elections_financial_returns_get_financial_return_part` no
  longer answers "did not run in election" for such a client id.
