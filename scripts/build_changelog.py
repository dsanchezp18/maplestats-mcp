"""Assemble the changelog.d/ fragments into CHANGELOG.md at release time.

Each change adds one file, changelog.d/<slug>.md, instead of editing the
Unreleased section of CHANGELOG.md: two pull requests open at once used to
conflict there every time. A fragment holds one or more Keep a Changelog
sections (Added, Changed, Deprecated, Removed, Fixed, Security), each a
list of entries:

    ### Fixed

    - `wds_get_cube_metadata`: ...

tests/test_changelog.py checks every fragment on every pull request.
To release, after bumping the version:

    uv run python scripts/build_changelog.py --preview
    uv run python scripts/build_changelog.py --version 0.4.3 [--date 2026-10-30]

The second command writes the fragments, after anything still under
Unreleased, as the release's section below an empty Unreleased heading,
and deletes them. Within a section, entries keep the order of the fragment
file names. The date defaults to today in UTC.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHANGELOG = ROOT / "CHANGELOG.md"
FRAGMENTS = ROOT / "changelog.d"
SECTIONS = ("Added", "Changed", "Deprecated", "Removed", "Fixed", "Security")

# Slugs keep the folder listing readable and the file names portable.
_SLUG = re.compile(r"[a-z0-9][a-z0-9-]*\.md")
_UNRELEASED = re.compile(r"^## \[Unreleased\][^\n]*\n(.*?)(?=^## \[|\Z)", re.MULTILINE | re.DOTALL)


def fragment_files(folder: Path = FRAGMENTS) -> list[Path]:
    """The fragments, in file-name order; the folder's README is not one."""
    if not folder.is_dir():
        return []
    return sorted(path for path in folder.glob("*.md") if path.name != "README.md")


def parse_sections(text: str, where: str) -> tuple[str, dict[str, list[str]]]:
    """Text before the first `###` heading, and each section's entries.

    An entry is a `- ` line with the indented lines under it. Raises
    ValueError, naming `where`, for an unknown section, an empty one, or a
    line that belongs to no entry.
    """
    intro: list[str] = []
    sections: dict[str, list[str]] = {}
    current: list[str] | None = None
    for number, line in enumerate(text.splitlines(), start=1):
        heading = re.fullmatch(r"###\s+(.+?)\s*", line)
        if heading:
            name = heading.group(1)
            if name not in SECTIONS:
                raise ValueError(
                    f"{where}:{number}: unknown section {name!r}, use one of {SECTIONS}"
                )
            current = sections.setdefault(name, [])
        elif current is None:
            intro.append(line)
        elif line.startswith("- "):
            current.append(line)
        elif line.startswith("  ") and current:
            current[-1] += "\n" + line
        elif line.strip():
            raise ValueError(
                f"{where}:{number}: entries start with '- ', continuations with 2 spaces"
            )
    for name, entries in sections.items():
        if not entries:
            raise ValueError(f"{where}: section {name!r} has no entries")
    return "\n".join(intro).strip(), sections


def check_fragments(folder: Path = FRAGMENTS) -> list[str]:
    """Every problem in the fragments, one line each; empty when all are well formed."""
    problems = []
    for path in fragment_files(folder):
        if not _SLUG.fullmatch(path.name):
            problems.append(f"{path.name}: name it <slug>.md, lower case, digits and hyphens")
        try:
            intro, sections = parse_sections(path.read_text(encoding="utf-8"), path.name)
        except ValueError as error:
            problems.append(str(error))
            continue
        if not sections:
            problems.append(f"{path.name}: no section heading such as '### Added'")
        elif intro:
            problems.append(f"{path.name}: text before the first section heading")
    return problems


def release_section(changelog: str, folder: Path = FRAGMENTS) -> str:
    """The body of the next release: Unreleased's entries, then the fragments'."""
    match = _UNRELEASED.search(changelog)
    intro, merged = parse_sections(match.group(1) if match else "", "CHANGELOG.md Unreleased")
    for path in fragment_files(folder):
        _, sections = parse_sections(path.read_text(encoding="utf-8"), path.name)
        for name, entries in sections.items():
            merged.setdefault(name, []).extend(entries)
    parts = [intro] if intro else []
    for name in SECTIONS:
        if name in merged:
            parts += [f"### {name}", "\n".join(merged[name])]
    return "\n\n".join(parts)


def write_release(changelog: str, version: str, date: str, folder: Path = FRAGMENTS) -> str:
    """The changelog with the release's section under an empty Unreleased heading."""
    if f"## [{version}]" in changelog:
        raise ValueError(f"CHANGELOG.md already has a section for {version}")
    body = release_section(changelog, folder)
    if not body:
        raise ValueError("nothing to release: no fragments and an empty Unreleased section")
    match = _UNRELEASED.search(changelog)
    if match is None:
        raise ValueError("CHANGELOG.md has no '## [Unreleased]' heading")
    release = f"## [Unreleased]\n\n## [{version}] - {date}\n\n{body}\n\n"
    return changelog[: match.start()] + release + changelog[match.end() :]


def main() -> int:
    parser = argparse.ArgumentParser(description="Assemble changelog.d/ into CHANGELOG.md.")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true", help="only check the fragments")
    action.add_argument("--preview", action="store_true", help="print the next release's notes")
    action.add_argument("--version", help="write the release into CHANGELOG.md")
    parser.add_argument("--date", default=datetime.now(UTC).date().isoformat())
    args = parser.parse_args()
    problems = check_fragments()
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    changelog = CHANGELOG.read_text(encoding="utf-8")
    if args.check:
        print(f"{len(fragment_files())} fragments, all well formed.")
        return 0
    if args.preview:
        print(release_section(changelog) or "Nothing to release yet.")
        return 0
    try:
        updated = write_release(changelog, args.version, args.date)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1
    CHANGELOG.write_text(updated, encoding="utf-8", newline="\n")
    for path in fragment_files():
        path.unlink()
    print(f"Wrote {args.version} into CHANGELOG.md and deleted its fragments.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
