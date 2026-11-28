"""statcan_reference_get_section_text reads scanned PDF pages by OCR, within its caps.

The render-and-read step (PDFium and Tesseract) is replaced by canned text, so these
tests need neither; tests/test_shared_ocr_engine.py reads a real scan with the real
engine. The PDFs are hand-built (tests/pdf_builder.py): a page that is one image and
has no text layer, as a scanner writes it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from maplestats_mcp.modules.statcan.reference import client, scans
from maplestats_mcp.shared import ocr
from maplestats_mcp.shared.errors import InvalidInput
from tests.pdf_builder import BlankPage, ImagePage, TextPage, build_pdf, scan

URL = "https://www150.statcan.gc.ca/n1/pub/15-203-x/15-203-x1999000-eng.pdf"
ENGINE = ocr.Engine("/usr/bin/tesseract", "5.5", "eng+fra")
PROSE = TextPage(["This page carries more than twenty-five characters of running text."])
FIXTURES = Path(__file__).parent / "fixtures"
TOOL = "statcan_reference:get_section_text"


@pytest.fixture(autouse=True)
def _ocr_off_unless_a_test_turns_it_on(monkeypatch):
    monkeypatch.delenv("MAPLE_OCR", raising=False)
    ocr.reset()


@pytest.fixture
def engine(monkeypatch) -> list[int]:
    """An engine that works: the pages it was asked to read are recorded."""
    monkeypatch.setattr(ocr, "status", lambda lang="en": ocr.Status(ENGINE))
    calls: list[int] = []

    def read(body, number, engine, dpi, wait, memory_mb):
        calls.append(number)
        return ocr._Recognised(
            f"Compte rendu page {number}\n\nElectoral Division Arthur 2,716", 93.2, dpi
        )

    monkeypatch.setattr(ocr, "_read_page", read)
    return calls


def _plain(text: str) -> str:
    return text.replace("\xa0", " ")


async def _read(httpx_mock, pages, **kwargs):
    httpx_mock.add_response(url=URL, content=build_pdf(pages), is_reusable=True)
    return await client.get_section_text(URL, **kwargs)


async def test_auto_reads_the_scanned_pages_and_says_what_it_did(httpx_mock, engine):
    result = await _read(httpx_mock, [scan(), scan(), scan()])
    assert engine == [1, 2, 3]
    assert result.ocr_pages == [1, 2, 3] and result.pages_without_text == 3
    text = result.sections[0].text
    assert "Compte rendu page 2" in text and "Electoral Division Arthur 2,716" in text
    assert (
        "[Page 2: text recognised by OCR from a scan (Tesseract 5.5, eng+fra, 200 dpi, mean" in text
    )
    assert "word confidence 93%), not the publisher's text layer." in text
    assert "has no text layer" not in text
    limits = result.provenance.limits or ""
    assert (
        "OCR (Tesseract 5.5, eng+fra, 200 dpi) read pages 1-3 of 3 (caps: 10 pages, 40 s, "
        "12 MP a page). The text is recognised from a scan, not the publisher's text layer: "
        f"check figures against the page image ({URL}#page=N)."
    ) in limits
    # What was read no longer comes back empty: no "empty" note and nothing left uncovered.
    assert "come back empty" not in limits and result.provenance.coverage is None
    (caveat,) = result.provenance.caveats
    assert "Check every figure against the page image" in caveat and f"{URL}#page=N" in caveat


async def test_the_report_s_wording_for_36_pages_in_both_languages(httpx_mock, engine):
    english = await _read(httpx_mock, [scan()] * 36)
    assert engine == [1, 2, 3, 4, 5]
    assert english.ocr_pages == [1, 2, 3, 4, 5]
    assert (
        "OCR (Tesseract 5.5, eng+fra, 200 dpi) read pages 1-5 of 36 (caps: 10 pages, 40 s, "
        "12 MP a page); pages 6-36 not read, pass pages='6-10'. The text is recognised from a "
        "scan, not the publisher's text layer: check figures against the page image ("
    ) in (english.provenance.limits or "")
    assert english.provenance.coverage == (
        "The text of pages 6-36 is not included (no text layer; 36 pages read)."
    )
    french = await client.get_section_text(URL, lang="fr")
    assert (
        "Reconnaissance optique (Tesseract 5.5, eng+fra, 200 ppp) : pages 1 à 5 sur 36 lues "
        "(plafonds : 10 pages, 40 s, 12 Mpx par page) ; pages 6 à 36 non lues, passez "
        "pages='6-10'. Le texte est reconnu à partir d'une numérisation, non fourni par "
        "l'éditeur : vérifiez les chiffres sur l'image de la page ("
    ) in _plain(french.provenance.limits or "")
    assert "[Page 3 : texte reconnu par reconnaissance optique" in _plain(french.sections[0].text)
    assert "Texte issu de la reconnaissance optique" in french.provenance.caveats[0]
    assert _plain(french.provenance.coverage or "").startswith("Le texte des pages 6 à 36")


async def test_pages_picks_other_pages_and_names_the_rest(httpx_mock, engine):
    result = await _read(httpx_mock, [scan()] * 36, page_selector="6-8")
    assert engine == [6, 7, 8] and result.ocr_pages == [6, 7, 8]
    assert "read pages 6-8 of 36" in (result.provenance.limits or "")
    # Pages 1-5 and 9-36 still have no text and say so.
    assert "No text layer on pages 1-5, 9-36 (33 of 36 pages read)" in (
        result.provenance.limits or ""
    )
    assert "has no text layer" in result.sections[0].text


async def test_more_than_ten_pages_asked_for_reads_ten(httpx_mock, engine):
    result = await _read(httpx_mock, [scan()] * 12, page_selector="1-12")
    assert engine == list(range(1, 11)) and result.ocr_pages == list(range(1, 11))
    assert "pages 11-12 not read, pass pages='11-12'" in (result.provenance.limits or "")


async def test_a_page_section_reads_only_that_page(httpx_mock, engine):
    result = await _read(httpx_mock, [scan()] * 6, section="page=4")
    assert engine == [4] and result.ocr_pages == [4]
    assert "Compte rendu page 4" in result.sections[0].text


async def test_a_bookmark_section_reads_the_scans_it_spans(httpx_mock, engine):
    import io

    from pypdf import PdfWriter

    writer = PdfWriter(clone_from=io.BytesIO(build_pdf([scan()] * 6)))
    writer.add_outline_item("Part one", 0)
    writer.add_outline_item("Part two", 3)
    out = io.BytesIO()
    writer.write(out)
    httpx_mock.add_response(url=URL, content=out.getvalue(), is_reusable=True)
    result = await client.get_section_text(URL, section="Part two")
    assert engine == [4, 5, 6] and result.ocr_pages == [4, 5, 6]


async def test_a_query_searches_the_text_of_the_pages_read(httpx_mock, engine):
    result = await _read(httpx_mock, [scan()] * 3, query="electoral division arthur")
    assert result.ocr_pages == [1, 2, 3]
    assert result.sections and "Electoral Division Arthur" in result.sections[0].text


async def test_auto_reads_scans_only_and_pages_names_a_page_with_text(httpx_mock, engine):
    result = await _read(httpx_mock, [PROSE, scan(), scan(), BlankPage()])
    assert engine == [2, 3] and result.ocr_pages == [2, 3]
    # The blank page is no scan: counted as without text, not read.
    assert result.pages_without_text == 3
    asked = await client.get_section_text(URL, page_selector="1")
    assert asked.ocr_pages == [] and engine == [2, 3]
    assert "Page 1 has a text layer, so OCR did not read it (ocr='force' reads it anyway)." in (
        asked.provenance.limits or ""
    )


async def test_a_few_scanned_pages_among_text_pages_are_not_read_unasked(httpx_mock, engine):
    # 15-203-X has 5 image pages among 277: reading them first would cost seconds and
    # put chart text in the search.
    result = await _read(httpx_mock, [PROSE] * 6 + [scan()])
    assert engine == [] and result.ocr_pages == [] and result.pages_without_text == 1
    limits = result.provenance.limits or ""
    assert (
        "Page 7 is scanned, too few among the pages with text to be read by OCR unasked: "
        "pass pages='7' to read it."
    ) in limits
    french = await client.get_section_text(URL, lang="fr")
    assert "La page 7 est numérisée, trop peu nombreuses parmi les pages avec texte" in _plain(
        french.provenance.limits or ""
    )
    assert "passez pages='7' pour la lire" in _plain(french.provenance.limits or "")
    # Asked for by number, or by section, it is read.
    by_pages = await client.get_section_text(URL, page_selector="7")
    assert by_pages.ocr_pages == [7]
    by_section = await client.get_section_text(URL, section="page=7")
    assert by_section.ocr_pages == [7] and engine == [7]


async def test_the_hint_to_ask_for_scanned_pages_is_only_given_where_ocr_runs(httpx_mock):
    result = await _read(httpx_mock, [PROSE] * 6 + [scan()])
    assert "too few among the pages with text" not in (result.provenance.limits or "")
    assert "No text layer on page 7" in (result.provenance.limits or "")


async def test_force_reads_a_page_that_has_text_and_replaces_its_text(httpx_mock, engine):
    result = await _read(httpx_mock, [PROSE, scan()], ocr="force", page_selector="1")
    assert engine == [1] and result.ocr_pages == [1]
    text = result.sections[0].text
    # The page's title is its first line as extracted; its body is the OCR text.
    body = text.split("\n\n", 1)[1]
    assert "Compte rendu page 1" in body and "running text" not in body
    # Page 2 was not asked for and is still an image.
    assert "[Page 2 has no text layer" in text


async def test_force_without_pages_reads_the_first_five(httpx_mock, engine):
    result = await _read(httpx_mock, [PROSE] * 7, ocr="force")
    assert engine == [1, 2, 3, 4, 5] and result.ocr_pages == [1, 2, 3, 4, 5]
    assert "pages 6-7 not read, pass pages='6-7'" in (result.provenance.limits or "")


async def test_off_reads_nothing_and_says_the_pages_stay_empty(httpx_mock, engine):
    result = await _read(httpx_mock, [scan(), scan()], ocr="off")
    assert engine == [] and result.ocr_pages == []
    limits = result.provenance.limits or ""
    assert "OCR was switched off (ocr='off'), so the pages without text stay empty." in limits
    assert "No text layer on pages 1-2" in limits


async def test_a_text_pdf_is_not_read_by_ocr(httpx_mock, engine):
    result = await _read(httpx_mock, [PROSE, PROSE])
    assert engine == [] and result.ocr_pages == [] and result.provenance.caveats == []


@pytest.mark.parametrize(
    ("reason", "english", "french"),
    [
        (
            "disabled",
            "OCR is not enabled on this server (it is switched on with MAPLE_OCR=1)",
            "La reconnaissance optique n'est pas activée sur ce serveur",
        ),
        (
            "pypdfium2",
            "OCR is enabled but the 'ocr' extra (pypdfium2) is not installed here",
            "l'extra « ocr » (pypdfium2) n'est pas installé ici",
        ),
        (
            "tesseract",
            "OCR is enabled but the tesseract program is not installed here",
            "le programme tesseract n'est pas installé ici",
        ),
        (
            "languages",
            "tesseract has no English or French language data (eng, fra) here",
            "tesseract n'a ici aucune donnée de langue anglaise ou française",
        ),
    ],
)
async def test_where_ocr_cannot_run_auto_returns_the_pages_empty_and_says_why(
    reason, english, french, httpx_mock, monkeypatch
):
    monkeypatch.setattr(ocr, "status", lambda lang="en": ocr.Status(None, reason))
    result = await _read(httpx_mock, [scan(), scan()])
    limits = result.provenance.limits or ""
    assert english in limits and "so the pages without text stay empty." in limits
    # The Stage 0 note is still there: the pages are counted, named and empty.
    assert result.ocr_pages == [] and result.pages_without_text == 2
    assert "No text layer on pages 1-2 (2 of 2 pages read)" in limits
    assert "[Page 1 has no text layer" in result.sections[0].text
    assert result.provenance.caveats == []
    in_french = await client.get_section_text(URL, lang="fr")
    assert french in _plain(in_french.provenance.limits or "")
    assert "les pages sans texte restent donc vides" in _plain(in_french.provenance.limits or "")


async def test_a_server_with_ocr_off_by_default_says_so(httpx_mock):
    # No patching: MAPLE_OCR is unset, as on the Render backup.
    result = await _read(httpx_mock, [scan()])
    assert "OCR is not enabled on this server (it is switched on with MAPLE_OCR=1)" in (
        result.provenance.limits or ""
    )


@pytest.mark.parametrize("reason", ["disabled", "pypdfium2", "tesseract", "languages"])
async def test_force_where_ocr_cannot_run_is_an_error_in_both_languages(
    reason, httpx_mock, monkeypatch
):
    monkeypatch.setattr(ocr, "status", lambda lang="en": ocr.Status(None, reason))
    httpx_mock.add_response(url=URL, content=build_pdf([scan()]), is_reusable=True)
    with pytest.raises(InvalidInput, match=r"ocr='force' cannot run: OCR is") as english:
        await client.get_section_text(URL, ocr="force")
    assert URL in str(english.value)
    with pytest.raises(InvalidInput, match="Entrée invalide") as french:
        await client.get_section_text(URL, ocr="force", lang="fr")
    assert "ocr='force' ne peut pas s'exécuter" in _plain(str(french.value))


async def test_pages_and_force_need_a_pdf_edition(httpx_mock):
    n1 = "https://www150.statcan.gc.ca/n1"
    httpx_mock.add_response(
        url=f"{n1}/en/catalogue/71-543-G",
        html=(FIXTURES / "catalogue_71-543-G_en.html").read_text(encoding="utf-8"),
    )
    httpx_mock.add_response(
        url=f"{n1}/pub/71-543-g/71-543-g2025001-eng.htm",
        html=(FIXTURES / "lfs_2025001_en.html").read_text(encoding="utf-8"),
    )
    with pytest.raises(InvalidInput, match="is an HTML edition"):
        await client.get_section_text("71-543-G", page_selector="3")
    with pytest.raises(InvalidInput, match="is an HTML edition"):
        await client.get_section_text("71-543-G", ocr="force")
    # 'off' and 'auto' are harmless on an HTML edition.
    result = await client.get_section_text("71-543-G", ocr="off", section="a3", max_chars=300)
    assert result.format == "html" and result.ocr_pages == []


async def test_bad_arguments_are_refused(httpx_mock, engine):
    httpx_mock.add_response(url=URL, content=build_pdf([scan(), scan()]), is_reusable=True)
    with pytest.raises(InvalidInput, match="ocr must be 'auto', 'off' or 'force'"):
        await client.get_section_text(URL, ocr="always")
    with pytest.raises(InvalidInput, match="pages 1 to 2"):
        await client.get_section_text(URL, page_selector="3")
    with pytest.raises(InvalidInput, match="Entrée invalide"):
        await client.get_section_text(URL, page_selector="abc", lang="fr")
    assert engine == []


async def test_pages_past_the_pages_read_are_refused(httpx_mock, engine, monkeypatch):
    monkeypatch.setattr(client.constants, "PDF_MAX_PAGES", 2)
    httpx_mock.add_response(url=URL, content=build_pdf([scan()] * 4), is_reusable=True)
    with pytest.raises(
        InvalidInput, match="page 3 was not read: this PDF's text was taken from its first 2 pages"
    ):
        await client.get_section_text(URL, page_selector="3")


async def test_the_cached_document_is_not_changed_by_an_ocr_call(httpx_mock, engine):
    await _read(httpx_mock, [scan(), scan()])
    again = await client.get_section_text(URL, ocr="off")
    # The text extracted once is cached; the OCR text of the call before is not in it.
    assert (
        "has no text layer" in again.sections[0].text
        and "Compte rendu" not in again.sections[0].text
    )


async def test_a_second_call_reads_the_ocr_text_from_the_cache(httpx_mock, engine):
    first = await _read(httpx_mock, [scan(), scan()])
    second = await client.get_section_text(URL)
    assert engine == [1, 2]
    assert second.sections[0].text == first.sections[0].text
    assert second.ocr_pages == [1, 2]


async def test_a_page_drawn_below_200_dpi_says_so(httpx_mock, engine, monkeypatch):
    # Tabloid pages, each one image of 2448 x 3168 pixels (144 dpi) drawn over the page.
    tabloid = ImagePage(width=2448, height=3168, drawn_width=1224, drawn_height=1584)
    httpx_mock.add_response(
        url=URL, content=build_pdf([tabloid, tabloid], media=(1224, 1584)), is_reusable=True
    )
    result = await client.get_section_text(URL)
    assert "OCR (Tesseract 5.5, eng+fra, 179 dpi) read pages 1-2 of 2" in (
        result.provenance.limits or ""
    )


async def test_a_page_that_must_not_be_drawn_is_refused_naming_the_page(httpx_mock, engine):
    httpx_mock.add_response(
        url=URL, content=build_pdf([scan(), ImagePage(width=30000, height=30000)]), is_reusable=True
    )
    with pytest.raises(InvalidInput, match="page 2 declares 900,000,000 pixels"):
        await client.get_section_text(URL)
    with pytest.raises(InvalidInput, match="la page 2 déclare"):
        await client.get_section_text(URL, lang="fr")
    assert engine == []


async def test_a_run_that_stops_early_says_where_and_why(httpx_mock, monkeypatch):
    monkeypatch.setattr(ocr, "status", lambda lang="en": ocr.Status(ENGINE))

    def read(body, number, engine, dpi, wait, memory_mb):
        if number == 3:
            raise ocr._Stop("busy")
        return ocr._Recognised(f"Compte rendu page {number}", 90.0, dpi)

    monkeypatch.setattr(ocr, "_read_page", read)
    result = await _read(httpx_mock, [scan()] * 4)
    assert result.ocr_pages == [1, 2]
    limits = result.provenance.limits or ""
    assert "pages 3-4 not read, pass pages='3-4'" in limits
    assert "Stopped at page 3: another OCR job held the engine for over 10 s." in limits
    assert result.provenance.coverage == (
        "The text of pages 3-4 is not included (no text layer; 4 pages read)."
    )


async def test_get_publication_points_to_ocr_for_scanned_pages(httpx_mock):
    httpx_mock.add_response(url=URL, content=build_pdf([scan(), PROSE]))
    result = await client.get_publication(URL)
    assert (
        "statcan_reference_get_section_text(publication, section='page=N') reads scanned pages"
        in (result.provenance.limits or "")
    )


# --- scans.py on its own ---------------------------------------------------------------


async def test_ocr_that_cannot_start_in_the_time_left_says_so(monkeypatch):
    monkeypatch.setattr(ocr, "status", lambda lang="en": ocr.Status(ENGINE))
    document = client.pdf.extract(
        build_pdf([scan(), scan()]), URL, max_pages=400, max_chars=10**6, seconds=60.0
    )

    async def body() -> bytes:
        return build_pdf([scan(), scan()])

    # Extraction used 45 s of the 40 s allowed: nothing is left for OCR.
    spent = await scans.read_scans(
        document,
        URL,
        body,
        mode="auto",
        selected=None,
        scope=None,
        spent=45.0,
        lang="en",
        context=TOOL,
    )
    assert spent.ocr_pages == []
    assert "OCR did not start: reading the PDF's text used the 40 s allowed." in spent.limits[0]
    assert "has no text layer" in " ".join(
        b.text for b in spent.document.page.blocks if b.kind == "text"
    )


async def _scan_two_pages(
    monkeypatch, *, spent: float, lang: str, stop_at: int | None = None, in_page: bool = True
):
    monkeypatch.setattr(ocr, "status", lambda lang="en": ocr.Status(ENGINE))

    def read(body, number, engine, dpi, wait, memory_mb):
        if number == stop_at:
            # The budget ended while this page was being read, or (in_page False) before
            # the work on it began.
            raise ocr._Stop("time", in_page=in_page)
        return ocr._Recognised(f"Compte rendu page {number}", 90.0, dpi)

    monkeypatch.setattr(ocr, "_read_page", read)
    pdf_bytes = build_pdf([scan(), scan()])
    document = client.pdf.extract(pdf_bytes, URL, max_pages=400, max_chars=10**6, seconds=60.0)

    async def body() -> bytes:
        return pdf_bytes

    return await scans.read_scans(
        document,
        URL,
        body,
        mode="auto",
        selected=None,
        scope=None,
        spent=spent,
        lang=lang,
        context=TOOL,
    )


async def test_ocr_that_runs_out_of_time_inside_the_first_page_does_not_say_it_never_started(
    monkeypatch,
):
    # The budget ends while page 1 is being read: OCR did start, and read nothing.
    result = await _scan_two_pages(monkeypatch, spent=0.0, lang="en", stop_at=1)
    assert result.ocr_pages == []
    note = result.limits[0]
    assert "did not start" not in note
    assert "page 1" in note and "40 s" in note and "ran out" in note
    assert "pages=" in note
    # No page was read, so nothing came from the cache.
    assert result.cached is False


async def test_the_same_in_french(monkeypatch):
    result = await _scan_two_pages(monkeypatch, spent=0.0, lang="fr", stop_at=1)
    note = result.limits[0]
    assert "n'a pas démarré" not in note
    assert "page 1" in note and "40 s" in note and "pages=" in note
    assert result.cached is False


async def test_a_budget_gone_before_the_first_page_began_does_not_say_it_was_reading_it(
    monkeypatch,
):
    # The wait for the engine used the time: page 1 was never drawn or read.
    result = await _scan_two_pages(monkeypatch, spent=0.0, lang="en", stop_at=1, in_page=False)
    assert result.ocr_pages == []
    note = result.limits[0]
    assert "while it was reading" not in note and "did not start" not in note
    assert "ran out before it could start reading page 1" in note
    assert "40 s" in note and "pages=" in note
    assert result.cached is False


async def test_the_same_before_the_first_page_began_in_french(monkeypatch):
    result = await _scan_two_pages(monkeypatch, spent=0.0, lang="fr", stop_at=1, in_page=False)
    note = result.limits[0].replace(" ", " ")
    assert "pendant la lecture" not in note and "n'a pas démarré" not in note
    assert "avant qu'elle puisse commencer la lecture de la page 1" in note
    assert "40 s" in note and "pages=" in note
    assert result.cached is False


async def test_ocr_that_never_starts_for_want_of_time_is_not_a_cached_answer(monkeypatch):
    # The time was spent before OCR began (45 s of 40 s): the wording stays as it was.
    result = await _scan_two_pages(monkeypatch, spent=45.0, lang="en")
    assert "OCR did not start: reading the PDF's text used the 40 s allowed." in result.limits[0]
    assert result.cached is False
    french = await _scan_two_pages(monkeypatch, spent=45.0, lang="fr")
    assert "n'a pas démarré" in french.limits[0]


def test_page_numbers_of_a_section():
    document = client.pdf.extract(
        build_pdf([PROSE, scan(), PROSE]), URL, max_pages=400, max_chars=10**6, seconds=60.0
    )
    assert scans.section_pages(document.page.blocks) == [1, 2, 3]
    heading = next(h for h in document.page.headings if h.anchor == "page=2")
    blocks = client.pages.section_blocks(document.page, heading)
    assert scans.section_pages(blocks) == [2]


async def test_pages_read_before_come_back_from_the_cache(monkeypatch):
    monkeypatch.setattr(ocr, "status", lambda lang="en": ocr.Status(ENGINE))
    calls: list[int] = []

    def read(body, number, engine, dpi, wait, memory_mb):
        calls.append(number)
        return ocr._Recognised(f"Compte rendu page {number}", 90.0, dpi)

    monkeypatch.setattr(ocr, "_read_page", read)
    body = build_pdf([scan(), scan()])
    document = client.pdf.extract(body, URL, max_pages=400, max_chars=10**6, seconds=60.0)

    async def load() -> bytes:
        return body

    async def run() -> scans.Scanned:
        return await scans.read_scans(
            document,
            URL,
            load,
            mode="auto",
            selected=None,
            scope=None,
            spent=0.0,
            lang="en",
            context=TOOL,
        )

    first, second = await run(), await run()
    assert calls == [1, 2] and not first.cached and second.cached
