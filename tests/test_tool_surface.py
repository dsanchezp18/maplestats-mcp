"""No breaking change to the tool surface goes without a CHANGELOG note.

Tools were removed and reshaped between releases (0.4.0 dropped the
statcan_census_tables_* and statcan_census_profile_2016_* tools) with
nothing to flag it. scripts/check_tool_surface.py compares
tool_catalogue.json with its version at the merge base of HEAD and
origin/main; this test fails while a breaking change's tool is missing from
the changelog.d/ fragments and CHANGELOG.md's Unreleased section. It skips where there is no git history
to compare with (an sdist, a shallow clone without origin/main), except
under TOOL_SURFACE_REQUIRED=1, which CI sets.
"""

from __future__ import annotations

import copy
import importlib.util
import os
import sys
from pathlib import Path

import pytest

from maplestats_mcp.catalogue import CATALOGUE_PATH

ROOT = Path(__file__).resolve().parents[1]


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "check_tool_surface", ROOT / "scripts" / "check_tool_surface.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolve their module through sys.modules while executing.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


surface = _load_script()


def test_breaking_changes_since_main_are_in_the_changelog():
    ref = os.environ.get("TOOL_SURFACE_BASE", surface.DEFAULT_BASE)
    old, base = surface.base_catalogue(ref)
    if old is None:
        # CI sets TOOL_SURFACE_REQUIRED, so a lost fetch-depth cannot turn the check off.
        if os.environ.get("TOOL_SURFACE_REQUIRED") == "1":
            pytest.fail(f"cannot compare the tool surface: {base}", pytrace=False)
        pytest.skip(f"cannot compare the tool surface: {base}")
    new = surface.surface(surface.read_catalogue())
    changes = surface.diff_surfaces(surface.surface(old), new)
    notes = surface.pending_notes(surface.CHANGELOG.read_text(encoding="utf-8"))
    missing = surface.unacknowledged(changes, notes)
    if missing:
        pytest.fail(surface.format_changes(changes, missing, base), pytrace=False)


def test_the_script_reads_the_servers_catalogue():
    assert ROOT / surface.CATALOGUE == CATALOGUE_PATH


def test_surface_keeps_the_contract_and_drops_descriptions():
    catalogue = {
        "format": 1,
        "modules": {
            "demo": {
                "files": ["tools.py"],
                "tools": [
                    {
                        "module": "demo.tools",
                        "name": "demo_get",
                        "title": "Demo get",
                        "description": "Docstring.",
                        "parameters": {
                            "type": "object",
                            "properties": {"year": {"type": "integer", "description": "Year."}},
                        },
                        "output_schema": {"type": "object", "title": "DemoResult"},
                        "annotations": {"readOnlyHint": True},
                    }
                ],
            }
        },
    }
    assert surface.surface(catalogue) == {
        "demo_get": {
            "title": "Demo get",
            "input_schema": {"type": "object", "properties": {"year": {"type": "integer"}}},
            "output_schema": {"type": "object"},
            "annotations": {"readOnlyHint": True},
        }
    }


def test_missing_base_ref_is_a_reason_not_an_error():
    old, reason = surface.base_catalogue("refs/heads/no-such-branch-for-this-test")
    assert old is None
    assert "no merge base" in reason


# A small surface in the shape surface() returns, for the classification tests below.
_BASE = {
    "demo_get": {
        "title": "Demo get",
        "annotations": {"readOnlyHint": True},
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "table": {"type": "string"},
                "year": {"anyOf": [{"type": "integer"}, {"type": "null"}], "default": None},
                "lang": {"type": "string", "enum": ["en", "fr"], "default": "en"},
            },
            "required": ["table"],
        },
        "output_schema": {
            "$defs": {
                "Row": {
                    "type": "object",
                    "properties": {"ref_date": {"type": "string"}, "value": {"type": "number"}},
                    "required": ["ref_date", "value"],
                }
            },
            "type": "object",
            "properties": {"rows": {"type": "array", "items": {"$ref": "#/$defs/Row"}}},
            "required": ["rows"],
        },
    }
}


def _changes(edit) -> list[tuple[str, str]]:
    new = copy.deepcopy(_BASE)
    edit(new["demo_get"])
    return [(change.kind, change.detail) for change in surface.diff_surfaces(_BASE, new)]


def test_identical_surfaces_have_no_changes():
    assert surface.diff_surfaces(_BASE, copy.deepcopy(_BASE)) == []


def test_removed_and_added_tools():
    renamed = {"demo_fetch": _BASE["demo_get"]}
    changes = [(c.kind, c.tool, c.detail) for c in surface.diff_surfaces(_BASE, renamed)]
    assert changes == [
        ("additive", "demo_fetch", "tool added"),
        ("breaking", "demo_get", "tool removed"),
    ]


def test_removed_parameter_is_breaking():
    def edit(tool):
        del tool["input_schema"]["properties"]["year"]

    assert _changes(edit) == [("breaking", "parameter `year`: removed")]


def test_renamed_parameter_is_breaking():
    def edit(tool):
        props = tool["input_schema"]["properties"]
        props["ref_year"] = props.pop("year")

    assert _changes(edit) == [("breaking", "parameter `year`: renamed to `ref_year`")]


def test_narrowed_type_is_breaking():
    def edit(tool):
        tool["input_schema"]["properties"]["year"] = {"type": "integer", "default": None}

    assert _changes(edit) == [
        ("breaking", "parameter `year`: type narrowed from integer | null to integer")
    ]


