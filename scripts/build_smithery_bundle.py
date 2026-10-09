"""Build the MCPB bundle that .github/workflows/release.yml publishes to Smithery.

Smithery lists a local stdio server from an MCPB bundle. This one holds no
server code: its launch command runs the release's own PyPI package with
`uvx`, so the bundle only carries the manifest, a tool list and a tiny
launcher. Two Smithery CLI rules shape it (found publishing 0.1.0 and
EcuDataMCP's 0.8.12):

- The CLI recognizes the `node`, `python`, `binary` and `bun` server types,
  not MCPB's `uv` type, so the manifest declares `python`.
- A release without a tool list is rejected, and each tool must carry its
  `inputSchema`. The list is read from the server built here, so it matches
  the version being released.

Usage:
    uv run python scripts/build_smithery_bundle.py [output_dir]
"""

from __future__ import annotations

import asyncio
import json
import sys
import zipfile
from pathlib import Path

from fastmcp import Client

from maplestats_mcp import __version__
from maplestats_mcp.server import build_server

ROOT = Path(__file__).resolve().parent.parent
REPO = "https://github.com/dsanchezp18/maplestats-mcp"


async def list_tools() -> list[dict]:
    async with Client(build_server()) as client:
        tools = await client.list_tools()
    return [
        {
            "name": tool.name,
            # Smithery shows the first paragraph; long docstrings are cut.
            "description": (tool.description or "")
            .strip()
            .split("\n\n")[0]
            .replace("\n", " ")[:300],
            "inputSchema": tool.input_schema,
        }
        for tool in tools
    ]


def manifest(tools: list[dict]) -> dict:
    server = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))
    return {
        "manifest_version": "0.4",
        "name": "maplestats-mcp",
        "display_name": "MapleStats MCP",
        "version": __version__,
        "description": server["description"],
        "long_description": (
            "One MCP server for Canadian open data: Statistics Canada tables, Census and "
            "public use microdata, the Bank of Canada, CMHC, federal agencies, and federal, "
            "provincial and municipal open-data portals, in English and French. Read-only; "
            "no credentials needed. Runs the published PyPI package with uvx."
        ),
        "author": {"name": "Daniel Sánchez Pazmiño", "url": "https://github.com/dsanchezp18"},
        "repository": {"type": "git", "url": REPO},
        "homepage": "https://maplestats.danielstats.io/",
        "documentation": f"{REPO}#readme",
        "support": f"{REPO}/issues",
        "server": {
            "type": "python",
            "entry_point": "server.py",
            "mcp_config": {"command": "uvx", "args": [f"maplestats-mcp=={__version__}"]},
        },
        "tools": tools,
        "compatibility": {
            "platforms": ["darwin", "linux", "win32"],
            "runtimes": {"python": ">=3.12"},
        },
        "keywords": [
            "canada",
            "statistics-canada",
            "open-data",
            "census",
            "bank-of-canada",
            "cmhc",
        ],
        "license": "MIT",
    }


def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dist"
    out_dir.mkdir(parents=True, exist_ok=True)
    tools = asyncio.run(list_tools())
    if not tools:
        print("No tools listed; Smithery would reject the release.", file=sys.stderr)
        return 1

    launcher = (
        '"""Launcher: the server itself is the maplestats-mcp package on PyPI."""\n'
        "import subprocess\nimport sys\n\n"
        f'sys.exit(subprocess.call(["uvx", "maplestats-mcp=={__version__}"]))\n'
    )
    bundle = out_dir / f"maplestats-mcp-{__version__}.mcpb"
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest(tools), indent=2, ensure_ascii=False))
        archive.writestr("server.py", launcher)
    print(f"{bundle} ({len(tools)} tools)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
