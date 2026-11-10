"""Live smoke test for the statcan.reference module's client.py: calls the
real "Reference resources" catalogue search (not mocks), per AGENTS.md's
"lesson from auditing the StatCan module" -- a clean mocked pytest run only
proves the code matches assumptions the tests share with it, not that those
assumptions are correct.

A sustained HTTP 429 from www150.statcan.gc.ca (seen on GitHub runners, where
many StatCan smoke jobs share IPs, even after the shared client's retries) is
skipped rather than failed: it is StatCan's rate limit, not a module fault.
Since 2026-10-29 every /n1/{lang}/type/ listing answers 404 or loops on
redirects while StatCan's own menus still link them; the client raises
UpstreamUnavailable for that, which is reported as SKIPPED, not FAILED.

The publication tools (statcan_reference_get_publication, _get_section_text) read
catalogue pages and /n1/pub/ pages, which are up while the listings are not: they
run in their own block, after the searches.

Usage:
    uv run python scripts/smoke_test_statcan_reference.py
"""

from __future__ import annotations

import asyncio
import sys

from _smoke_common import skip_outage, verdict

from maplestats_mcp.modules.statcan.reference import client
from maplestats_mcp.shared.errors import InvalidInput, UpstreamError, UpstreamUnavailable


async def main() -> int:
    ok = True

    try:
        result = await client.search_documents("housing")
        print(
            f"OK: search_documents('housing') -> {result.returned_count} of {result.total_matched}"
        )
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
        print(
            f"OK: search_documents('logement', lang=fr) -> {fr.returned_count} of {fr.total_matched}"
        )
        ok &= fr.total_matched > 0

        page2 = await client.search_documents("housing", page=2, count=5)
        print(f"OK: search_documents('housing', page=2) -> {page2.returned_count} results")
        ok &= page2.returned_count > 0
        ok &= page2.documents[0].title != result.documents[0].title

        # A search matching nothing is StatCan's "found no results" page (no
        # #ndm-results): an empty result with a hint, not an upstream error.
        none = await client.search_documents("owned accommodation CPI")
        print(f"OK: search_documents('owned accommodation CPI') -> {none.total_matched}")
        ok &= none.returned_count == 0
        ok &= "every word" in (none.provenance.limits or "")

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
    except UpstreamError as exc:
        # A rate limit is StatCan's, not ours; any other UpstreamError still fails.
        if "HTTP 429" not in str(exc):
            skip_outage("StatCan's reference catalogue", exc)
        else:
            skip_outage("StatCan's reference catalogue (HTTP 429)", UpstreamUnavailable(str(exc)))
    except UpstreamUnavailable as exc:
        skip_outage("StatCan's reference catalogue", exc)

    # The publications themselves (catalogue pages and /n1/pub/ pages), which do not
    # go through the /n1/{lang}/type/ listings above and are checked even when those
    # are down.
    try:
        ok &= await _publications()
    except (UpstreamError, UpstreamUnavailable) as exc:
        skip_outage("StatCan's publication pages", exc)

    return verdict("STATCAN REFERENCE", ok)


async def _publications() -> bool:
    ok = True
    lfs = await client.get_publication("71-543-G")
    ids = [section.id for section in lfs.sections]
    print(
        f"OK: get_publication('71-543-G') -> {lfs.title}, issue {lfs.issue} "
        f"({lfs.release_date}), {len(ids)} sections, {lfs.editions_total} editions"
    )
    ok &= lfs.format == "html" and bool(lfs.issue) and bool(lfs.pdf_url)
    ok &= "a3" in ids and len(ids) > 20 and lfs.editions_total > 10

    text = await client.get_section_text("71-543-G", query="involuntary part-time")
    best = text.sections[0]
    print(f"OK: query 'involuntary part-time' -> [{best.id}] {best.title}: {best.text[:120]!r}")
    ok &= "involuntary part-time" in best.text.lower() and "#" in best.url

    section = await client.get_section_text("71-543-G", section="a3", max_chars=500)
    print(f"OK: section 'a3' -> {section.sections[0].total_chars} chars, cut at 500")
    ok &= section.sections[0].next_start_char is not None

    owned = await client.get_section_text("62-553-X", query="owned accommodation")
    print(f"OK: 62-553-X 'owned accommodation' -> {[s.id for s in owned.sections]}")
    ok &= owned.sections[0].id.startswith("chap-10") and owned.pages_read > 10

    basket = await client.get_section_text("62-553-X", section="Weights and Basket Updates")
    print(f"OK: 62-553-X section 'Weights and Basket Updates' -> {basket.sections[0].id}")
    ok &= "basket" in basket.sections[0].text.lower()

    iea = await client.get_publication("13-017-X")
    print(f"OK: get_publication('13-017-X') -> {iea.issue}, archived={iea.archived}")
    ok &= iea.archived and len(iea.sections) > 10

    labour = await client.get_section_text("13-017-X", query="supplementary labour income", limit=2)
    print(f"OK: 13-017-X 'supplementary labour income' -> {[s.id for s in labour.sections]}")
    ok &= bool(labour.sections) and "supplementary labour income" in labour.sections[0].text.lower()

    french = await client.get_section_text(
        "71-543-G", query="temps partiel involontaire", lang="fr", limit=1
    )
    print(f"OK: French query -> {french.sections[0].url}: {french.sections[0].text[:100]!r}")
    ok &= french.edition_url.endswith("-fra.htm")
    ok &= "temps partiel involontaire" in french.sections[0].text.lower()

    article = await client.get_section_text("62F0014M2021011", query="basket weights", limit=1)
    print(f"OK: 62F0014M2021011 'basket weights' -> {article.sections[0].title}")
    ok &= bool(article.sections)

    pdf = await client.get_publication("15-203-X")
    print(f"OK: get_publication('15-203-X') -> format={pdf.format} {pdf.url}")
    ok &= pdf.format == "pdf" and pdf.url.endswith(".pdf")

    try:
        await client.get_publication("https://example.com/n1/pub/71-543-g/x-eng.htm")
        print("FAIL: expected InvalidInput for a non-StatCan URL")
        ok = False
    except InvalidInput:
        print("OK: a non-StatCan URL raises InvalidInput")
    return ok


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
