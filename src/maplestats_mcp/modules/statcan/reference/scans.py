"""OCR of the scanned pages of a PDF edition: which pages are read, what the result says.

shared/ocr.py reads pages; this module decides which ones, puts their text where the
empty page was (a copy of the cached document, never the cached one), and words what a
caller must know: which pages were read, which were not and how to ask for them, the
caps in force, and that the text is recognised from a scan and not the publisher's.
Pages are asked for in the order of the file.

`ocr="auto"` reads the pages that have no text layer and an image the size of the page
(pdf.PdfText.scanned_pages), the first DEFAULT_PAGES of them, when scans are at least
half of the pages read (or a `section` names them), or the pages named in `pages` that
have no text; `"force"` reads the pages asked for (or the first
DEFAULT_PAGES of the section) even when they have text, for a text layer that is wrong;
`"off"` reads none. Where OCR is not available, auto leaves the pages empty and says
why, and force raises.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from maplestats_mcp.modules.statcan.lang import say
from maplestats_mcp.modules.statcan.reference import constants, pages, pdf
from maplestats_mcp.shared import ocr
from maplestats_mcp.shared.errors import InvalidInput
from maplestats_mcp.shared.fr_typography import lang_error
from maplestats_mcp.shared.i18n import fr_number

_PAGE_ANCHOR = re.compile(r"page=(\d+)")


@dataclass
class Scanned:
    """The document with its OCR'd pages in place, and what to tell the caller."""

    document: pdf.PdfText
    ocr_pages: list[int] = field(default_factory=list)
    limits: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    cached: bool = True


def section_pages(blocks: list[pages.Block]) -> list[int]:
    """The PDF page numbers whose headings are among `blocks`, in order."""
    found: list[int] = []
    for block in blocks:
        match = _PAGE_ANCHOR.fullmatch(block.anchor or "") if block.kind == "heading" else None
        if match:
            found.append(int(match.group(1)))
    return found


def _where(numbers: list[int], lang: str) -> str:
    many = len(set(numbers)) > 1
    return f"{'pages' if many else 'page'} {pdf.page_ranges(numbers, lang)}"


def _sentence(text: str) -> str:
    return text[:1].upper() + text[1:]


def _marker(page: ocr.OcrPage, run: ocr.OcrRun, url: str, lang: str) -> str:
    """The line before a page's recognised text: what it is, how sure the engine was."""
    engine = f"Tesseract {run.engine.version}, {run.engine.languages}"
    confidence = page.confidence
    en_conf = f", mean word confidence {confidence:.0f}%" if confidence is not None else ""
    fr_conf = f", confiance moyenne des mots {confidence:.0f} %" if confidence is not None else ""
    cut = ""
    cut_fr = ""
    if page.truncated:
        cut = f" Cut at the {ocr.MAX_CHARS:,} character limit."
        cut_fr = f" Coupé à la limite de {fr_number(ocr.MAX_CHARS)} caractères."
    if not page.text:
        return say(
            f"[Page {page.number}: OCR ({engine}, {page.dpi} dpi) found no text on this page. "
            f"Check the page image: {url}#page={page.number}]",
            f"[Page {page.number} : la reconnaissance optique ({engine}, {page.dpi} ppp) n'a "
            f"trouvé aucun texte sur cette page. Vérifiez l'image de la page : "
            f"{url}#page={page.number}]",
            lang,
        )
    return say(
        f"[Page {page.number}: text recognised by OCR from a scan ({engine}, {page.dpi} dpi"
        f"{en_conf}), not the publisher's text layer. Check figures against the page image: "
        f"{url}#page={page.number}.{cut}]",
        f"[Page {page.number} : texte reconnu par reconnaissance optique à partir d'une "
        f"numérisation ({engine}, {page.dpi} ppp{fr_conf}), et non la couche de texte de "
        f"l'éditeur. Vérifiez les chiffres sur l'image de la page : "
        f"{url}#page={page.number}.{cut_fr}]",
        lang,
    )


