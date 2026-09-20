"""Live smoke test for ISED's Spectrum Management System licence site data."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable
from typing import Any

from maple_data_mcp.modules.ised.spectrum import client
from maple_data_mcp.shared.errors import InvalidInput


async def _check(label: str, awaitable: Awaitable[Any]) -> Any:
    try:
        result = await awaitable
        print(f"OK: {label} -> {type(result).__name__}")
        return result
    except Exception as exc:
        print(f"FAIL: {label} -> {type(exc).__name__}: {exc}")
        raise


async def main() -> int:
    result = await _check("query_licences()", client.query_licences(limit=3))
    if not result.rows:
        print("FAIL: ISED spectrum query returned no rows at all")
        return 1
    if "LICENSEE" not in result.rows[0]:
        print("FAIL: expected LICENSEE field missing from a row")
        return 1

    licensee = result.rows[0]["LICENSEE"]
    filtered = await _check(
        "query_licences(where=LICENSEE)",
        client.query_licences(where=f"LICENSEE = '{licensee}'", limit=3),
    )
    if not filtered.rows:
        print(f"FAIL: filtering by LICENSEE = {licensee!r} returned no rows")
        return 1

    try:
        await client.query_licences(limit=0)
    except InvalidInput:
        print("OK: limit=0 raises InvalidInput")
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: limit=0 raised {type(exc).__name__}: {exc}")
        return 1

    print(f"Sample row LICENSEE: {licensee!r}")
    print("ISED-SPECTRUM SMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