def test_removed_enum_value_is_breaking_and_added_one_additive():
    def edit(tool):
        tool["input_schema"]["properties"]["lang"]["enum"] = ["en", "es"]

    assert _changes(edit) == [
        ("breaking", 'parameter `lang`: values removed: "fr"'),
        ("additive", 'parameter `lang`: values added: "es"'),
    ]


def test_required_parameter_added_is_breaking_optional_one_additive():
    def edit(tool):
        schema = tool["input_schema"]
        schema["properties"]["geo"] = {"type": "string"}
        schema["properties"]["limit"] = {"type": "integer", "default": 100}
        schema["required"] = ["table", "geo"]

    assert _changes(edit) == [
        ("breaking", "parameter `geo`: added as required"),
        ("additive", "parameter `limit`: added"),
    ]


def test_parameter_becoming_required_is_breaking():
    def edit(tool):
        tool["input_schema"]["required"] = ["table", "year"]

    assert _changes(edit) == [("breaking", "parameter `year`: now required")]


def test_widened_input_type_is_additive():
    def edit(tool):
        tool["input_schema"]["properties"]["year"]["anyOf"][0] = {"type": "number"}

    assert _changes(edit) == [
        ("additive", "parameter `year`: type widened from integer | null to null | number")
    ]


def test_removed_output_field_is_breaking_added_one_additive():
    def edit(tool):
        row = tool["output_schema"]["$defs"]["Row"]
        del row["properties"]["value"]
        row["properties"]["status"] = {"type": "string"}
        row["required"] = ["ref_date"]

    assert _changes(edit) == [
        ("breaking", "output field `rows[].value`: removed"),
        ("additive", "output field `rows[].status`: added"),
    ]


def test_nullable_output_field_is_breaking():
    def edit(tool):
        row = tool["output_schema"]["$defs"]["Row"]
        row["properties"]["value"] = {"anyOf": [{"type": "number"}, {"type": "null"}]}

    assert _changes(edit) == [
        ("breaking", "output field `rows[].value`: type widened from number to null | number")
    ]


def test_title_annotation_and_default_changes_are_other():
    def edit(tool):
        tool["title"] = "Demo fetch"
        tool["annotations"]["readOnlyHint"] = False
        tool["input_schema"]["properties"]["lang"]["default"] = "fr"

    assert _changes(edit) == [
        ("other", 'title changed from "Demo get" to "Demo fetch"'),
        ("other", "annotation readOnlyHint changed from true to false"),
        ("other", 'parameter `lang`: default changed from "en" to "fr"'),
    ]


def test_unrecognised_difference_is_still_reported():
    def edit(tool):
        tool["input_schema"]["properties"]["table"]["uniqueItems"] = True

    assert _changes(edit) == [
        ("other", "parameter `table`: schema changed in a way this check does not name")
    ]


def test_stripping_keeps_property_and_default_values_named_like_notes():
    schema = {
        "title": "Args",
        "description": "dropped",
        "properties": {
            "title": {"type": "string", "description": "dropped", "default": {"title": "kept"}},
        },
    }
    assert surface.strip_notes(schema) == {
        "properties": {"title": {"type": "string", "default": {"title": "kept"}}}
    }


def test_unreleased_notes_stop_at_the_next_release():
    changelog = (
        "# Changelog\n\n## [Unreleased]\n\n### Removed\n\n- `demo_get`: use `demo_fetch`.\n\n"
        "## [0.4.1] - 2026-10-20\n\n- `old_tool` removed.\n"
    )
    notes = surface.unreleased_notes(changelog)
    assert "demo_get" in notes and "old_tool" not in notes
    assert surface.unreleased_notes("# Changelog\n") == ""


def test_pending_notes_read_the_fragments_too(tmp_path):
    (tmp_path / "drop-demo-get.md").write_text("### Removed\n\n- `demo_get`: use `demo_fetch`.\n")
    (tmp_path / "README.md").write_text("How to write a fragment about `readme_tool`.\n")
    changelog = "# Changelog\n\n## [Unreleased]\n\n### Fixed\n\n- `demo_list` pages.\n"
    notes = surface.pending_notes(changelog, tmp_path)
    assert "demo_get" in notes and "demo_list" in notes and "readme_tool" not in notes
    assert surface.pending_notes(changelog, tmp_path / "none") == surface.unreleased_notes(
        changelog
    )


def test_a_breaking_change_counts_as_noted_when_the_tool_or_its_family_is_named():
    notes = "- Removed `statcan_census_tables_*`; `demo_get` takes `ref_year` now."
    assert surface.acknowledged("demo_get", notes)
    assert surface.acknowledged("statcan_census_tables_list", notes)
    # A longer tool name that starts with a noted one is a different tool.
    assert not surface.acknowledged("demo_get_all", notes)
    assert not surface.acknowledged("demo", notes)


def test_only_unnoted_breaking_changes_fail():
    def edit(tool):
        del tool["input_schema"]["properties"]["year"]
        tool["input_schema"]["properties"]["limit"] = {"type": "integer", "default": 100}

    new = copy.deepcopy(_BASE)
    edit(new["demo_get"])
    changes = surface.diff_surfaces(_BASE, new)
    missing = surface.unacknowledged(changes, "Nothing about it.")
    assert [(c.kind, c.detail) for c in missing] == [("breaking", "parameter `year`: removed")]
    assert surface.unacknowledged(changes, "- `demo_get` drops `year`.") == []
    summary = surface.format_changes(changes, missing, "0123456789abcdef")
    breaking, additive = summary.split("Additive changes")
    assert "demo_get: parameter `year`: removed  [not in CHANGELOG]" in breaking
    assert "demo_get: parameter `limit`: added" in additive
    assert "changelog.d/" in summary and "0123456789ab" in summary
