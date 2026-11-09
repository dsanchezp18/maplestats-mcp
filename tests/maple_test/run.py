"""Ask the Maple Test questions through one arm and record every answer.

Every arm gets the same model, system prompt and agent loop: headless Claude Code
(`claude -p`) with every built-in tool off, run in an empty folder so nothing in this
repository (the answer key included) is in reach. Only the data access changes:

- maplestats: this repository's server over stdio (`--server-dir` picks the checkout;
  `--frozen` serves its upstream HTTP from a cassette, see frozen_server.py)
- maplestats_hosted: the hosted MapleStats server, over HTTP
- mcp_statcan: the community mcp-statcan server's public endpoint
- pipeworx: Pipeworx's hosted StatCan and Bank of Canada servers, together
- arose26: arose26's statcan-mcp and bank-of-canada-mcp npm packages, together
- mcp_canada: ReyemTech's mcp-canada from PyPI (`uvx mcp-canada`)
- openmcp: opendatafyi's OpenMCP, from a local clone with its catalogue (`--alts`)
- candata_mcp: CanData's own server, from a local clone of their monorepo (`--alts`)
- statcan2: statcan2.ca's hosted server (an independent rebuild of every StatCan table)
- canada_data_agent: gcode33's canada-data-agent MCP server, from a local clone (`--alts`)
- opencanada: OpenCanadaPublicDataMCP's federal servers that match the questions (statcan,
  boc, census, ircc, immigration, dpd, eccc-weather, climate, hydrometric), from a local
  clone (`--alts`)
- no_tools: the model alone

The local-clone arms read `--alts` (or MAPLE_TEST_ALTS): a folder holding `openmcp/`
(cloned, `venv/` built, `catalog.duckdb` downloaded, per its README) and `candata/`
(the Canadian-Open-Data-Agentic-Platform repo, `uv sync` run) and
`gcode33_canada-data-agent/` (`uv sync` run; it caches StatCan responses in PostgreSQL,
so a database at its default DATABASE_URL needs the table from its
migrations/0002_http_cache.sql), and `opencanada/` (the OpenCanadaPublicDataMCP repo, each
of those servers with a `.venv` from `uv sync` plus `mcp[cli]<2`: their pyproject allows
mcp 2.x, which removed the FastMCP import they use). Keep it outside this
repository: it is third-party code.

`ENABLE_TOOL_SEARCH=false` keeps MCP tools loaded up front: with built-in tools off, the
deferred-tool search tool is gone too, and the MCP arms would otherwise see no tools.
This is the setup CanData used for its GTA benchmark (2026-10-22), so scores from the two
benchmarks are read the same way.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tests.maple_test.grade import SUITES, load_key

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
TIMEOUT_S = 600
MAX_TURNS = 25
# MAPLE_HOSTED_URL points both hosted arms at another deployment of the same code (the
# 2026-11-09 full-arm re-runs used a local server at the commit the hosted one ran).
HOSTED = os.environ.get("MAPLE_HOSTED_URL", "https://mcp.maplestats.danielstats.io/mcp")
ARMS = (
    "maplestats",
    "maplestats_hosted",
    "maplestats_full",
    "mcp_statcan",
    "pipeworx",
    "arose26",
    "mcp_canada",
    "openmcp",
    "candata_mcp",
    "statcan2",
    "canada_data_agent",
    "opencanada",
    "no_tools",
)

# Arms whose servers run elsewhere: several can run at once from one laptop. The others start
# a server on this machine (stdio), and two of those at once compete for its CPU and
# memory (OpenMCP took 3.3 GB per call), so `run-many` runs them one after another.
HOSTED_ARMS = frozenset({"maplestats_hosted", "mcp_statcan", "pipeworx", "statcan2", "no_tools"})
NOT_CONNECTED = "MCP tools were not available."
# Questions at once a hosted arm tolerates from one machine. Hosted MapleStats allows 120
# HTTP requests a minute per client (shared/security.py), and one answer makes a dozen or
# more: three at once got "Rate limit exceeded" on 16 of 64 answers (2026-11-09).
MAX_WORKERS = {"maplestats_hosted": 1, "maplestats_full": 1}
CONNECT_RETRIES = 2

OPENCANADA_SERVERS = (
    "statcan",
    "boc",
    "census",
    "ircc",
    "immigration",
    "dpd",
    "eccc-weather",
    "climate",
    "hydrometric",
)

PROMPTS = {
    "v1": """\