def _stop_sentence(run: ocr.OcrRun, lang: str) -> str:
    """Why the run ended early, as a sentence (empty when it did not)."""
    page = run.stopped_page
    if run.stopped == "time":
        return say(
            f" Stopped at the {constants.PDF_EXTRACT_SECONDS:.0f} s time limit.",
            f" Arrêt à la limite de {constants.PDF_EXTRACT_SECONDS:.0f} s.",
            lang,
        )
    if run.stopped == "busy":
        return say(
            f" Stopped at page {page}: another OCR job held the engine for over "
            f"{ocr.BUSY_SECONDS:.0f} s.",
            f" Arrêt à la page {page} : une autre reconnaissance optique a occupé le moteur "
            f"plus de {ocr.BUSY_SECONDS:.0f} s.",
            lang,
        )
    if run.stopped == "timeout":
        return say(
            f" Stopped at page {page}: reading it took over {ocr.PAGE_SECONDS:.0f} s.",
            f" Arrêt à la page {page} : sa lecture a pris plus de {ocr.PAGE_SECONDS:.0f} s.",
            lang,
        )
    if run.stopped == "failed":
        return say(
            f" Stopped at page {page}: it could not be read.",
            f" Arrêt à la page {page} : elle n'a pas pu être lue.",
            lang,
        )
    if run.stopped == "chars":
        return say(
            f" Stopped at the {ocr.MAX_CHARS:,} character limit; the last page is cut.",
            f" Arrêt à la limite de {fr_number(ocr.MAX_CHARS)} caractères ; la dernière page est "
            "coupée.",
            lang,
        )
    return ""


def _read_note(run: ocr.OcrRun, rest: list[int], page_count: int, url: str, lang: str) -> str:
    """What was read, within which caps, what was not and how to ask for it."""
    done = [p.number for p in run.pages]
    dpis = sorted({p.dpi for p in run.pages})
    dpi = f"{dpis[0]}" if len(dpis) == 1 else f"{dpis[0]}-{dpis[-1]}"
    engine = f"Tesseract {run.engine.version}, {run.engine.languages}"
    megapixels = ocr.MAX_RENDER_PIXELS // 1_000_000
    budget = f"{constants.PDF_EXTRACT_SECONDS:.0f}"
    # The value to pass as pages=, so always in the selector's own form ("6-10").
    hint = pdf.page_ranges(rest[: ocr.DEFAULT_PAGES], "en")
    plural_done = len(done) > 1
    unread_en = f"; {_where(rest, 'en')} not read, pass pages='{hint}'" if rest else ""
    unread_fr = (
        f" ; {_where(rest, 'fr')} non {'lues' if len(rest) > 1 else 'lue'}, passez pages='{hint}'"
        if rest
        else ""
    )
    return say(
        f"OCR ({engine}, {dpi} dpi) read {_where(done, 'en')} of {page_count} (caps: "
        f"{ocr.MAX_PAGES} pages, {budget} s, {megapixels} MP a page){unread_en}."
        f"{_stop_sentence(run, 'en')} The text is recognised from a scan, not the publisher's "
        f"text layer: check figures against the page image ({url}#page=N).",
        f"Reconnaissance optique ({engine}, {dpi} ppp) : {_where(done, 'fr')} sur {page_count} "
        f"{'lues' if plural_done else 'lue'} (plafonds : {ocr.MAX_PAGES} pages, {budget} s, "
        f"{megapixels} Mpx par page){unread_fr}.{_stop_sentence(run, 'fr')} Le texte est "
        f"reconnu à partir d'une numérisation, non fourni par l'éditeur : vérifiez les chiffres "
        f"sur l'image de la page ({url}#page=N).",
        lang,
    )


