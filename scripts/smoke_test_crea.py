"""Live smoke test for the CREA MLS® HPI links module.

The module's only request is a HEAD on the monthly zip URL; this checks
that the URL it builds for the current release month answers.
"""

from __future__ import annotations

import asyncio
import sys

from maplestats_mcp.modules.crea import client


async def main() -> int:
    failures = 0
    for lang in ("en", "fr"):
        links = await client.get_hpi_links(lang=lang)
        print(
            f"OK: {lang} release_month={links.release_month} zip={links.zip_url} "
            f"confirmed={links.zip_confirmed} size={links.zip_size_bytes} "
            f"last_modified={links.zip_last_modified}"
        )
        failures += not links.zip_confirmed
        failures += len(links.pages) != 5 or len(links.open_alternatives) != 3

    print("CREA SMOKE TEST " + ("PASSED" if not failures else f"FAILED ({failures})"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
