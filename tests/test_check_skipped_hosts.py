"""The weekly smoke run fails loudly when one upstream host took many scripts down.

StatCan's www150 host answered every automated client with a Cloudflare challenge on
2026-11-17; every script that reads it skipped (exit 75, a warning), the run stayed green and
nobody was told. A skipped script now names the host behind its outage, and
scripts/check_skipped_hosts.py counts them per host. One source that is down must still never
turn the run red.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import _run_smoke  # pyright: ignore[reportMissingImports]
import _smoke_common  # pyright: ignore[reportMissingImports]
import check_skipped_hosts  # pyright: ignore[reportMissingImports]
from _smoke_common import (  # pyright: ignore[reportMissingImports]
    SKIPPED_EXIT,
    failing_hosts,
    report_skipped_hosts,
    skip_outage,
    skip_reloading,
)

from maplestats_mcp.shared.breaker import BREAKER, one_call
from maplestats_mcp.shared.errors import UpstreamUnavailable

WWW150 = "www150.statcan.gc.ca"


@pytest.fixture(autouse=True)
def _fresh_skips(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_smoke_common, "_skipped", [])
    monkeypatch.setattr(_smoke_common, "_skipped_hosts", set())


# 1. Where a skipped script's host comes from ----


def _outage(url: str) -> UpstreamUnavailable:
    """What a shared client raises when a request times out: the typed error from the httpx one."""
    timeout = httpx.ReadTimeout("slow", request=httpx.Request("GET", url))
    try:
        raise UpstreamUnavailable("the source is slow") from timeout
    except UpstreamUnavailable as error:
        return error


def test_the_host_comes_from_the_httpx_error_that_caused_the_outage():
    request = httpx.Request("GET", f"https://{WWW150}/t1/cimt/rest/getPeriods")
    assert failing_hosts(httpx.ConnectTimeout("timed out", request=request)) == [WWW150]
    response = httpx.Response(503, request=request)
    status = httpx.HTTPStatusError("503", request=request, response=response)
    try:
        raise UpstreamUnavailable("the portal is down") from status
    except UpstreamUnavailable as wrapped:
        assert failing_hosts(wrapped) == [WWW150]


def test_a_typed_error_that_names_its_host_gives_it():
    error = UpstreamUnavailable("challenged")
    error.host = "www12.statcan.gc.ca"  # type: ignore[attr-defined]
    assert failing_hosts(error) == ["www12.statcan.gc.ca"]


def test_without_either_the_breaker_says_which_hosts_failed():
    with one_call():
        BREAKER.record_failure(WWW150, "cloudflare")
    with one_call():
        BREAKER.record_failure("geo.statcan.gc.ca", "timeout")
    assert failing_hosts(UpstreamUnavailable("down")) == ["geo.statcan.gc.ca", WWW150]
    BREAKER.reset()
    assert failing_hosts(UpstreamUnavailable("down")) == []


def test_the_breakers_path_groups_come_back_as_one_host():
    # An error with no request (every CircuitOpen) falls back to the breaker's keys, which
    # are "host/group" for StatCan's www150. check_skipped_hosts counts scripts per host, so
    # a whole-host outage has to read as one host, not as one per path group.
    for key in (f"{WWW150}/wds", f"{WWW150}/sdmx", f"{WWW150}/daily", "www12.statcan.gc.ca/census"):
        with one_call():
            BREAKER.record_failure(key, "timeout")
    with one_call():
        BREAKER.record_failure("geo.statcan.gc.ca", "timeout")
    assert failing_hosts(UpstreamUnavailable("down")) == [
        "geo.statcan.gc.ca",
        "www12.statcan.gc.ca",
        WWW150,
    ]


def test_a_skip_remembers_its_hosts_and_a_reload_names_none(capsys):
    skip_outage("StatCan", _outage(f"https://{WWW150}/x"))
    skip_reloading("open.canada.ca", "grants")
    report_skipped_hosts("smoke_test_wds")
    out = capsys.readouterr().out
    assert out.splitlines()[-1] == f"SKIPHOST {WWW150} smoke_test_wds"
    assert out.count("SKIPHOST") == 1


# 2. The runner prints them for a skipped run, and only for one ----


def _script(folder: Path, name: str, body: str) -> None:
    (folder / f"{name}.py").write_text(
        "import httpx\nfrom _smoke_common import skip_outage, verdict\n" + body,
        encoding="utf-8",
    )


@pytest.fixture
def scripts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(_run_smoke, "HERE", tmp_path)
    return tmp_path


def test_a_script_cut_short_by_an_outage_names_its_host(scripts, capsys):
    _script(
        scripts,
        "smoke_test_one",
        f'request = httpx.Request("GET", "https://{WWW150}/t1/cimt/rest/getPeriods")\n'
        'raise httpx.ConnectTimeout("timed out", request=request)\n',
    )
    assert _run_smoke.main("smoke_test_one") == SKIPPED_EXIT
    assert f"SKIPHOST {WWW150} smoke_test_one" in capsys.readouterr().out


def test_a_script_that_skipped_a_check_and_exits_75_names_its_host(scripts, capsys):
    _script(
        scripts,
        "smoke_test_two",
        f'request = httpx.Request("GET", "https://{WWW150}/n1/rss/dai-quo/0-eng.atom")\n'
        'skip_outage("The Daily", httpx.ReadTimeout("slow", request=request))\n'
        'raise SystemExit(verdict("DAILY", True))\n',
    )
    assert _run_smoke.main("smoke_test_two") == SKIPPED_EXIT
    out = capsys.readouterr().out
    assert f"SKIPHOST {WWW150} smoke_test_two" in out
    assert "SKIPPED" in out


def test_a_passing_script_prints_no_host(scripts, capsys):
    _script(scripts, "smoke_test_three", "pass\n")
    assert _run_smoke.main("smoke_test_three") == 0
    assert "SKIPHOST" not in capsys.readouterr().out


def test_a_failure_is_still_a_failure_and_names_no_host(scripts, capsys):
    _script(scripts, "smoke_test_four", 'raise SystemExit(verdict("X", False))\n')
    assert _run_smoke.main("smoke_test_four") == 1
    assert "SKIPHOST" not in capsys.readouterr().out


# 3. What the weekly job decides ----


def _skips(folder: Path, **by_script: list[str]) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    for script, hosts in by_script.items():
        (folder / f"{script}.txt").write_text("\n".join(hosts) + "\n", encoding="utf-8")
    return folder


def test_skip_files_are_read_per_host(tmp_path):
    folder = _skips(
        tmp_path / "skipped",
        smoke_test_a=[WWW150],
        smoke_test_b=[WWW150, "geo.statcan.gc.ca"],
        smoke_test_c=[],
    )
    assert check_skipped_hosts.read_skips(folder) == {
        "geo.statcan.gc.ca": ["smoke_test_b"],
        WWW150: ["smoke_test_a", "smoke_test_b"],
    }
    assert check_skipped_hosts.read_skips(tmp_path / "nothing here") == {}


def test_more_than_three_scripts_for_one_host_is_a_finding():
    three = {WWW150: ["a", "b", "c"]}
    four = {WWW150: ["a", "b", "c", "d"]}
    assert check_skipped_hosts.findings(three, set()) == {}
    found = check_skipped_hosts.findings(four, set())
    assert list(found) == [WWW150] and "4 scripts skipped" in found[WWW150][0]
    assert check_skipped_hosts.findings(four, set(), max_scripts=5) == {}


def test_the_same_host_two_runs_in_a_row_is_a_finding():
    found = check_skipped_hosts.findings({WWW150: ["smoke_test_cimt"]}, {WWW150})
    assert found == {WWW150: ["also skipped in the previous run"]}
    # Another host last time says nothing about this one.
    assert check_skipped_hosts.findings({WWW150: ["a"]}, {"geo.statcan.gc.ca"}) == {}


def test_one_down_source_does_not_fail_the_run(tmp_path, capsys):
    """A single script skipped for a single host, with nothing the week before."""
    folder = _skips(tmp_path / "skipped", smoke_test_ckan=["open.canada.ca"])
    out = tmp_path / "report"
    code = check_skipped_hosts.main(["--skips", str(folder), "--out", str(out)])
    assert code == 0
    assert "No host crossed the line" in capsys.readouterr().out
    assert json.loads((out / "skipped-hosts.json").read_text()) == {
        "open.canada.ca": ["smoke_test_ckan"]
    }
    # No skip at all is fine too, with or without the folder.
    assert check_skipped_hosts.main(["--skips", str(tmp_path / "none"), "--out", str(out)]) == 0


def test_a_host_that_took_many_scripts_down_fails_the_run_and_is_named(tmp_path, capsys):
    scripts = [f"smoke_test_{name}" for name in ("wds", "sdmx", "cimt", "daily", "reference")]
    folder = _skips(tmp_path / "skipped", **{s: [WWW150] for s in scripts})
    out = tmp_path / "report"
    code = check_skipped_hosts.main(["--skips", str(folder), "--out", str(out)])
    assert code == 1
    report = (out / "skip-report.md").read_text(encoding="utf-8")
    assert f"`{WWW150}`: 5 scripts skipped for it (more than 3)" in report
    assert all(f"`{script}`" in report for script in scripts)
    assert capsys.readouterr().out == report


def test_a_repeat_is_read_from_the_previous_runs_file(tmp_path):
    previous = tmp_path / "previous.json"
    previous.write_text(json.dumps({WWW150: ["smoke_test_cimt"]}), encoding="utf-8")
    folder = _skips(tmp_path / "skipped", smoke_test_cimt=[WWW150])
    out = tmp_path / "report"
    args = ["--skips", str(folder), "--out", str(out), "--previous", str(previous)]
    assert check_skipped_hosts.main(args) == 1
    assert "also skipped in the previous run" in (out / "skip-report.md").read_text()
    # A missing or unreadable previous file is no previous run.
    previous.write_text("not json", encoding="utf-8")
    assert check_skipped_hosts.main(args) == 0
    previous.unlink()
    assert check_skipped_hosts.main(args) == 0


def test_the_workflow_wires_the_job_and_the_alert():
    workflow = (Path(__file__).resolve().parent.parent / ".github/workflows/smoke.yml").read_text(
        encoding="utf-8"
    )
    assert "scripts/check_skipped_hosts.py" in workflow
    assert "needs: [smoke, answer-keys, skipped-hosts]" in workflow
    assert "needs.skipped-hosts.result == 'failure'" in workflow
    assert "smoke-skips-${{ matrix.script }}" in workflow
    assert 'grep -E "^SKIPHOST "' in workflow
