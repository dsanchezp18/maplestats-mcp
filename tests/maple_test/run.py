"""Ask the Maple Test questions through one arm and record every answer.

Every arm gets the same model, system prompt and agent loop: headless Claude Code
(`claude -p`) with every built-in tool off, run in an empty folder so nothing in this
repository (the answer key included) is in reach. Only the data access changes:

- maplestats: this repository's server over stdio (`--server-dir` picks the checkout)
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
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tests.maple_test.grade import SUITES, load_key

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
TIMEOUT_S = 600
MAX_TURNS = 25
ARMS = (
    "maplestats",
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
}


def servers(arm: str, server_dir: Path, alts: Path | None = None) -> dict[str, Any]:
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
                "command": str(home / "venv" / "bin" / "python"),
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
                "command": str(home / n / ".venv" / "bin" / "python"),
                "args": [str(home / n / "main.py")],
            }
            for n in names
        }
    if arm == "statcan2":
        return {"statcan2": {"type": "http", "url": "https://statcan2.ca/api/mcp"}}
    if arm == "maplestats":
        return {
            "maplestats": {
                "command": "uv",
                "args": ["run", "--directory", str(server_dir), "maplestats-mcp"],
                "env": {"MAPLE_TRANSPORT": "stdio"},
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
    with tempfile.TemporaryDirectory() as empty:
        try:
            proc = subprocess.run(
                command,
                input=question["question"],
                capture_output=True,
                text=True,
                cwd=empty,
                env={**os.environ, "ENABLE_TOOL_SEARCH": "false"},
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
        error, response = True, "MCP tools were not available. " + response
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
    )


def run(
    arm: str,
    model: str,
    server_dir: Path,
    only: list[str] | None,
    label: str,
    alts: Path | None = None,
    version: str = "v1",
    repeat: int = 1,
) -> Path:
    questions = [q for q in load_key(version) if not only or q["id"] in only]
    runs = SUITES[version].runs
    runs.mkdir(exist_ok=True)
    name = label or arm
    out = runs / f"{datetime.now(UTC).date().isoformat()}_{name}_{model}.jsonl"
    # A run is evidence: never overwrite one (a retry gets its own --label).
    if out.exists():
        raise SystemExit(f"{out.name} exists; pass --label to keep both runs")
    if alts is None and os.environ.get("MAPLE_TEST_ALTS"):
        alts = Path(os.environ["MAPLE_TEST_ALTS"])
    config_servers = servers(arm, server_dir, alts)
    with tempfile.TemporaryDirectory() as tmp:
        config = None
        if config_servers:
            config = Path(tmp) / "mcp.json"
            config.write_text(json.dumps({"mcpServers": config_servers}))
        with out.open("w", encoding="utf-8") as fh:
            # Whole passes, not each question three times in a row: a source that is down
            # for a minute then costs one answer per pass, not three of one question.
            for r in range(repeat):
                for q in questions:
                    answer = ask(arm, model, q, config, version)
                    answer.arm, answer.repeat = name, r
                    fh.write(json.dumps(asdict(answer), ensure_ascii=False) + "\n")
                    fh.flush()
                    state = "ERROR" if answer.is_error else f"{len(answer.tool_calls)} calls"
                    print(f"{q['id']}#{r} {name}: {state}, {answer.duration_s}s", file=sys.stderr)
    return out
