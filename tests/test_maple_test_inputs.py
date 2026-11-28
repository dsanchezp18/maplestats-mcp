"""Publication evidence must survive a revised key without rewriting old run files."""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from tests.maple_test import grade, inputs, run


@pytest.fixture
def recorded_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    key = {
        "built_at": "2026-11-01",
        "questions": [
            {
                "id": "Q-1",
                "question": "How many units?",
                "expected": {"count": 12},
                "eval_type": "numeric",
                "citations": [],
                "category": "quantity",
                "source": "statcan",
                "qtype": "figure",
                "split": "test",
                "in_sample_for": [],
            }
        ],
    }
    key_path = tmp_path / "key.json"
    key_path.write_text(json.dumps(key), encoding="utf-8")
    suite = replace(
        grade.SUITES["v4"],
        key=key_path,
        runs=tmp_path,
        overrides=tmp_path / "overrides.json",
        citation_cache=tmp_path / "citations.json",
        results=tmp_path / "results.json",
    )
    monkeypatch.setitem(grade.SUITES, "v4", suite)
    monkeypatch.setattr(inputs, "environment", lambda repo: {"python": "test"})

    def ask(arm, model, question, config, version="v1", *, system_prompt=None):
        sidecars = list(tmp_path.glob("*.manifest.json"))
        assert sidecars, "the key must be recorded before asking the first question"
        record = json.loads(sidecars[-1].read_text())
        assert system_prompt == record["system_prompt"]
        return run.Answer(
            question_id=question["id"],
            arm=arm,
            requested_model=model,
            model_ids=["resolved-model-id"],
            tools_available=[],
            started_at="2026-11-27T12:00:00+00:00",
            duration_s=1.0,
            tool_calls=[],
            is_error=False,
            response="There are 12 units.",
        )

    monkeypatch.setattr(run, "ask", ask)
    return run.run("no_tools", "m", run.REPO, None, "frozen-inputs", version="v4")


def _change_key(value: float = 99) -> None:
    path = grade.SUITES["v4"].key
    key = json.loads(path.read_text())
    key["questions"][0]["expected"]["count"] = value
    key["questions"][0]["split"] = "dev"
    path.write_text(json.dumps(key), encoding="utf-8")


def test_saved_key_keeps_original_score_and_split_after_working_key_changes(recorded_run: Path):
    original = recorded_run.read_bytes()
    _change_key()
    report = grade.grade_runs([recorded_run], "v4")
    row = report["answers"][0]
    assert (row["grade"]["outcome"], row["split"]) == ("correct", "test")
    assert report["questions"][0]["expected"] == {"count": 12}
    assert report["input_provenance"]["runs"][0]["key_source"] == "recorded manifest"
    assert recorded_run.read_bytes() == original
    assert (
        grade.grade_answer(grade.load_key("v4")[0], "There are 12 units.").outcome == "hallucinated"
    )


def test_v4_cli_judge_uses_recorded_key(recorded_run: Path, monkeypatch: pytest.MonkeyPatch):
    from tests.maple_test import __main__, judge, review

    _change_key()
    seen: list[dict[str, Any]] = []

    def judge_many(pairs, model, workers):
        values = list(pairs)
        seen.extend(q for q, _ in values)
        return [{"outcome": "correct", "confidence": 1.0, "reason": "test"} for _ in values]

    monkeypatch.setattr(judge, "judge_many", judge_many)
    monkeypatch.setattr(review, "QUEUE", recorded_run.parent / "queue.md")
    monkeypatch.setattr(__main__, "HERE", recorded_run.parent / "tests" / "maple_test")
    monkeypatch.setattr(
        sys, "argv", ["maple", "grade", "--version", "v4", "--judge", str(recorded_run)]
    )
    assert __main__.main() == 0
    assert seen[0]["expected"] == {"count": 12}
    assert seen[0]["split"] == "test"


@pytest.mark.parametrize("change", ["key", "prompt", "budget", "environment"])
def test_resume_refuses_changed_inputs_before_any_call(
    recorded_run: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
):
    original = recorded_run.read_bytes()
    if change == "key":
        _change_key()
    elif change == "prompt":
        monkeypatch.setitem(run.PROMPTS, "v4", run.PROMPTS["v4"] + " Different instructions.")
    elif change == "budget":
        monkeypatch.setattr(run, "MAX_TURNS", run.MAX_TURNS + 1)
    else:
        monkeypatch.setattr(inputs, "environment", lambda repo: {"python": "changed"})
    with pytest.raises(ValueError, match="Cannot resume with changed inputs"):
        run.run("no_tools", "m", run.REPO, None, "frozen-inputs", version="v4", resume=True)
    assert recorded_run.read_bytes() == original


@pytest.mark.parametrize(
    "option", ["MAPLE_STATCAN_FALLBACK", "MAPLE_QUERY_SERIES", "MAPLE_RESPONSE_MAX_BYTES"]
)
def test_interrupted_local_run_cannot_resume_with_changed_source_option(
    recorded_run: Path,
    monkeypatch: pytest.MonkeyPatch,
    option: str,
):
    key_path = grade.SUITES["v4"].key
    key = json.loads(key_path.read_text())
    key["questions"].append({**key["questions"][0], "id": "Q-2"})
    key_path.write_text(json.dumps(key))
    monkeypatch.setattr(inputs, "checkout", lambda path, scope=(): {"commit": "source-version"})
    monkeypatch.setenv(option, "200000" if option.endswith("BYTES") else "1")
    ask = run.ask
    calls: list[str] = []

    def interrupted(arm, model, question, config, version="v1", *, system_prompt=None):
        calls.append(question["id"])
        if question["id"] == "Q-2":
            raise RuntimeError("interrupted")
        return ask(arm, model, question, config, version, system_prompt=system_prompt)

    monkeypatch.setattr(run, "ask", interrupted)
    with pytest.raises(RuntimeError, match="interrupted"):
        run.run("maplestats", "m", run.REPO, None, "local-options", version="v4")
    path = next(recorded_run.parent.glob("*_local-options_m.jsonl"))
    original = path.read_bytes()
    monkeypatch.setenv(option, "10000" if option.endswith("BYTES") else "0")
    with pytest.raises(ValueError, match="Cannot resume with changed inputs.*execution"):
        run.run("maplestats", "m", run.REPO, None, "local-options", version="v4", resume=True)
    assert calls == ["Q-1", "Q-2"] and path.read_bytes() == original


