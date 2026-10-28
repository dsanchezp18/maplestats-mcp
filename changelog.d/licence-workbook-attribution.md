### Changed

- `reproduce_workbook`: the Source sheet has a new "Changes made" row listing
  what cleaning changed (columns renamed, text trimmed, empty text left blank,
  text converted to numbers or dates, long integers kept as text), and its
  Attribution row now gives the notice the publisher's terms ask for. For
  Statistics Canada data it is the Open Licence's "Adapted from Statistics
  Canada, <product>, <date>. This does not constitute an endorsement by
  Statistics Canada of this product." once cleaning changed anything, and its
  "Source: Statistics Canada, <product>, <date>. Reproduced and distributed on
  an 'as is' basis with the permission of Statistics Canada." otherwise (in
  French with `lang="fr"`); the product is the table number and the title given.
  For the Bank of Canada and Creative Commons Attribution licences, which ask
  that changes be indicated, the attribution says changes were made. The
  tool results' own `provenance.licence` is unchanged.
