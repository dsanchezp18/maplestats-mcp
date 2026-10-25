# Changelog fragments

Each change that belongs in [`CHANGELOG.md`](../CHANGELOG.md) adds one file
here, `changelog.d/<slug>.md` (lower case, digits and hyphens, named after the
change), instead of editing the Unreleased section. Two pull requests open at
the same time then never conflict over the changelog.

A fragment holds one or more [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
sections (`Added`, `Changed`, `Deprecated`, `Removed`, `Fixed`, `Security`),
each a list of entries written as they will read in the release notes:

```markdown
### Fixed

- `wds_get_cube_metadata`: what was wrong, what it does now, and since when.
  Continuation lines are indented by two spaces.
```

`tests/test_changelog.py` checks every fragment. At release time
`scripts/build_changelog.py` writes them into `CHANGELOG.md` and deletes them
(see "Releasing" in [`AGENTS.md`](../AGENTS.md)). This README is not a fragment.