You answer questions about Canadian economic and social statistics. Today is {today}.

Use official sources: Statistics Canada and the Bank of Canada. With every figure, give \
the Statistics Canada table number (such as 14-10-0287-01) and vector (such as \
v2062815), or the Bank of Canada series, and the reference period.

If a figure does not exist or you cannot check it, say so instead of estimating. Keep \
the answer short.""",
    # v2 asks about publishers beyond StatCan and the Bank of Canada, so the prompt names
    # them; it is otherwise the v1 prompt, and every arm gets the same one.
    "v2": """\
You answer questions about Canadian economic, social and environmental data. Today is \
{today}.

Use official sources: Statistics Canada, the Bank of Canada, and other federal, \
provincial and municipal publishers. With every figure, give its source: for Statistics \
Canada the table number (such as 14-10-0287-01) and vector (such as v2062815), for the \
Bank of Canada the series, for any other publisher the dataset or page; and the \
reference period.

If a figure does not exist or you cannot check it, say so instead of estimating. Keep \
the answer short.""",
    # v3 asks about the data's documentation (units, revisions, definitions, codes, dataset
    # metadata on open-data portals), not only figures, so the prompt says so; it is
    # otherwise the v2 prompt, and every arm gets the same one.
    "v3": """\
You answer questions about Canadian data and its documentation: series metadata, survey \
methods, definitions, classifications, and open-data portal datasets. Today is {today}.

Use official sources: Statistics Canada, the Bank of Canada, CMHC, and federal, \
provincial and municipal publishers and their open-data portals. With every answer, give \
its source: for Statistics Canada the table, vector or survey record, for the Bank of \
Canada the series, for a portal the dataset and portal, for any other publisher the page.

If something is not published or you cannot check it, say so instead of guessing. Keep \
the answer short.""",
    # v4 mixes v1 to v3 questions, so the prompt covers figures, release dates and
    # documentation, and asks for a closing JSON block the grader reads first (README,
    # "Structured answers"). Every arm gets the same one.
    "v4": """\
You answer questions about Canadian data: figures, release dates, and the data's \
documentation (series metadata, survey methods, definitions, classifications, open-data \
portal datasets). Today is {today}.

Use official sources: Statistics Canada, the Bank of Canada, CMHC, other federal, \
provincial and municipal publishers and their open-data portals, and international \
bodies where the question names them. With every answer, give its source: for \
Statistics Canada the table number (such as 14-10-0287-01) and vector (such as \
v2062815), for the Bank of Canada the series, for a portal the dataset and portal, for \
any other publisher the dataset or page; and the reference period.

If something is not published or you cannot check it, say so instead of estimating. \
Keep the answer short.

End the answer with a fenced JSON block (```json ... ```) holding:
{{"values": [{{"name": "what it is", "value": <number or text>, "unit": "e.g. %, \
persons, thousands", "period": "reference period or date"}}],
 "sources": [{{"publisher": "...", "id": "table, vector, series or dataset id"}}],
 "not_published": <true if what was asked is not published or does not exist>,
 "abstain": <true if you could not check the answer>,
 "abstain_reason": "<why, or empty>"}}
Put every figure, date, code or fact you state in "values", numbers as plain numbers.""",
}


def _venv_python(venv: Path) -> Path:
    """A virtual environment's Python: bin/python, or Scripts/python.exe on Windows."""
    return venv / "Scripts" / "python.exe" if sys.platform == "win32" else venv / "bin" / "python"


