"""Add a MapleStats arm to CanData's run_baseline.py without editing it.

CanData's harness is not copied here: clone it yourself and point CANDATA_REPO at it.

    git clone https://github.com/neobenjax/Canadian-Open-Data-Agentic-Platform.git candata
    export CANDATA_REPO=$PWD/candata
    python run_maplestats.py <maplestats_checkout> maplestats_after run --arm maplestats_after \
        --model claude-sonnet-5-5
    python run_maplestats.py <maplestats_checkout> maplestats_after grade

The arm runs exactly like their candata_mcp arm: a stdio MCP server, their system prompt,
their agent loop (headless `claude -p`, built-in tools off) and ENABLE_TOOL_SEARCH=false,
which their ask() sets. Run files land in their baseline/runs/ folder; grading merges
maplestats_overrides.json (our hand re-grades) over their manual_overrides.json.
"""

import importlib.util
import json
import os
import sys
from pathlib import Path

CANDATA = Path(os.environ["CANDATA_REPO"]) / "collaboration/benchmarks/run_baseline.py"
spec = importlib.util.spec_from_file_location("run_baseline", CANDATA)
rb = importlib.util.module_from_spec(spec)
sys.modules["run_baseline"] = rb
spec.loader.exec_module(rb)

server_dir, arm = sys.argv[1], sys.argv[2]
sys.argv = [sys.argv[0], *sys.argv[3:]]
rb.MCP_SERVERS[arm] = {
    "maplestats": {
        "command": "uv",
        "args": ["run", "--directory", server_dir, "maplestats-mcp"],
        "env": {"MAPLE_TRANSPORT": "stdio"},
    }
}
# Every MapleStats arm with a run file, so grading can order all of them.
seen = sorted(
    {p.name.split("_claude-")[0].split("_", 1)[1] for p in rb.RUNS_DIR.glob("*_maplestats_*.jsonl")}
)
rb.ARMS = (*rb.ARMS, *dict.fromkeys([*seen, arm]))
# Our hand re-grades live in our own file; merge them over CanData's for grading.
ours = Path(__file__).with_name("maplestats_overrides.json")
if ours.exists():
    theirs = json.loads(rb.OVERRIDES.read_text(encoding="utf-8"))
    merged = {**theirs, **json.loads(ours.read_text(encoding="utf-8"))}
    tmp = rb.OUT_DIR / "merged_overrides.json"
    tmp.write_text(json.dumps(merged), encoding="utf-8")
    rb.OVERRIDES = tmp
sys.exit(rb.main())