def _caveat(url: str, lang: str) -> str:
    return say(
        "OCR text, not the publisher's: numbers in tables and small print are the least "
        f"reliable part. Check every figure against the page image ({url}#page=N).",
        "Texte issu de la reconnaissance optique, non fourni par l'éditeur : les chiffres des "
        "tableaux et les petits caractères sont les moins fiables. Vérifiez chaque chiffre sur "
        f"l'image de la page ({url}#page=N).",
        lang,
    )


def _candidates(
    document: pdf.PdfText,
    mode: str,
    selected: list[int] | None,
    scope: list[int] | None,
) -> list[int]:
    """The pages OCR would read: all of them, before the page caps."""
    if mode == "force":
        return selected or [n for n in (scope or range(1, document.pages_read + 1))]
    if selected:
        return [n for n in selected if n in document.no_text_pages]
    scanned = document.scanned_pages
    if scope is None and len(scanned) * 2 < document.pages_read:
        # A PDF that is mostly text with a few image pages (15-203-X: 5 charts among 277
        # pages) is not read by OCR unasked: the pages come back empty and named, and
        # pages= asks for them. Reading five chart pages first would cost seconds, and
        # their text would be searched as if it were the publisher's.
        return []
    return [n for n in scanned if scope is None or n in scope]


async def read_scans(
    document: pdf.PdfText,
    url: str,
    load_body: Callable[[], Awaitable[bytes]],
    *,
    mode: str,
    selected: list[int] | None,
    scope: list[int] | None,
    spent: float,
    lang: str,
    context: str,
) -> Scanned:
    """OCR the pages `mode`, `selected` (pages=) and `scope` (the section's pages) call for.

    `spent` is the seconds this call's extraction used, taken off the time the pages get.
    """
    result = Scanned(document)
    past = [n for n in selected or [] if n > document.pages_read]
    if past:
        raise lang_error(
            InvalidInput,
            lang,
            f"{context}: page {past[0]} was not read: this PDF's text was taken from its first "
            f"{document.pages_read} pages only.",
            f"{context} : la page {past[0]} n'a pas été lue : le texte de ce PDF n'a été pris que "
            f"sur ses {document.pages_read} premières pages.",
        )
    if mode == "off":
        if document.no_text_pages:
            result.limits.append(
                say(
                    "OCR was switched off (ocr='off'), so the pages without text stay empty.",
                    "La reconnaissance optique a été désactivée (ocr='off') : les pages sans "
                    "texte restent donc vides.",
                    lang,
                )
            )
        return result
    wanted = _candidates(document, mode, selected, scope)
    if mode == "auto" and selected:
        texted = [n for n in selected if n not in document.no_text_pages]
        if texted:
            many = len(texted) > 1
            result.limits.append(
                say(
                    f"{_sentence(_where(texted, 'en'))} {'have' if many else 'has'} a text layer, "
                    f"so OCR did not read {'them' if many else 'it'} (ocr='force' reads "
                    f"{'them' if many else 'it'} anyway).",
                    f"{'Les' if many else 'La'} {_where(texted, 'fr')} "
                    f"{'ont' if many else 'a'} une couche de texte : la reconnaissance optique "
                    f"ne {'les a pas lues' if many else 'l' + chr(39) + 'a pas lue'} "
                    f"(ocr='force' {'les lit' if many else 'la lit'} quand même).",
                    lang,
                )
            )
    if not wanted:
        if mode == "auto" and not selected and scope is None and document.scanned_pages:
            few = document.scanned_pages
            if ocr.status(lang).engine is not None:
                hint = pdf.page_ranges(few[: ocr.DEFAULT_PAGES], "en")
                result.limits.append(
                    say(
                        f"{_sentence(_where(few, 'en'))} {'are' if len(few) > 1 else 'is'} "
                        "scanned, too few among the pages with text to be read by OCR unasked: "
                        f"pass pages='{hint}' to read {'them' if len(few) > 1 else 'it'}.",
                        f"{'Les' if len(few) > 1 else 'La'} {_where(few, 'fr')} "
                        f"{'sont numérisées' if len(few) > 1 else 'est numérisée'}, trop peu "
                        "nombreuses parmi les pages avec texte pour être lues d'office par "
                        f"reconnaissance optique : passez pages='{hint}' pour "
                        f"{'les lire' if len(few) > 1 else 'la lire'}.",
                        lang,
                    )
                )
        return result
    state = ocr.status(lang)
    if state.engine is None:
        reason = state.reason or "disabled"
        why = ocr.unavailable(reason, lang)
        if mode == "force":
            raise lang_error(
                InvalidInput,
                lang,
                f"{context}: ocr='force' cannot run: {why}. Use ocr='auto' or 'off', or open "
                f"the PDF at {url}.",
                f"{context} : ocr='force' ne peut pas s'exécuter : {why}. Utilisez ocr='auto' ou "
                f"'off', ou ouvrez le PDF à {url}.",
            )
        result.limits.append(
            say(
                f"{_sentence(why)}, so the pages without text stay empty.",
                f"{_sentence(why)} : les pages sans texte restent donc vides.",
                lang,
            )
        )
        return result

    chosen = wanted if selected else wanted[: ocr.DEFAULT_PAGES]
    body = await load_body()
    run = await ocr.read_pages(
        body,
        chosen,
        engine=state.engine,
        url=url,
        lang=lang,
        seconds=max(0.0, constants.PDF_EXTRACT_SECONDS - spent),
        context=context,
    )
    texts: dict[int, list[str]] = {}
    for page in run.pages:
        paragraphs = [text for text in page.text.split("\n\n") if text.strip()]
        texts[page.number] = [_marker(page, run, url, lang), *paragraphs]
    done = [p.number for p in run.pages]
    rest = [n for n in wanted if n not in done]
    result.document = pdf.with_page_text(document, texts)
    result.ocr_pages = done
    # With no page read there is no cached answer to speak of (all() of nothing is True).
    result.cached = bool(run.pages) and all(p.cached for p in run.pages)
    if run.pages:
        result.limits.append(_read_note(run, rest, document.page_count, url, lang))
        result.caveats.append(_caveat(url, lang))
    else:
        result.limits.append(_nothing_read_note(run, lang))
    return result