def servers(
    arm: str, server_dir: Path, alts: Path | None = None, frozen: Path | None = None
) -> dict[str, Any]:
    if arm in ("openmcp", "candata_mcp", "canada_data_agent", "opencanada") and alts is None:
        raise SystemExit(f"--alts (or MAPLE_TEST_ALTS) is needed for the {arm} arm")
    if arm == "arose26":
        # Two sibling packages by the same author; a user covering both sources installs both.
        return {
            "statcan": {"command": "npx", "args": ["-y", "statcan-mcp"]},
            "bankofcanada": {"command": "npx", "args": ["-y", "bank-of-canada-mcp"]},
        }
    if arm == "mcp_canada":
        return {"mcpcanada": {"command": "uvx", "args": ["mcp-canada"]}}
    if arm == "openmcp":
        assert alts is not None
        home = alts / "openmcp"
        return {
            "openmcp": {
                "command": str(_venv_python(home / "venv")),
                "args": [str(home / "mcp_server.py")],
            }
        }
    if arm == "candata_mcp":
        assert alts is not None
        home = alts / "candata"
        # As CanData's own run_baseline.py starts it: the monorepo is not installed as a package.
        return {
            "candata": {
                "command": "uv",
                "args": ["run", "--directory", str(home), "python", "-m", "candata_mcp"],
                "env": {"PYTHONPATH": str(home / "packages" / "candata-mcp" / "src")},
            }
        }
    if arm == "canada_data_agent":
        assert alts is not None
        home = alts / "gcode33_canada-data-agent"
        return {
            "canada": {"command": "uv", "args": ["run", "--directory", str(home), "canada-mcp"]}
        }
    if arm == "opencanada":
        assert alts is not None
        home = alts / "opencanada" / "servers" / "federal"
        # The federal servers a user would install for these questions, not all 99: loading
        # every server's tools at once would only bury the relevant ones.
        names = OPENCANADA_SERVERS
        return {
            n.replace("-", "_"): {
                "command": str(_venv_python(home / n / ".venv")),
                "args": [str(home / n / "main.py")],
            }
            for n in names
        }
    if arm == "statcan2":
        return {"statcan2": {"type": "http", "url": "https://statcan2.ca/api/mcp"}}
    if arm == "maplestats" and frozen is not None:
        # Upstream HTTP from a cassette: recorded on a miss, or FROZEN_MODE=replay for none.
        return {
            "maplestats": {
                "command": "uv",
                "args": [
                    "run",
                    "--directory",
                    str(server_dir),
                    "python",
                    str(HERE / "frozen_server.py"),
                    "--cassette",
                    str(frozen.resolve()),
                    "--mode",
                    os.environ.get("FROZEN_MODE", "auto"),
                ],
                "env": {"MAPLE_TRANSPORT": "stdio"},
            }
        }
    if arm == "maplestats":
        return {
            "maplestats": {
                "command": "uv",
                "args": ["run", "--directory", str(server_dir), "maplestats-mcp"],
                "env": {"MAPLE_TRANSPORT": "stdio"},
            }
        }
    if arm == "maplestats_hosted":
        # The hosted server as users reach it (brief results, the default since #203).
        return {"maplestats": {"type": "http", "url": HOSTED}}
    if arm == "maplestats_full":
        # The same hosted server through a local relay that sets detail='full' on every
        # call_tool request (relay_full.py), so full results do not depend on the model.
        return {
            "maplestats": {
                "command": "uv",
                "args": [
                    "run",
                    "--directory",
                    str(REPO),
                    "python",
                    "-m",
                    "tests.maple_test.relay_full",
                    HOSTED,
                ],
                "env": {"MAPLE_RELAY_LOG": os.environ.get("MAPLE_RELAY_LOG", "")},
            }
        }
    if arm == "mcp_statcan":
        return {"statcan": {"type": "http", "url": "https://mcp-statcan.onrender.com/mcp"}}
    if arm == "pipeworx":
        # Pipeworx publishes StatCan and the Bank of Canada as two hosted servers; a
        # user covering both installs both, so the arm gets both.
        return {
            "statcan": {"type": "http", "url": "https://gateway.pipeworx.io/statcan/mcp"},
            "bankofcanada": {
                "type": "http",
                "url": "https://gateway.pipeworx.io/bank-of-canada/mcp",
            },
        }
    return {}


@dataclass
class Answer:
    question_id: str
    arm: str
    requested_model: str
    model_ids: list[str]
    tools_available: list[str]
    started_at: str
    duration_s: float
    tool_calls: list[str]
    is_error: bool
    response: str
    repeat: int = 0
    cost_usd: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    # Prompt caching: input_tokens counts only what was neither read from nor written to
    # the cache (14 on a typical answer), so the input a model read is all three summed.
    cache_read_tokens: int | None = None
    cache_creation_tokens: int | None = None


