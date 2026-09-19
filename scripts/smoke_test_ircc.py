"""Live smoke test for the IRCC Express Entry rounds client.

Run from the repository root with:

    uv run python scripts/smoke_test_ircc.py
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable
from typing import Any

from maple_data_mcp.modules.ircc import client
from maple_data_mcp.shared.errors import InvalidInput, NotFound


async def _check(label: str, awaitable: Awaitable[Any]) -> Any:
    try:
        result = await awaitable
        print(f"OK: {label} -> {type(result).__name__}")
        return result
    except Exception as exc:
        print(f"FAIL: {label} -> {type(exc).__name__}: {exc}")
        raise


async def main() -> int:
    latest_en = await _check(
        "get_latest_express_entry_round(en)", client.get_latest_express_entry_round()
    )
    latest_fr = await _check(
        "get_latest_express_entry_round(fr)", client.get_latest_express_entry_round(lang="fr")
    )
    if latest_en.round.draw_number != latest_fr.round.draw_number:
        print("FAIL: EN and FR feeds report different latest draw numbers")
        return 1
    if not any(ord(ch) > 127 for ch in latest_fr.round.program):
        print(
            "WARN: latest FR program has no accented characters -- cp1252 decoding "
            "not exercised by this round; not a hard failure."
        )

    listed = await _check("list_express_entry_rounds(default)", client.list_express_entry_rounds())
    if not listed.rounds or listed.rounds[0].draw_number != latest_en.round.draw_number:
        print("FAIL: list_express_entry_rounds' first row does not match the latest round")
        return 1

    filtered = await _check(
        "list_express_entry_rounds(program filter)",
        client.list_express_entry_rounds(program="Canadian Experience Class", limit=5),
    )
    if not filtered.rounds:
        print("FAIL: 'Canadian Experience Class' program filter returned zero rounds")
        return 1

    first_round = await _check("get_express_entry_round('1')", client.get_express_entry_round("1"))
    if first_round.round.draw_date.isoformat() != "2015-01-31":
        print(f"FAIL: round #1 draw_date was {first_round.round.draw_date}, expected 2015-01-31")
        return 1
    if first_round.round.eligibility_cutoff is not None:
        print("FAIL: round #1 was expected to have no published eligibility cutoff")
        return 1

    lettered_round = await _check(
        "get_express_entry_round('91a')", client.get_express_entry_round("91a")
    )
    if lettered_round.round.draw_date.isoformat() != "2018-05-30":
        print(
            f"FAIL: round #91a draw_date was {lettered_round.round.draw_date}, expected 2018-05-30"
        )
        return 1

    try:
        await client.get_express_entry_round("999999")
    except NotFound:
        print("OK: unknown draw number raises NotFound")
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: unknown draw number raised {type(exc).__name__}: {exc}")
        return 1

    try:
        await client.list_express_entry_rounds(limit=0)
    except InvalidInput:
        print("OK: limit=0 raises InvalidInput")
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: limit=0 raised {type(exc).__name__}: {exc}")
        return 1

    print(f"Latest round: #{latest_en.round.draw_number} on {latest_en.round.draw_date}")
    print(f"Latest CRS cutoff: {latest_en.round.crs_cutoff}")
    print("IRCC SMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
