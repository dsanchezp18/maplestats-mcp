"""Live smoke test for the statcan.reference module's client.py: calls the
real "Reference resources" catalogue search (not mocks), per AGENTS.md's
"lesson from auditing the StatCan module" -- a clean mocked pytest run only
proves the code matches assumptions the tests share with it, not that those
assumptions are correct.

Usage:
    uv run python scripts/smoke_test_statcan_reference.py
"""

from __future__ import annotations

import asyncio
import sys

from maple_data_mcp.modules.statcan.reference import client
from maple_data_mcp.shared.errors import InvalidInput, NotFound


async def main() -> int:
    ok = True

    result = await client.search_documents("housing")
    print(f"OK: search_documents('housing') -> {result.returned_count} of {result.total_matched}")
    ok &= result.total_matched > 50
    ok &= result.returned_count > 0
    sample = result.documents[0]
    print("  sample:", sample.model_dump())
    ok &= bool(sample.title)
    ok &= sample.url.startswith("http")

    empty = await client.search_documents("")
    print(f"OK: search_documents('') -> total_matched={empty.total_matched}")
    ok &= empty.total_matched > 1500  # confirmed live: 2,031

    fr = await client.search_documents("logement", lang="fr", count=5)
    print(f"OK: search_documents('logement', lang=fr) -> {fr.returned_count} of {fr.total_matched}")
    ok &= fr.total_matched > 0

    page2 = await client.search_documents("housing", page=2, count=5)
    print(f"OK: search_documents('housing', page=2) -> {page2.returned_count} results")
    ok &= page2.returned_count > 0
    ok &= page2.documents[0].title != result.documents[0].title

    try:
        await client.search_documents("housing", lang="de")
        print("FAIL: expected InvalidInput for a bogus lang")
        ok = False
    except InvalidInput:
        print("OK: bogus lang raises InvalidInput as expected")

    analysis = await client.search_analysis("housing")
    print(
        f"OK: search_analysis('housing') -> {analysis.returned_count} of {analysis.total_matched}"
    )
    ok &= analysis.catalogue == "analysis"
    ok &= analysis.total_matched > 0
    print("  sample:", analysis.documents[0].model_dump())

    analysis_fr = await client.search_analysis("logement", lang="fr", count=3)
    print(f"OK: search_analysis('logement', lang=fr) -> {analysis_fr.total_matched}")
    ok &= analysis_fr.total_matched > 0

    data = await client.search_data("Public Use Microdata Files")
    print(
        f"OK: search_data('Public Use Microdata Files') -> {data.returned_count} of {data.total_matched}"
    )
    ok &= data.catalogue == "data"
    ok &= data.total_matched > 50  # confirmed live: 144
    print("  sample:", data.documents[0].model_dump())

    data_fr = await client.search_data("logement", lang="fr", count=3)
    print(f"OK: search_data('logement', lang=fr) -> {data_fr.total_matched}")
    ok &= data_fr.total_matched > 0

    # Series-level catalogue number, works with dashes as given. This
    # page lists editions (each with its own catalogue number), not
    # formats -- confirmed live the table header reads "Titles", not
    # "Format".
    series = await client.get_document_formats("16-511-X")
    print(f"OK: get_document_formats('16-511-X') -> {len(series.editions)} edition(s)")
    ok &= bool(series.title)
    ok &= series.formats == []
    ok &= len(series.editions) > 0

    # Issue-level catalogue number, confirmed live to need dashes
    # stripped -- this exercises the fallback-on-404 path for real.
    formats_issue = await client.get_document_formats("46-28-0001202600100004")
    print(
        f"OK: get_document_formats('46-28-0001202600100004') -> "
        f"{[f.format for f in formats_issue.formats]}"
    )
    ok &= any(f.format == "PDF" and f.url.endswith(".pdf") for f in formats_issue.formats)
    ok &= formats_issue.catalogue_number == "46-28-0001202600100004"

    try:
        await client.get_document_formats("not-a-real-catalogue-number-00000")
        print("FAIL: expected NotFound for a bogus catalogue number")
        ok = False
    except NotFound:
        print("OK: bogus catalogue number raises NotFound as expected")

    print("\nSTATCAN REFERENCE SMOKE TEST PASSED" if ok else "\nSMOKE TEST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