def ask(
    arm: str, model: str, question: dict[str, Any], config: Path | None, version: str = "v1"
) -> Answer:
    started = datetime.now(UTC)
    command = [
        "claude",
        "-p",
        "--model",
        model,
        "--system-prompt",
        PROMPTS[version].format(today=started.date().isoformat()),
        "--tools",
        "",
        "--strict-mcp-config",
        "--setting-sources",
        "",
        "--no-session-persistence",
        "--max-turns",
        str(MAX_TURNS),
        "--output-format",
        "stream-json",
        "--verbose",
    ]
    names = []
    if config is not None:
        names = list(json.loads(config.read_text())["mcpServers"])
        command += ["--mcp-config", str(config), "--allowedTools", *[f"mcp__{n}" for n in names]]
    # ignore_cleanup_errors: on Windows the folder can still be held by a child process (the
    # MCP server) when the answer is in; the error ended a run after 16 answers (2026-11-05).
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as empty:
        try:
            proc = subprocess.run(
                command,
                input=question["question"],
                capture_output=True,
                # The CLI writes UTF-8. Plain text=True decodes with the Windows code page:
                # "2–13 November" came back as "2â€“13", and a byte it cannot decode left
                # stdout None and ended a run after 10 answers (2026-11-05).
                encoding="utf-8",
                errors="replace",
                cwd=empty,
                # MCP_TIMEOUT (ms): how long the CLI waits for a server to start. OpenMCP
                # took 85 s to answer initialize on Windows (2026-11-05), and MapleStats
                # sometimes missed the default under load; both then answered with no
                # tools. Three minutes, for every arm alike.
                env={**os.environ, "ENABLE_TOOL_SEARCH": "false", "MCP_TIMEOUT": "180000"},
                timeout=TIMEOUT_S,
                check=False,
            )
        except subprocess.TimeoutExpired:
            # One stuck answer must not end a run of hundreds; it is recorded as an error.
            proc = subprocess.CompletedProcess(command, 124, "", f"timed out after {TIMEOUT_S}s")
    tools: list[str] = []
    calls: list[str] = []
    models: set[str] = set()
    result: dict[str, Any] = {}
    for line in proc.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "system" and event.get("subtype") == "init":
            tools = sorted(event.get("tools", []))
        elif event.get("type") == "assistant":
            models.add(event["message"].get("model", "unknown"))
            calls += [
                b["name"]
                for b in event["message"].get("content", [])
                if b.get("type") == "tool_use"
            ]
        elif event.get("type") == "result":
            result = event
    response = result.get("result") or proc.stderr.strip() or "no result"
    error = bool(result.get("is_error", True)) or proc.returncode != 0
    if names and not all(any(t.startswith(f"mcp__{n}__") for t in tools) for n in names):
        error, response = True, f"{NOT_CONNECTED} {response}"
    return Answer(
        question_id=question["id"],
        arm=arm,
        requested_model=model,
        model_ids=sorted(models),
        tools_available=tools,
        started_at=started.isoformat(timespec="seconds"),
        duration_s=round((datetime.now(UTC) - started).total_seconds(), 1),
        tool_calls=calls,
        is_error=error,
        response=response,
        cost_usd=result.get("total_cost_usd"),
        input_tokens=(result.get("usage") or {}).get("input_tokens"),
        output_tokens=(result.get("usage") or {}).get("output_tokens"),
        cache_read_tokens=(result.get("usage") or {}).get("cache_read_input_tokens"),
        cache_creation_tokens=(result.get("usage") or {}).get("cache_creation_input_tokens"),
    )


def jobs(
    questions: list[dict[str, Any]], repeat: int, extra_passes: int
) -> list[tuple[dict[str, Any], int]]:
    """(question, pass) in the order asked: whole passes, then the extra ones.

    `extra_passes` asks again only the questions the key marks `extra_passes` (v4: those
    whose outcome changed between passes in earlier runs), after the full passes.
    """
    out = [(q, r) for r in range(repeat) for q in questions]
    out += [
        (q, r)
        for r in range(repeat, repeat + extra_passes)
        for q in questions
        if q.get("extra_passes")
    ]
    return out


