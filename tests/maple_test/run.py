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
- no_tools: the model alone

The local-clone arms read `--alts` (or MAPLE_TEST_ALTS): a folder holding `openmcp/`
(cloned, `venv/` built, `catalog.duckdb` downloaded, per its README) and `candata/`
(the Canadian-Open-Data-Agentic-Platform repo, `uv sync` run). Keep it outside this
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

from tests.maple_test.grade import load_key

HERE = Path(__file__).resolve().parent
RUNS = HERE / "runs"
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
    "no_tools",
)

PROMPT = """\
You answer questions about Canadian economic and social statistics. Today is {today}.

Use official sources: Statistics Canada and the Bank of Canada. With every figure, give \
the Statistics Canada table number (such as 14-10-0287-01) and vector (such as \
v2062815), or the Bank of Canada series, and the reference period.

If a figure does not exist or you cannot check it, say so instead of estimating. Keep \
the answer short."""


def servers(arm: str, server_dir: Path, alts: Path | None = None) -> dict[str, Any]:
    if arm in ("openmcp", "candata_mcp") and alts is None:
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


def ask(arm: str, model: str, question: dict[str, Any], config: Path | None) -> Answer:
    started = datetime.now(UTC)
    command = [
        "claude",
        "-p",
        "--model",
        model,
        "--system-prompt",
        PROMPT.format(today=started.date().isoformat()),
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
    )


def run(
    arm: str,
    model: str,
    server_dir: Path,
    only: list[str] | None,
    label: str,
    alts: Path | None = None,
) -> Path:
    questions = [q for q in load_key() if not only or q["id"] in only]
    RUNS.mkdir(exist_ok=True)
    name = label or arm
    out = RUNS / f"{datetime.now(UTC).date().isoformat()}_{name}_{model}.jsonl"
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
            for q in questions:
                answer = ask(arm, model, q, config)
                answer.arm = name
                fh.write(json.dumps(asdict(answer), ensure_ascii=False) + "\n")
                fh.flush()
                state = "ERROR" if answer.is_error else f"{len(answer.tool_calls)} calls"
                print(f"{q['id']} {name}: {state}, {answer.duration_s}s", file=sys.stderr)
    return out
