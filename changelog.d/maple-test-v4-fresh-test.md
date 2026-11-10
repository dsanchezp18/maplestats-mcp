### Added

- Maple Test v4 has a fresh held-out test set: 25 questions written and keyed on
  2026-11-09 from the publishers' own APIs (`build_key_v4_test.py`, with `--check`), before
  any server answered them, stratified like the set they replace and reviewed by an
  independent agent. The first test set (in-sample for MapleStats) moved to dev, as the
  rotation rule says. The grader reads a comparison's call from an optional regex.