def test_generated_environment_overrides_inherited_local_source_options(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("MAPLE_TRANSPORT", "http")
    monkeypatch.setenv("MAPLE_STATCAN_FALLBACK", "0")
    servers = {
        "local": {
            "command": "uv",
            "env": {"MAPLE_TRANSPORT": "stdio", "MAPLE_STATCAN_FALLBACK": "1", "TOKEN": "secret"},
        }
    }
    first = inputs.public_configuration(servers)
    options = first["local"]["source_options"]
    assert options["MAPLE_TRANSPORT"] == "stdio" and options["MAPLE_STATCAN_FALLBACK"] == "1"
    assert "TOKEN" not in options
    monkeypatch.setenv("MAPLE_TRANSPORT", "sse")
    monkeypatch.setenv("MAPLE_STATCAN_FALLBACK", "off")
    assert inputs.public_configuration(servers) == first
    remote = inputs.public_configuration(
        {"remote": {"type": "http", "url": "https://example.test/mcp"}}
    )
    assert remote["remote"]["source_options"] == {}


def test_changed_manifest_is_not_silently_trusted(recorded_run: Path):
    path = inputs.manifest_path(recorded_run)
    record = json.loads(path.read_text())
    record["key"]["questions"][0]["expected"]["count"] = 99
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="Invalid or mismatched run manifest"):
        grade.grade_runs([recorded_run], "v4")


def test_orphaned_manifest_is_preserved_with_clear_recovery(recorded_run: Path):
    recorded_run.unlink()
    path = inputs.manifest_path(recorded_run)
    original = path.read_bytes()
    with pytest.raises(ValueError, match="preserve it and start a new --label"):
        run.run("no_tools", "m", run.REPO, None, "frozen-inputs", version="v4")
    assert path.read_bytes() == original


@pytest.mark.parametrize("change", ["missing-sidecar", "wrong-digest", "duplicate", "unplanned"])
def test_answers_must_match_their_manifest(recorded_run: Path, change: str):
    rows = grade.load_runs([recorded_run])
    if change == "missing-sidecar":
        inputs.manifest_path(recorded_run).unlink()
    elif change == "wrong-digest":
        rows[0]["manifest_sha256"] = "other-inputs"
    elif change == "duplicate":
        rows.append(dict(rows[0]))
    else:
        rows[0]["question_id"] = "Q-not-planned"
    recorded_run.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    with pytest.raises(ValueError, match="recorded manifest is missing|does not match"):
        grade.grade_runs([recorded_run], "v4")


def test_legacy_grade_is_supported_with_explicit_warning_but_resume_is_refused(recorded_run: Path):
    rows = grade.load_runs([recorded_run])
    rows[0].pop("manifest_sha256")
    recorded_run.write_text(json.dumps(rows[0]) + "\n")
    inputs.manifest_path(recorded_run).unlink()
    with pytest.warns(RuntimeWarning, match="Legacy runs have no recorded inputs"):
        report = grade.grade_runs([recorded_run], "v4")
    assert report["answers"][0]["grade"]["outcome"] == "correct"
    assert "not reconstructed" in " ".join(report["input_provenance"]["notes"])
    with pytest.raises(ValueError, match="Cannot resume a legacy run"):
        run.run("no_tools", "m", run.REPO, None, "frozen-inputs", version="v4", resume=True)


def test_different_recorded_question_keys_cannot_be_pooled(recorded_run: Path):
    _change_key()
    other = run.run("no_tools", "m", run.REPO, None, "different-inputs", version="v4")
    with pytest.raises(ValueError, match="different answer keys"):
        grade.grade_runs([recorded_run, other], "v4")


def test_report_identifies_current_adjudication_inputs(recorded_run: Path):
    suite = grade.SUITES["v4"]
    suite.overrides.write_text("{}")
    suite.citation_cache.write_text("{}")
    provenance = grade.grade_runs([recorded_run], "v4")["input_provenance"]
    assert provenance["overrides_sha256"] == inputs.file_digest(suite.overrides)
    assert provenance["citation_cache_sha256"] == inputs.file_digest(suite.citation_cache)
    assert "current working files" in " ".join(provenance["notes"])


def test_manifest_configuration_omits_credentials():
    configuration = inputs.public_configuration(
        {
            "data": {
                "type": "http",
                "url": "https://user:password@example.test/mcp?api_key=secret#secret",
                "headers": {"Authorization": "Bearer secret"},
                "env": {"TOKEN": "secret"},
                "args": ["https://example.test/mcp?token=secret"],
            },
        }
    )
    text = json.dumps(configuration)
    assert "secret" not in text and "password" not in text and "user:" not in text
    assert configuration["data"]["url"] == "https://example.test/mcp"
