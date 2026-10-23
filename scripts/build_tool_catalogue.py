"""Regenerate src/maplestats_mcp/tool_catalogue.json from the modules' code.

Run it after adding, removing or changing a tool (its name, docstring,
parameters or return model); tests/test_tool_catalogue.py fails until the
file matches the code. See maplestats_mcp/catalogue.py for why it exists.
"""

from __future__ import annotations

from maplestats_mcp.catalogue import CATALOGUE_PATH, write_catalogue

if __name__ == "__main__":
    write_catalogue()
    print(f"wrote {CATALOGUE_PATH}")
