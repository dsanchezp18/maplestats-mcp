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
    print(
        f"OK: 62-553-X 'owned accommodation' -> {[s.id for s in owned.sections]}, "
        f"{owned.pages_read} pages read"
    )
    # Chapter 10's title holds both words: it is read first and the search stops
    # well before the edition's 15 pages (6 on 2026-11-10).
    ok &= owned.sections[0].id.startswith("chap-10") and owned.pages_read < 12

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

    provincial = await client.get_section_text("13-017-X", query="provincial allocation")
    print(
        f"OK: 13-017-X 'provincial allocation' -> {[s.id for s in provincial.sections]}, "
        f"{provincial.pages_read} pages read"
    )
    # 6.4 "Estimation methods - provincial and territorial estimates" and 2.176
    # "The Provincial Economic Accounts" (each in the top three of all 146 pages).
    found = {s.id.partition("#")[0] for s in provincial.sections}
    ok &= bool(found & {"themes/ch06/5213357", "themes/ch02/5213339"})

    deep = await client.get_section_text("13-607-X", section="224", max_chars=300)
    print(f"OK: 13-607-X section '224' (a page id below the main page) -> {deep.sections[0].title}")
    ok &= deep.sections[0].title == "Provincial and Territorial Gross Domestic Product"

    # PDF-only editions: the text is extracted from the PDF.
    pdf = await client.get_publication("15-203-X")
    print(
        f"OK: get_publication('15-203-X') -> format={pdf.format} {pdf.url}, "
        f"{len(pdf.sections)} sections"
    )
    ok &= pdf.format == "pdf" and pdf.url.endswith(".pdf") and len(pdf.sections) > 100
    ok &= "extracted from the PDF" in (pdf.provenance.limits or "")

    methods = await client.get_section_text("15-203-X", query="gross output approach", limit=3)
    best = methods.sections[0]
    print(f"OK: 15-203-X 'gross output approach' -> [{best.id}] {best.title} {best.url}")
    # The provincial allocation methods (net output, gross output, selected factor
    # incomes) are on PDF pages 188 to 196 of the 1984-1999 edition; "Gross Output
    # Approach" is a heading on page 192.
    ok &= best.title == "Gross Output Approach" and best.url == pdf.url + "#page=192"
    ok &= "allocating national gross output" in best.text

    page = await client.get_section_text("15-203-X", section="192", max_chars=6000)
    print(f"OK: 15-203-X section '192' -> {page.sections[0].title}")
    ok &= "selected factor incomes" in page.sections[0].text.lower()

    lfs_2006 = await client.get_section_text(
        "71-543-G", edition="2006", query="involuntary part-time", limit=1
    )
    print(f"OK: 71-543-G 2006 (PDF) 'involuntary part-time' -> {lfs_2006.sections[0].url}")
    ok &= lfs_2006.format == "pdf" and "involuntary part-time" in lfs_2006.sections[0].text.lower()

    # The CLF 2.0 layout of the 2007-2012 LFS guides (windows-1252 under a UTF-8
    # header, its text in div.center).
    lfs_2008 = await client.get_section_text("71-543-G", edition="2008", section="Sections")
    print(f"OK: 71-543-G 2008 section 'Sections' -> {lfs_2008.sections[0].title!r}")
    ok &= "menu" not in lfs_2008.sections[0].title.lower()
    ok &= "�" not in lfs_2008.sections[0].text

    # R1 to R8 are not in the LFS guide: the result says where they are defined.
    rates = await client.get_section_text(
        "71-543-G", query="supplementary unemployment rates R1 R8"
    )
    print(f"OK: 71-543-G 'supplementary unemployment rates R1 R8' -> {rates.provenance.limits!r}")
    ok &= "14-10-0077-01" in (rates.provenance.limits or "")

    try:
        await client.get_publication("https://example.com/n1/pub/71-543-g/x-eng.htm")
        print("FAIL: expected InvalidInput for a non-StatCan URL")
        ok = False
    except InvalidInput:
        print("OK: a non-StatCan URL raises InvalidInput")
    return ok


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
