# ============================================================
# Tests for the chat demo's usage counts
# Author: Daniel Sanchez
# Purpose: Check the counters, the saved file and what they refuse to keep
# Inputs:  none
# Outputs: pass/fail
# ============================================================

import usage


def test_counts_survive_a_restart(tmp_path):
    path = tmp_path / "stats" / "chat.json"
    first = usage.ChatStats(path)
    first.outcome("answered")
    first.tokens("input", 500)
    first.tool_call("wds_search_cubes", ok=True)
    assert first.save()
    second = usage.ChatStats(path)
    snap = second.snapshot()
    assert snap["persisted"] is True
    assert snap["counting_since"] == first.since.isoformat()
    assert snap["outcomes"] == {"answered": 1}
    assert snap["tokens"] == {"input": 500}
    assert snap["tools"] == {"wds_search_cubes": 1}
    assert sum(day["outcomes"]["answered"] for day in snap["by_day"].values()) == 1


def test_two_processes_add_up_and_a_second_save_adds_nothing(tmp_path):
    path = tmp_path / "chat.json"
    old = usage.ChatStats(path)
    old.outcome("answered")
    old.save()
    new = usage.ChatStats(path)
    old.outcome("answered")
    new.outcome("failed")
    old.save()
    new.save()
    new.save()
    assert usage.ChatStats(path).snapshot()["outcomes"] == {"answered": 2, "failed": 1}


def test_a_bad_file_is_moved_aside(tmp_path):
    path = tmp_path / "chat.json"
    path.write_text("{not json", encoding="utf-8")
    stats = usage.ChatStats(path)
    assert stats.snapshot()["questions"] == 0
    assert (tmp_path / "chat.json.bad").exists()
    stats.outcome("answered")
    assert stats.save()


def test_a_failed_save_keeps_the_counts(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("", encoding="utf-8")
    stats = usage.ChatStats(blocker / "chat.json")
    stats.outcome("answered")
    assert not stats.save()
    blocker.unlink()
    assert stats.save()
    assert usage.ChatStats(blocker / "chat.json").snapshot()["outcomes"] == {
        "answered": 1
    }


def test_unknown_values_never_become_keys():
    stats = usage.ChatStats()
    stats.outcome("my question text")
    stats.tokens("my question text", 5)
    stats.model_call("Tell me the API key")
    stats.tool_call("Robert'); DROP TABLE", ok=True)
    stats.turn(500)
    snap = stats.snapshot()
    assert snap["outcomes"] == {"failed": 1}
    assert snap["tokens"] == {}
    assert snap["stop_reasons"] == {"other": 1}
    assert snap["tools"] == {"other": 1}
    assert snap["turns"] == {"9+": 1}


def test_tool_names_are_capped():
    stats = usage.ChatStats()
    for n in range(usage.MAX_TOOL_NAMES + 20):
        stats.tool_call(f"tool_{n}", ok=True)
    tools = stats.snapshot()["tools"]
    assert len(tools) == usage.MAX_TOOL_NAMES + 1
    assert tools["other"] == 20


def test_without_a_file_nothing_is_written(tmp_path):
    stats = usage.ChatStats()
    stats.outcome("answered")
    assert not stats.save()
    assert list(tmp_path.iterdir()) == []


def test_the_image_copies_every_module():
    # The Dockerfile names its files; a module left out crashes the container at
    # startup (usage.py was nearly shipped that way).
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    copied = " ".join(
        line
        for line in (root / "Dockerfile").read_text(encoding="utf-8").splitlines()
        if line.startswith("COPY ")
    ).split()
    modules = {p.name for p in root.glob("*.py")}
    assert modules <= set(copied), sorted(modules - set(copied))
