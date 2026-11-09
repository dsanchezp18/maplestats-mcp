### Added

- Maple Test v4: 47 questions kept from v1 to v3 (near-duplicates and questions every
  comparable server always got right or always got wrong dropped, by an item analysis of
  the hand-reviewed grades), split into a public dev set and a held-out test set with a
  rotation rule (`build_key_v4.py`). Answers end with a JSON block the grader reads first;
  an LLM judge, calibrated against the v1 to v3 hand reviews, sends only disputed or
  uncertain answers to a person (`grade --version v4 --judge`, `calibrate.py`). Runs take
  one pass plus extra passes on volatile questions, ask hosted arms' questions in parallel,
  run arms side by side (`run-many`), and can serve MapleStats' upstream HTTP from a frozen
  cassette (`--frozen`).
