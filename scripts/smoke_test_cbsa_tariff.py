"""Live smoke test for the cbsa_tariff module: downloads CBSA's real Customs
Tariff databases (not mocks) and calls every client function and every
tool, per AGENTS.md's "lesson from auditing the StatCan module".

The first run reads three editions (2026-2 in English and French, and one
from 2018), about 30 s; later runs use the Parquet copies in
MAPLE_CBSA_TARIFF_CACHE_DIR.

Usage:
    uv run python scripts/smoke_test_cbsa_tariff.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
import tracemalloc

from fastmcp import Client
from mcp.types import TextContent

from maplestats_mcp.modules.cbsa_tariff import client
from maplestats_mcp.server import mcp
from maplestats_mcp.shared.errors import InvalidInput, NotFound


async def _expect_error(label: str, coro, exc_type: type[Exception]) -> bool:
    try:
        await coro
    except exc_type as exc:
        print(f"OK: {label} -> {type(exc).__name__}: {str(exc)[:120]}")
        return True
    except Exception as exc:  # noqa: BLE001 - smoke test wants to see everything
        print(f"FAIL: {label} -> {type(exc).__name__}: {exc}")
        return False
    print(f"FAIL: {label} -> no error")
    return False


def _check(label: str, condition: bool, detail: object = "") -> bool:
    print(f"{'OK' if condition else 'FAIL'}: {label} {detail}")
    return condition


async def main() -> bool:
    ok = True

    editions = await client.list_editions()
    labels = [e.edition for e in editions.editions]
    ok &= _check("list_editions", "2026-2" in labels, labels)
    older = await client.list_editions(year=2018, lang="fr")
    ok &= _check(
        "list_editions 2018 (fr)",
        len(older.editions) == 4 and older.editions[0].access_zip_url.endswith("-fra.zip"),
        [(e.edition, str(e.effective_date)) for e in older.editions],
    )
    commented = await client.list_editions(year=2023)
    ok &= _check(
        "2023 skips the commented-out T2023-2",
        "2023-2" not in [e.edition for e in commented.editions],
        [e.edition for e in commented.editions],
    )

    tracemalloc.start()
    started = time.monotonic()
    ev = await client.lookup("8703.80.00", edition="2026-2")
    peak = tracemalloc.get_traced_memory()[1] / 2**20
    tracemalloc.stop()
    item = ev.item
    ok &= _check(
        "lookup 8703.80.00 (2026-2)",
        item is not None
        and item.mfn == "6.1 %"
        and item.general == "35%"
        and {r.code: r.percent for r in item.rates}.get("GPT") == 6.0
        and {r.code: r.text for r in item.rates}.get("CPUKT") == "Free",
        f"{time.monotonic() - started:.1f} s, peak {peak:.0f} MB traced; "
        f"{item.description if item else None}; ancestors "
        f"{[a.tariff for a in ev.ancestors]}; children {ev.total_children}",
    )

    dairy = await client.lookup("0401.10.10")
    rates = {r.code: r.text for r in dairy.item.rates} if dairy.item else {}
    ok &= _check(
        "lookup 0401.10.10 (latest): supply-managed, no CUSMA Mexico rate",
        dairy.item is not None and dairy.item.mfn == "7.5 %" and "MXT" not in rates,
        rates,
    )

    heading = await client.lookup("8703")
    ok &= _check(
        "lookup heading 8703 lists lines under it",
        heading.item is not None and heading.total_children > 20,
        f"{heading.total_children} children, first {[c.tariff for c in heading.children[:4]]}",
    )

    long_text = await client.lookup("9913.00.00")
    description = long_text.item.description if long_text.item else ""
    ok &= _check(
        "lookup 9913.00.00 joins DESC1 and DESC2",
        len(description) > 30_000 and "Domazoline" in description,
        len(description),
    )

    french = await client.lookup("2711.12.90", lang="fr")
    ok &= _check(
        "lookup 2711.12.90 (fr)",
        french.item is not None
        and french.item.description == "Autres"
        and french.item.mfn == "En fr."
        and french.item.rates[0].percent == 0.0
        and french.item.rates[0].name.startswith("Tarif de la nation"),
        [(a.tariff, a.description[:40]) for a in french.ancestors],
    )

    dated = await client.lookup("8703.80.00", edition="2018-06-01")
    codes = [r.code for r in dated.item.rates] if dated.item else []
    ok &= _check(
        "lookup on 2018-06-01: edition 2018, NAFTA columns, no CPTPP",
        dated.edition.edition == "2018" and "MUST" in codes and "CPTPT" not in codes,
        (dated.edition.edition, dated.item.mfn if dated.item else None, codes),
    )

    syrup = await client.search("maple syrup")
    ok &= _check(
        "search 'maple syrup'",
        any(line.digits.startswith("1702") for line in syrup.lines),
        [(line.tariff, line.description[:50], line.mfn) for line in syrup.lines],
    )
    vehicles = await client.search("electric", chapter="87", limit=5)
    ok &= _check(
        "search 'electric' in chapter 87",
        vehicles.returned_count == 5 and vehicles.total_matches > 5,
        f"{vehicles.total_matches} matches; {vehicles.provenance.limits}",
    )
    erable = await client.search("sirop d'érable", lang="fr")
    ok &= _check(
        "search (fr) 'sirop d'érable'",
        erable.total_matches > 0,
        [(line.tariff, line.description[:50]) for line in erable.lines],
    )
    return ok


async def errors() -> bool:
    ok = True
    ok &= await _expect_error("words as a number", client.lookup("cheese"), InvalidInput)
    ok &= await _expect_error("missing number", client.lookup("0000.00"), NotFound)
    ok &= await _expect_error("unknown edition", client.lookup("8703", edition="2025-9"), NotFound)
    ok &= await _expect_error("bad edition", client.search("cheese", edition="soon"), InvalidInput)
    ok &= await _expect_error("year too early", client.list_editions(year=2010), InvalidInput)
    ok &= await _expect_error("empty search", client.search(""), InvalidInput)
    return ok


async def through_server() -> bool:
    """Every tool once through call_tool, as a client reaches it."""
    ok = True
    calls = [
        ("cbsa_tariff_list_editions", {"lang": "fr"}),
        ("cbsa_tariff_lookup", {"tariff_item": "0406.90", "edition": "latest"}),
        ("cbsa_tariff_search", {"query": "cheddar", "chapter": "4", "limit": 3, "lang": "fr"}),
    ]
    async with Client(mcp) as session:
        for name, args in calls:
            result = await session.call_tool("call_tool", {"name": name, "arguments": args})
            text = next(c.text for c in result.content if isinstance(c, TextContent))
            data = json.loads(text)
            ok &= _check(f"call_tool({name})", not result.is_error, sorted(data)[:6])
    return ok


async def run() -> int:
    ok = await main()
    ok &= await errors()
    ok &= await through_server()
    print("ALL OK" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
