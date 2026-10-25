"""changelog.d/ fragments are well formed and assemble into CHANGELOG.md.

Each pull request adds a fragment instead of editing CHANGELOG.md's
Unreleased section, so parallel pull requests no longer conflict there;
scripts/build_changelog.py writes them into CHANGELOG.md at release time.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "build_changelog", ROOT / "scripts" / "build_changelog.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


changelog = _load_script()

CHANGELOG = """# Changelog

Intro.

## [Unreleased]

### Fixed

- `demo_list` pages again.

## [0.4.2] - 2026-10-24

### Added

- Older entry.
"""


def _fragment(folder: Path, name: str, text: str) -> None:
    (folder / name).write_text(text, encoding="utf-8")


def test_every_fragment_in_the_repository_is_well_formed():
    assert changelog.check_fragments() == []


def test_the_changelog_has_an_unreleased_heading_and_no_unreleased_edits():
    # Entries go in changelog.d/; an edit here is what made parallel pull requests conflict.
    text = changelog.CHANGELOG.read_text(encoding="utf-8")
    match = changelog._UNRELEASED.search(text)
    assert match, "CHANGELOG.md needs a '## [Unreleased]' heading"
    _, sections = changelog.parse_sections(match.group(1), "CHANGELOG.md")
    assert not sections, "add a changelog.d/<slug>.md fragment instead of editing Unreleased"


def test_a_release_merges_unreleased_and_fragments_in_section_order(tmp_path):
    _fragment(tmp_path, "b-breaker.md", "### Added\n\n- A breaker.\n  Two lines.\n")
    _fragment(tmp_path, "a-docs.md", "### Fixed\n\n- A link.\n\n### Added\n\n- A page.\n")
    _fragment(tmp_path, "README.md", "How to write one.\n")
    updated = changelog.write_release(CHANGELOG, "0.4.3", "2026-10-30", tmp_path)
    assert updated.startswith(
        "# Changelog\n\nIntro.\n\n## [Unreleased]\n\n## [0.4.3] - 2026-10-30\n"
    )
    release = updated.split("## [0.4.3] - 2026-10-30\n\n")[1].split("## [0.4.2]")[0]
    assert release == (
        "### Added\n\n- A page.\n- A breaker.\n  Two lines.\n\n"
        "### Fixed\n\n- `demo_list` pages again.\n- A link.\n\n"
    )
    assert updated.endswith("## [0.4.2] - 2026-10-24\n\n### Added\n\n- Older entry.\n")


def test_a_release_refuses_a_version_already_written_or_nothing_to_write(tmp_path):
    with pytest.raises(ValueError, match="already has a section"):
        changelog.write_release(CHANGELOG, "0.4.2", "2026-10-30", tmp_path)
    empty = CHANGELOG.replace("### Fixed\n\n- `demo_list` pages again.\n\n", "")
    with pytest.raises(ValueError, match="nothing to release"):
        changelog.write_release(empty, "0.4.3", "2026-10-30", tmp_path)


@pytest.mark.parametrize(
    ("name", "text", "problem"),
    [
        ("ok.md", "### Improved\n\n- Something.\n", "unknown section 'Improved'"),
        ("ok.md", "- No heading.\n", "no section heading"),
        ("ok.md", "Intro.\n\n### Added\n\n- One.\n", "text before the first section heading"),
        ("ok.md", "### Added\n\nA paragraph.\n", "entries start with '- '"),
        ("ok.md", "### Added\n\n### Fixed\n\n- One.\n", "section 'Added' has no entries"),
        ("ok.md", "\n", "no section heading"),
        ("Big_Name.md", "### Added\n\n- One.\n", "name it <slug>.md"),
    ],
)
def test_malformed_fragments_are_reported_by_file(tmp_path, name, text, problem):
    _fragment(tmp_path, name, text)
    problems = changelog.check_fragments(tmp_path)
    assert len(problems) == 1 and problem in problems[0] and name in problems[0], problems


def test_no_fragment_folder_means_nothing_pending(tmp_path):
    assert changelog.fragment_files(tmp_path / "none") == []
    assert changelog.check_fragments(tmp_path / "none") == []
