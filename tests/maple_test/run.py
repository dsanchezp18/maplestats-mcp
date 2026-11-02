"""Ask the Maple Test questions through one arm and record every answer.

Every arm gets the same model, system prompt and agent loop: headless Claude Code
(`claude -p`) with every built-in tool off, run in an empty folder so nothing in this
repository (the answer key included) is in reach. Only the data access changes:

- maplestats: this repository's server over stdio (`--server-dir` picks the checkout)
- mcp_statcan: the community mcp-statcan server's public endpoint
- no_tools: the model alone

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
ARMS = ("maplestats", "mcp_statcan", "no_tools")

PROMPT = """\
You answer questions about Canadian economic and social statistics. Today is {today}.

Use official sources: Statistics Canada and the Bank of Canada. With every figure, give \
the Statistics Canada table number (such as 14-10-0287-01) and vector (such as \
v2062815), or the Bank of Canada series, and the reference period.

If a figure does not exist or you cannot check it, say so instead of estimating. Keep \
the answer short."""


def servers(arm: str, server_dir: Path) -> dict[str, Any]:
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
    if names and not any(t.startswith(f"mcp__{names[0]}__") for t in tools):
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


def run(arm: str, model: str, server_dir: Path, only: list[str] | None, label: str) -> Path:
    questions = [q for q in load_key() if not only or q["id"] in only]
    RUNS.mkdir(exist_ok=True)
    name = label or arm
    out = RUNS / f"{datetime.now(UTC).date().isoformat()}_{name}_{model}.jsonl"
    with tempfile.TemporaryDirectory() as tmp:
        config = None
        if servers(arm, server_dir):
            config = Path(tmp) / "mcp.json"
            config.write_text(json.dumps({"mcpServers": servers(arm, server_dir)}))
        with out.open("w", encoding="utf-8") as fh:
            for q in questions:
                answer = ask(arm, model, q, config)
                answer.arm = name
                fh.write(json.dumps(asdict(answer), ensure_ascii=False) + "\n")
                fh.flush()
                state = "ERROR" if answer.is_error else f"{len(answer.tool_calls)} calls"
                print(f"{q['id']} {name}: {state}, {answer.duration_s}s", file=sys.stderr)
    return out
