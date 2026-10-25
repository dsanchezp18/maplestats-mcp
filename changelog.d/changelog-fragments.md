### Changed

- Changelog entries are now one file per change in `changelog.d/` instead of edits to the
  Unreleased section of `CHANGELOG.md`, so pull requests open at the same time no longer
  conflict over it. `scripts/build_changelog.py --version X` writes them into `CHANGELOG.md`
  at release time, and `tests/test_changelog.py` checks each fragment. The tool-surface check
  (`scripts/check_tool_surface.py`) accepts a breaking change named in a fragment.
- CI runs the R and Julia reproduce tests in their own `r-julia` job, with the R library and
  Julia packages cached, instead of on the Python 3.12 leg. The slowest job went from 216 to
  370 s to 138 to 173 s on `main` (2026-10-23 to 2026-10-25), and a skip in that job fails it.