def run(
    arm: str,
    model: str,
    server_dir: Path,
    only: list[str] | None,
    label: str,
    alts: Path | None = None,
    version: str = "v1",
    repeat: int = 1,
    extra_passes: int = 0,
    split: str = "all",
    workers: int = 1,
    frozen: Path | None = None,
) -> Path:
    questions = [
        q
        for q in load_key(version)
        if (not only or q["id"] in only) and split in ("all", q.get("split", "all"))
    ]
    runs = SUITES[version].runs
    runs.mkdir(exist_ok=True)
    name = label or arm
    out = runs / f"{datetime.now(UTC).date().isoformat()}_{name}_{model}.jsonl"
    # A run is evidence: never overwrite one (a retry gets its own --label).
    if out.exists():
        raise SystemExit(f"{out.name} exists; pass --label to keep both runs")
    if alts is None and os.environ.get("MAPLE_TEST_ALTS"):
        alts = Path(os.environ["MAPLE_TEST_ALTS"])
    config_servers = servers(arm, server_dir, alts, frozen)
    if workers > MAX_WORKERS.get(arm, workers):
        print(f"{arm}: --workers {workers} lowered to {MAX_WORKERS[arm]}", file=sys.stderr)
        workers = MAX_WORKERS[arm]
    if workers > 1 and arm not in HOSTED_ARMS:
        # Each answer starts its own server: several at once compete for this machine and,
        # for MapleStats, for the publishers' rate limits.
        print(
            f"{arm} starts a local server per answer; --workers {workers} may slow it",
            file=sys.stderr,
        )
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        config = None
        if config_servers:
            config = Path(tmp) / "mcp.json"
            config.write_text(json.dumps({"mcpServers": config_servers}))
        lock = threading.Lock()
        with out.open("w", encoding="utf-8") as fh:

            def one(job: tuple[dict[str, Any], int]) -> None:
                q, r = job
                answer = ask(arm, model, q, config, version)
                # A server that did not connect is not an answer: ask again, up to
                # CONNECT_RETRIES times (the hosted server missed some starts with four
                # sessions at once, 2026-11-09). v2 re-asked these by hand.
                for _ in range(CONNECT_RETRIES):
                    if not answer.response.startswith(NOT_CONNECTED):
                        break
                    answer = ask(arm, model, q, config, version)
                answer.arm, answer.repeat = name, r
                with lock:
                    fh.write(json.dumps(asdict(answer), ensure_ascii=False) + "\n")
                    fh.flush()
                state = "ERROR" if answer.is_error else f"{len(answer.tool_calls)} calls"
                print(f"{q['id']}#{r} {name}: {state}, {answer.duration_s}s", file=sys.stderr)

            # Whole passes, not each question three times in a row: a source that is down
            # for a minute then costs one answer per pass, not three of one question.
            with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
                list(pool.map(one, jobs(questions, repeat, extra_passes)))
    return out


def run_many(arms: list[str], workers: int = 1, **kwargs: Any) -> list[Path]:
    """Several arms at once: every hosted arm in parallel, local-server arms in one lane.

    Hosted arms (HOSTED_ARMS) share nothing on this machine but the CLI, so they run side
    by side, each with `workers` questions at a time. Arms that start a server here run
    one after another in a lane of their own, beside the hosted ones.
    """
    hosted = [a for a in arms if a in HOSTED_ARMS]
    local = [a for a in arms if a not in HOSTED_ARMS]

    def lane() -> list[Path]:
        return [run(a, workers=1, **kwargs) for a in local]

    with ThreadPoolExecutor(max_workers=len(hosted) + 1) as pool:
        futures = [pool.submit(run, a, workers=workers, **kwargs) for a in hosted]
        lane_future = pool.submit(lane) if local else None
        paths = [f.result() for f in futures]
        if lane_future is not None:
            paths += lane_future.result()
    return paths


def seconds_per_answer(arm: str) -> float | None:
    """Mean seconds per answer in an arm's earlier runs (v2 to v4), errors left out."""
    durations = []
    for version in ("v2", "v3", "v4"):
        for path in SUITES[version].runs.glob("*.jsonl"):
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                r = json.loads(line)
                if not r["is_error"] and r["arm"].split("-")[0] == arm:
                    durations.append(r["duration_s"])
    return sum(durations) / len(durations) if durations else None


def estimate(version: str, repeat: int, extra_passes: int, workers: int) -> list[str]:
    """Markdown: expected wall time per arm, from its earlier runs' seconds per answer."""
    questions = load_key(version)
    answers = len(jobs(questions, repeat, extra_passes))
    volatile = sum(bool(q.get("extra_passes")) for q in questions)
    lines = [
        (
            f"{len(questions)} questions, {answers} answers ({repeat} full pass(es), "
            f"{extra_passes} extra on the {volatile} volatile questions). Local-server arms run "
            "one question at a time."
        ),
        "",
        f"| Arm | Seconds per answer | One at a time | {workers} at a time |",
        "| :-- | --: | --: | --: |",
    ]
    for arm in ARMS:
        s = seconds_per_answer(arm)
        if s is None:
            lines.append(f"| {arm} | – | – | – |")
            continue
        w = min(workers, MAX_WORKERS.get(arm, workers)) if arm in HOSTED_ARMS else 1
        lines.append(
            f"| {arm} | {s:.0f} | {answers * s / 60:.0f} min | {answers * s / 60 / w:.0f} min |"
        )
    return lines