def _nothing_read_note(run: ocr.OcrRun, lang: str) -> str:
    """Why OCR read no page. The run reads none only when the time ran out (stopped
    "time"): before the first page began, when reading the PDF's text had used the
    allowance (no stopped_page); before the first page's own work began, when the wait for
    the engine had (stopped_page, not stopped_in_page); or inside the first page
    (stopped_page, stopped_in_page), after its drawing or reading had begun."""
    budget = f"{constants.PDF_EXTRACT_SECONDS:.0f}"
    if run.stopped_page is None:
        return say(
            f"OCR did not start: reading the PDF's text used the {budget} s allowed. Ask again, "
            "with pages= for these pages.",
            f"La reconnaissance optique n'a pas démarré : la lecture du texte du PDF a "
            f"utilisé les {budget} s allouées. Redemandez, avec pages= pour ces pages.",
            lang,
        )
    if not run.stopped_in_page:
        return say(
            f"OCR read no page: the {budget} s allowed ran out before it could start reading "
            f"page {run.stopped_page}. Ask again, with pages= for these pages.",
            f"La reconnaissance optique n'a lu aucune page : les {budget} s allouées se sont "
            f"écoulées avant qu'elle puisse commencer la lecture de la page {run.stopped_page}. "
            "Redemandez, avec pages= pour ces pages.",
            lang,
        )
    return say(
        f"OCR started but read no page: the {budget} s allowed ran out while it was reading "
        f"page {run.stopped_page}. Ask again, with pages= for these pages.",
        f"La reconnaissance optique a démarré mais n'a lu aucune page : les {budget} s allouées "
        f"se sont écoulées pendant la lecture de la page {run.stopped_page}. Redemandez, avec "
        "pages= pour ces pages.",
        lang,
    )
