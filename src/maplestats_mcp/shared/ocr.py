"""Read the pages of a scanned PDF: PDFium draws each page, Tesseract reads the picture.

A scan has no text layer, so pypdf finds nothing on it (shared/pdf_pages.py counts
such pages). Tesseract 5 reads them: on two real scanned letters, one English and
one French, 1 and 4 characters were wrong out of 1,173 and 1,708 (measured
2026-11-16, Tesseract 5.4 on Windows with the "fast" models), about 1.1 s a page on
one core. Numbers in a shaded table were far weaker (52 to 92% of figures exactly
right depending on the settings), so every result carries "recognised from a scan,
check figures" and the caller says so.

How it is built, and why:

- optional: `pypdfium2` (the `ocr` extra) renders a page to an 8-bit gray bitmap in
  about 0.1 s, and the `tesseract` program of the system (Debian's
  tesseract-ocr, with its eng and fra data) reads it from a pipe as a PGM, with
  TSV output for the confidence of each word. Nothing is imported or started until
  a page is read, so a server without either starts as before, and `MAPLE_OCR`
  (default off) must be set to 1 on top of that;
- the page is not extracted with pypdf's `page.images`, which raises on JBIG2, JPX and
  some JPEG images (134 JBIG2 and 63 JPEG images on the sampled PBO letters): PDFium
  draws whatever the page holds;
- PDFium is not thread safe, so one slot (a semaphore) covers the render and the
  Tesseract run: one page at a time in the whole process, the next caller waiting at
  most BUSY_SECONDS for it;
- a Tesseract child that outlives its time is killed here (`run_parse` cancels the
  await, not the thread or the process): PAGE_SECONDS a page, and the loop over the
  pages draws from one budget the caller gives it (the reference reader gives its
  PDF_EXTRACT_SECONDS less what extraction already used), so the pages read are
  whatever fits. The budget also bounds the page being read: the child is killed at
  whichever comes first, PAGE_SECONDS or what is left of the budget (the page render,
  which PDFium cannot interrupt, is the one step that can still run past it);
- where the operating system allows it (Linux), the child's address space is capped
  at `MAPLE_OCR_MEMORY_MB` by a one-line Python launcher that sets RLIMIT_AS and
  execs tesseract (a `preexec_fn` is unsafe in a process with threads);
- a page's size is bounded before anything is rendered, because the byte cap of a
  download bounds nothing here: a 107 KB file that declares one 30,000 x 30,000
  pixel image used 197 MB to render at 200 dpi (PDFium, measured 2026-11-16). A
  page whose declared images pass MAX_DECLARED_PIXELS is refused, and one that
  would pass MAX_RENDER_PIXELS at 200 dpi is drawn at a lower resolution, down to
  MIN_DPI, then refused;
- each page's text is cached with a hash of the document's bytes, its resolution and
  the engine's version, inside the shared response cache's byte budget (about 3 KB a
  page). The URL alone is not the document: a file replaced at the same URL within the
  cache's day would have been served the old file's text.

None of these caps raises an existing one.
"""

from __future__ import annotations

import contextvars
import hashlib
import importlib
import importlib.util
import io
import logging
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pypdf import PdfReader

from maplestats_mcp import config
from maplestats_mcp.shared import cache, pdf_pages
from maplestats_mcp.shared.errors import InvalidInput, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.executor import check_deadline, run_parse
from maplestats_mcp.shared.fr_typography import lang_error
from maplestats_mcp.shared.i18n import fr_number, pick

logger = logging.getLogger("maplestats_mcp.ocr")

# --- Caps. All are additions to the reference reader's, none replaces one. ------------
MAX_PAGES = 10  # pages one call reads, however many are asked for
DEFAULT_PAGES = 5  # pages read when the caller names none
RENDER_DPI = 200
MIN_DPI = 100
MAX_RENDER_PIXELS = 12_000_000  # a letter page at 300 dpi is 8.4 million
MAX_DECLARED_PIXELS = 60_000_000  # pixels the images of one page may declare
PAGE_SECONDS = 15.0  # a Tesseract child is killed after this
BUSY_SECONDS = 10.0  # the longest a call waits for the one OCR slot
MAX_CHARS = 60_000  # characters of OCR text one call returns (1,400 to 2,800 a page)
CACHE_TTL_SECONDS = 24 * 60 * 60
PROBE_SECONDS = 15.0

# Languages asked of Tesseract for a call in each language, the call's own first.
_LANGUAGES = {"en": ("eng", "fra"), "fr": ("fra", "eng")}
# What the child may see of the environment: what the program and the OS need, and
# where the language data are (no tokens, no HOME).
_ENV_KEYS = ("PATH", "SYSTEMROOT", "SystemRoot", "WINDIR", "TEMP", "TMP", "TMPDIR", "LANG")
_TESSDATA = "TESSDATA_PREFIX"
# Sets the address-space cap, then replaces itself with tesseract (same process id, so
# kill() reaches the program). A failure to set the cap is not fatal.
_LIMIT_PROGRAM = (
    "import os, resource, sys\n"
    "limit = int(sys.argv[1])\n"
    "try:\n"
    "    resource.setrlimit(resource.RLIMIT_AS, (limit, limit))\n"
    "except (ValueError, OSError):\n"
    "    pass\n"
    "os.execv(sys.argv[2], sys.argv[2:])\n"
)

# RLIMIT_AS is enforced on Linux; macOS and Windows keep the time and page caps only.
_LINUX = sys.platform.startswith("linux")

Reason = Literal["disabled", "pypdfium2", "tesseract", "languages"]
Stopped = Literal["time", "busy", "timeout", "failed", "chars"]


@dataclass(frozen=True)
class Engine:
    path: str
    version: str  # "5.4"
    languages: str  # "eng+fra"


@dataclass(frozen=True)
class Status:
    """`engine` when OCR can run here, else `reason` it cannot."""

    engine: Engine | None
    reason: Reason | None = None


@dataclass
class OcrPage:
    number: int  # 1-based
    text: str
    confidence: float | None  # mean of Tesseract's word confidences, 0 to 100
    dpi: int
    seconds: float  # 0 for a page read from the cache
    cached: bool
    truncated: bool = False  # cut at MAX_CHARS


@dataclass
class OcrRun:
    engine: Engine
    pages: list[OcrPage]
    unread: list[int]  # asked for, within the page cap, not reached
    over_cap: list[int]  # asked for beyond MAX_PAGES
    stopped: Stopped | None = None
    # The page a busy, timeout or failed stop happened at, or the page the budget ran out
    # at (a "time" stop between pages leaves it None).
    stopped_page: int | None = None
    # Whether the stop came after the work on stopped_page had begun (it was being drawn or
    # read), not before (the wait for the engine, or no time left once it was free): a
    # "time" stop says "while it was reading page N" only when this is True.
    stopped_in_page: bool = False
    seconds: float = 0.0


@dataclass(frozen=True)
class _Recognised:
    text: str
    confidence: float | None
    dpi: int


@dataclass(frozen=True)
class _Plan:
    number: int
    dpi: int


class _Stop(Exception):
    """A worker's report that the page was not read: kind, and the program's own words.

    `in_page` is False when the stop came before any work on the page began (waiting for
    the engine, or the budget gone once it was free), True once it was being drawn or read.
    """

    def __init__(self, kind: Stopped, detail: str = "", *, in_page: bool = True) -> None:
        super().__init__(kind)
        self.kind: Stopped = kind
        self.detail = detail
        self.in_page = in_page


# One page at a time, render and read: PDFium is not thread safe, and one Tesseract
# child is about 125 MB (four at once would break a 512 MB host).
_slot = threading.Semaphore(1)
_probed: dict[str, tuple[str, frozenset[str]]] = {}
_probe_lock = threading.Lock()

# When the caller's time budget ends (a time.monotonic() value). read_pages sets it
# around each page's read and run_parse copies the context into the worker thread, so
# the page being read stops at the budget, not only at PAGE_SECONDS. Unset: PAGE_SECONDS
# alone, as when _read_page is called directly.
_budget_end: contextvars.ContextVar[float | None] = contextvars.ContextVar(
    "ocr_budget_end", default=None
)


def reset() -> None:
    """Forget what was found about the installed Tesseract (tests change it)."""
    with _probe_lock:
        _probed.clear()


# --- Is OCR available here? -----------------------------------------------------------


def _child_env() -> dict[str, str]:
    env = {key: os.environ[key] for key in (*_ENV_KEYS, _TESSDATA) if key in os.environ}
    # One thread: a predictable share of a small host's CPU and memory, and the same
    # text on every run (checked 3 times, one thread and the default).
    env["OMP_THREAD_LIMIT"] = "1"
    return env


def _run_text(command: list[str]) -> str | None:
    """Output (both streams) of a quick Tesseract query, or None when it does not run."""
    try:
        done = subprocess.run(
            command,
            capture_output=True,
            timeout=PROBE_SECONDS,
            env=_child_env(),
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.decode("utf-8", "replace") + "\n" + done.stderr.decode("utf-8", "replace")


def _probe(path: str) -> tuple[str, frozenset[str]] | None:
    """(version "5.4", language codes with data) of the tesseract program, once per process."""
    with _probe_lock:
        found = _probed.get(path)
    if found is not None:
        return found
    version_text = _run_text([path, "--version"])
    languages_text = _run_text([path, "--list-langs"])
    if version_text is None or languages_text is None:
        return None
    match = re.search(r"tesseract\s+v?(\d+)\.(\d+)", version_text, re.IGNORECASE)
    languages = frozenset(
        line.strip()
        for line in languages_text.splitlines()
        if re.fullmatch(r"[A-Za-z_]{3,12}", line.strip())
    )
    found = (f"{match.group(1)}.{match.group(2)}" if match else "?", languages)
    with _probe_lock:
        _probed[path] = found
    return found


def status(lang: str = "en") -> Status:
    """Whether a page can be read here: MAPLE_OCR on, pypdfium2 installed, tesseract
    found with data for English or French. The first reason it cannot, else the engine."""
    if not config.get_ocr_enabled():
        return Status(None, "disabled")
    if importlib.util.find_spec("pypdfium2") is None:
        return Status(None, "pypdfium2")
    path = shutil.which("tesseract")
    probe = _probe(path) if path else None
    if path is None or probe is None:
        return Status(None, "tesseract")
    wanted = _LANGUAGES["fr" if lang.lower().startswith("fr") else "en"]
    have = [code for code in wanted if code in probe[1]]
    if not have:
        return Status(None, "languages")
    return Status(Engine(path, probe[0], "+".join(have)))


def unavailable(reason: Reason, lang: str = "en") -> str:
    """Why OCR cannot run here, as a clause that completes a sentence."""
    if reason == "disabled":
        return pick(
            lang,
            "OCR is not enabled on this server (it is switched on with MAPLE_OCR=1)",
            "la reconnaissance optique n'est pas activée sur ce serveur (elle s'active avec "
            "MAPLE_OCR=1)",
        )
    if reason == "pypdfium2":
        return pick(
            lang,
            "OCR is enabled but the 'ocr' extra (pypdfium2) is not installed here",
            "la reconnaissance optique est activée, mais l'extra « ocr » (pypdfium2) n'est pas "
            "installé ici",
        )
    if reason == "tesseract":
        return pick(
            lang,
            "OCR is enabled but the tesseract program is not installed here",
            "la reconnaissance optique est activée, mais le programme tesseract n'est pas "
            "installé ici",
        )
    return pick(
        lang,
        "OCR is enabled but tesseract has no English or French language data (eng, fra) here",
        "la reconnaissance optique est activée, mais tesseract n'a ici aucune donnée de langue "
        "anglaise ou française (eng, fra)",
    )


# --- Page selectors ---------------------------------------------------------------------

_SELECTOR_PREFIX = re.compile(r"^\s*(?:pages?|pp?)?[\s.=]*", re.IGNORECASE)
_SELECTOR_PART = re.compile(r"(\d{1,6})(?:-(\d{1,6}))?")


def parse_pages(spec: str, page_count: int, lang: str = "en", context: str = "ocr") -> list[int]:
    """'6-10', '1,3,5-7', 'page=3' or '3' as sorted page numbers, each within the file.

    InvalidInput, naming the valid range, for text that is not a page list or a page
    outside the file.
    """

    def invalid(en: str, fr: str) -> InvalidInput:
        return lang_error(InvalidInput, lang, f"{context}: {en}", f"{context} : {fr}")

    text = _SELECTOR_PREFIX.sub("", spec.replace("–", "-"))
    text = re.sub(r"\s*-\s*", "-", text.strip())
    parts = [part for part in re.split(r"[,;\s]+", text) if part]
    if not parts:
        raise invalid(
            f"pages is empty: give page numbers such as '3', '6-10' or '1,3,5-7' (the PDF has "
            f"{page_count} pages).",
            f"pages est vide : donnez des numéros de page comme '3', '6-10' ou '1,3,5-7' (le "
            f"PDF compte {page_count} pages).",
        )
    numbers: set[int] = set()
    for part in parts:
        match = _SELECTOR_PART.fullmatch(part)
        if match is None:
            raise invalid(
                f"{part!r} in pages is not a page number or a range such as '6-10'.",
                f"{part!r} dans pages n'est ni un numéro de page ni un intervalle comme '6-10'.",
            )
        first = int(match.group(1))
        last = int(match.group(2) or first)
        if first < 1 or last < first or last > page_count:
            raise invalid(
                f"pages {part!r} is outside the file: it has pages 1 to {page_count}.",
                f"pages {part!r} est hors du fichier : il a les pages 1 à {page_count}.",
            )
        numbers.update(range(first, last + 1))
    return sorted(numbers)


# --- Reading a page (worker thread) ------------------------------------------------------


def _pixels(width_pt: float, height_pt: float, dpi: int) -> int:
    return math.ceil(width_pt * dpi / 72) * math.ceil(height_pt * dpi / 72)


def fit_dpi(width_pt: float, height_pt: float) -> int | None:
    """RENDER_DPI, or the highest lower resolution that keeps the page within
    MAX_RENDER_PIXELS; None when even MIN_DPI would not."""
    if width_pt <= 0 or height_pt <= 0:
        return None
    dpi = RENDER_DPI
    if _pixels(width_pt, height_pt, dpi) > MAX_RENDER_PIXELS:
        dpi = math.floor(72 * math.sqrt(MAX_RENDER_PIXELS / (width_pt * height_pt)))
        while dpi >= MIN_DPI and _pixels(width_pt, height_pt, dpi) > MAX_RENDER_PIXELS:
            dpi -= 1
    return dpi if dpi >= MIN_DPI else None


def _plan(body: bytes, numbers: Sequence[int], url: str, lang: str, context: str) -> list[_Plan]:
    """The resolution each page is drawn at, or InvalidInput naming the first page that
    must not be drawn. Reads sizes only (pypdf), never an image or a render."""
    try:
        reader = PdfReader(io.BytesIO(body))
        count = len(reader.pages)
    except Exception as exc:
        raise lang_error(
            UpstreamError,
            lang,
            f"{context}: {url} could not be opened for OCR ({type(exc).__name__}).",
            f"{context} : {url} n'a pas pu être ouvert pour la reconnaissance optique "
            f"({type(exc).__name__}).",
        ) from exc
    plans: list[_Plan] = []
    for number in numbers:
        if not 1 <= number <= count:
            raise lang_error(
                InvalidInput,
                lang,
                f"{context}: page {number} is outside the file, which has {count} pages.",
                f"{context} : la page {number} est hors du fichier, qui compte {count} pages.",
            )
        page = reader.pages[number - 1]
        declared = pdf_pages.declared_image_pixels(page)
        if declared > MAX_DECLARED_PIXELS:
            raise lang_error(
                InvalidInput,
                lang,
                f"{context}: page {number} declares {declared:,} pixels of images (over "
                f"{MAX_DECLARED_PIXELS:,}), so it is not drawn for OCR. Leave it out of pages= "
                f"or open the PDF at {url}#page={number}.",
                f"{context} : la page {number} déclare {fr_number(declared)} pixels d'images (plus "
                f"de {fr_number(MAX_DECLARED_PIXELS)}) ; elle n'est donc pas dessinée pour la "
                f"reconnaissance optique. Retirez-la de pages= ou ouvrez le PDF à {url}#page={number}.",
            )
        width, height = float(page.mediabox.width), float(page.mediabox.height)
        dpi = fit_dpi(width, height)
        if dpi is None:
            raise lang_error(
                InvalidInput,
                lang,
                f"{context}: page {number} is {width / 72:.0f} x {height / 72:.0f} inches: even "
                f"at {MIN_DPI} dpi it would pass {MAX_RENDER_PIXELS:,} pixels, so it is not "
                f"drawn for OCR. Leave it out of pages= or open the PDF at {url}#page={number}.",
                f"{context} : la page {number} fait {width / 72:.0f} x {height / 72:.0f} pouces : "
                f"même à {MIN_DPI} ppp elle dépasserait {fr_number(MAX_RENDER_PIXELS)} pixels ; "
                f"elle n'est donc pas dessinée pour la reconnaissance optique. Retirez-la de "
                f"pages= ou ouvrez le PDF à {url}#page={number}.",
            )
        plans.append(_Plan(number, dpi))
    return plans


def _render_pgm(body: bytes, number: int, dpi: int) -> bytes:
    """The page as a binary PGM (8-bit gray), drawn by PDFium."""
    # Imported here, by name: the extra may be missing, and a type checker without it
    # installed must not fail on the import.
    pdfium: Any = importlib.import_module("pypdfium2")
    try:
        document = pdfium.PdfDocument(body)
    except pdfium.PdfiumError as exc:
        raise _Stop("failed", f"PDFium could not open the file ({exc})") from exc
    try:
        page = document[number - 1]
        bitmap = page.render(scale=dpi / 72, grayscale=True)
        width, height, stride = bitmap.width, bitmap.height, bitmap.stride
        buffer = bytes(bitmap.buffer)
    except pdfium.PdfiumError as exc:
        raise _Stop("failed", f"PDFium could not draw the page ({exc})") from exc
    finally:
        document.close()
    rows = (
        buffer
        if stride == width
        else b"".join(buffer[y * stride : y * stride + width] for y in range(height))
    )
    return b"P5\n%d %d\n255\n" % (width, height) + rows


def _command(engine: Engine, dpi: int, memory_mb: int) -> list[str]:
    command = [
        engine.path,
        "stdin",
        "stdout",
        "-l",
        engine.languages,
        "--oem",
        "1",
        "--psm",
        "3",
        "--dpi",
        str(dpi),
        "tsv",
    ]
    if memory_mb > 0 and _LINUX:
        limit = memory_mb * 1024 * 1024
        return [sys.executable, "-S", "-I", "-c", _LIMIT_PROGRAM, str(limit), *command]
    return command


def _tesseract(
    pgm: bytes, engine: Engine, dpi: int, memory_mb: int, seconds: float | None = None
) -> str:
    """Tesseract's TSV for the image, from a child killed at PAGE_SECONDS or after
    `seconds` (what is left of the caller's budget), whichever is less.

    A child killed at the budget is `_Stop("time")`, not a page over PAGE_SECONDS
    (`_Stop("timeout")`): the page may be fine, the call has no time left for it.
    """
    limit = PAGE_SECONDS if seconds is None else min(PAGE_SECONDS, seconds)
    try:
        child = subprocess.Popen(
            _command(engine, dpi, memory_mb),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_child_env(),
        )
    except OSError as exc:
        raise _Stop("failed", f"tesseract did not start ({exc})") from exc
    try:
        out, err = child.communicate(pgm, timeout=limit)
    except subprocess.TimeoutExpired:
        child.kill()
        child.communicate()  # reaps the child and closes its pipes
        raise _Stop("timeout" if limit >= PAGE_SECONDS else "time") from None
    except BaseException:
        child.kill()
        child.communicate()
        raise
    if child.returncode != 0:
        words = err.decode("utf-8", "replace").strip().splitlines()
        detail = f"exit status {child.returncode}" + (f": {words[-1][:200]}" if words else "")
        raise _Stop("failed", detail)
    return out.decode("utf-8", "replace")


def parse_tsv(tsv: str) -> tuple[str, float | None]:
    """(text, mean word confidence) of Tesseract's TSV: words joined into lines, lines
    into paragraphs (a blank line between them), in the order Tesseract read them.

    Only words (level 5) with text count; the confidence is the mean over those
    Tesseract scored (0 to 100), None when it scored none.
    """
    paragraphs: dict[tuple[str, str], dict[str, list[str]]] = {}
    scores: list[float] = []
    for row in tsv.splitlines()[1:]:
        cells = row.split("\t")
        if len(cells) < 12 or cells[0] != "5":
            continue
        word = "\t".join(cells[11:]).strip()
        if not word:
            continue
        try:
            score = float(cells[10])
        except ValueError:
            score = -1.0
        if score >= 0:
            scores.append(score)
        lines = paragraphs.setdefault((cells[2], cells[3]), {})
        lines.setdefault(cells[4], []).append(word)
    text = "\n\n".join(
        "\n".join(" ".join(words) for words in lines.values()) for lines in paragraphs.values()
    )
    confidence = round(sum(scores) / len(scores), 1) if scores else None
    return text, confidence


def _budget_left(*, in_page: bool = True) -> float | None:
    """Seconds left of the caller's budget (see _budget_end); None when it set none.
    `_Stop("time")` when none is left, with `in_page` saying whether work on the page had
    begun."""
    end = _budget_end.get()
    if end is None:
        return None
    left = end - time.monotonic()
    if left <= 0:
        raise _Stop("time", in_page=in_page)
    return left


def _digest(body: bytes) -> str:
    """The first 32 hex characters of the file's SHA-256: the cache key's document part."""
    return hashlib.sha256(body).hexdigest()[:32]


def _read_page(
    body: bytes, number: int, engine: Engine, dpi: int, wait: float, memory_mb: int
) -> _Recognised:
    """Render and read one page, holding the one OCR slot. Runs in the parse pool."""
    if not _slot.acquire(timeout=max(0.0, wait)):
        raise _Stop("busy", in_page=False)
    try:
        check_deadline()
        # The wait for the slot above used part of the budget: no render for a page
        # there is no time left to read. The page has not been started, so the stop says so.
        _budget_left(in_page=False)
        pgm = _render_pgm(body, number, dpi)
        check_deadline()
        text, confidence = parse_tsv(_tesseract(pgm, engine, dpi, memory_mb, _budget_left()))
    finally:
        _slot.release()
    return _Recognised(text, confidence, dpi)


# --- Reading several pages (event loop) ---------------------------------------------------


def _stopped_error(
    run_kind: Stopped, number: int, detail: str, lang: str, context: str
) -> Exception:
    if run_kind == "busy":
        return lang_error(
            UpstreamUnavailable,
            lang,
            f"{context}: another OCR job has held the engine for over {BUSY_SECONDS:.0f} s "
            "(one page is read at a time on this server). Try again shortly.",
            f"{context} : une autre reconnaissance optique occupe le moteur depuis plus de "
            f"{BUSY_SECONDS:.0f} s (une page à la fois sur ce serveur). Réessayez sous peu.",
        )
    if run_kind == "timeout":
        return lang_error(
            UpstreamError,
            lang,
            f"{context}: reading page {number} took over {PAGE_SECONDS:.0f} s and was stopped. "
            "Read the other pages with pages=, or open the PDF at the page.",
            f"{context} : la lecture de la page {number} a pris plus de {PAGE_SECONDS:.0f} s et a "
            "été arrêtée. Lisez les autres pages avec pages=, ou ouvrez le PDF à cette page.",
        )
    hint = ""
    hint_fr = ""
    if "exit status -" in detail or "bad_alloc" in detail:
        hint = f" (the child is limited to MAPLE_OCR_MEMORY_MB={config.get_ocr_memory_mb()})"
        hint_fr = f" (l'enfant est limité à MAPLE_OCR_MEMORY_MB={config.get_ocr_memory_mb()})"
    return lang_error(
        UpstreamError,
        lang,
        f"{context}: page {number} could not be read by OCR: {detail}{hint}.",
        f"{context} : la page {number} n'a pas pu être lue par reconnaissance optique : "
        f"{detail}{hint_fr}.",
    )


async def _read_cached(
    key: str,
    body: bytes,
    plan: _Plan,
    engine: Engine,
    memory_mb: int,
    started: float,
    seconds: float,
) -> tuple[_Recognised, bool]:
    """One page's text and whether it came from the cache, read within the budget that
    began at `started` and lasts `seconds`.

    Calls reading the same page at once share one read (cache.cached_fetch), and a call
    that joined another's read is handed its outcome, including a stop that was about
    the other call: its budget ending ("time") or its own wait for the engine ("busy",
    which is cut to that call's remaining budget). Such a stop is not this call's, so it
    reads again with its own budget while any is left. A "timeout" or a "failed" is about
    the page, and is shared as it is: no second try.
    """
    while True:
        remaining = seconds - (time.monotonic() - started)
        ran = False

        async def fetch(wait: float = min(BUSY_SECONDS, remaining)) -> _Recognised:
            nonlocal ran
            ran = True
            token = _budget_end.set(started + seconds)
            try:
                return await run_parse(
                    _read_page, body, plan.number, engine, plan.dpi, wait, memory_mb
                )
            finally:
                _budget_end.reset(token)

        try:
            return await cache.cached_fetch(key, CACHE_TTL_SECONDS, fetch)
        except _Stop as stop:
            if ran or stop.kind not in ("time", "busy"):
                raise
            if seconds - (time.monotonic() - started) <= 0:
                # Past this call's own budget too: the time limit, whatever the other
                # call's stop was called. This call never began the page.
                raise _Stop("time", in_page=False) from None


async def read_pages(
    body: bytes,
    numbers: Sequence[int],
    *,
    engine: Engine,
    url: str,
    lang: str,
    seconds: float,
    context: str,
) -> OcrRun:
    """Read `numbers` (1-based pages of `body`) in order, within the caps.

    At most MAX_PAGES pages and `seconds` of work (the wait for the OCR slot included),
    then the pages not reached are returned in `unread` with `stopped` saying why: a
    cap that ends the run is not an error, whether the budget ends between two pages, before
    a page's work begins (the wait for the engine used it) or in the middle of a page (that
    page is then unread, with no pages read if it was the first; `stopped_in_page` says
    which). A page that must not be drawn raises InvalidInput before any page is read; a
    first page that cannot be read at all (the engine busy, a crash, a page over
    PAGE_SECONDS) raises too, since there is nothing to return.
    """
    started = time.monotonic()
    ordered = sorted(set(numbers))
    todo, over_cap = ordered[:MAX_PAGES], ordered[MAX_PAGES:]
    plans = await run_parse(_plan, body, todo, url, lang, context)
    memory_mb = config.get_ocr_memory_mb()
    run = OcrRun(engine, [], [], over_cap)
    total = 0
    # The document's identity for the cache: the URL can serve another file tomorrow. Hashed
    # in the pool: a PDF of many MB would hold the event loop for the length of the hash.
    digest = await run_parse(_digest, body)
    for index, plan in enumerate(plans):
        remaining = seconds - (time.monotonic() - started)
        if remaining <= 0:
            run.stopped = "time"
            run.unread = [p.number for p in plans[index:]]
            break
        began = time.monotonic()
        key = f"ocr:{url}:{digest}:{plan.number}:{plan.dpi}:{engine.version}:{engine.languages}"
        try:
            read, cached = await _read_cached(key, body, plan, engine, memory_mb, started, seconds)
        except _Stop as stop:
            # The budget ending inside a page is a cap that ends the run, like the one
            # checked above between pages, so it is not an error even for the first page.
            if not run.pages and stop.kind != "time":
                raise _stopped_error(stop.kind, plan.number, stop.detail, lang, context) from None
            run.stopped, run.stopped_page = stop.kind, plan.number
            run.stopped_in_page = stop.in_page
            run.unread = [p.number for p in plans[index:]]
            break
        text, truncated = read.text, False
        if total + len(text) > MAX_CHARS:
            text, truncated = _cut(text, MAX_CHARS - total), True
        total += len(text)
        run.pages.append(
            OcrPage(
                plan.number,
                text,
                read.confidence,
                read.dpi,
                0.0 if cached else time.monotonic() - began,
                cached,
                truncated,
            )
        )
        if truncated:
            run.stopped = "chars"
            run.unread = [p.number for p in plans[index + 1 :]]
            break
    run.seconds = time.monotonic() - started
    return run


def _cut(text: str, limit: int) -> str:
    """`text` to at most `limit` characters, at the end of a line when one is near."""
    if len(text) <= limit:
        return text
    window = text[: max(0, limit)]
    newline = window.rfind("\n")
    return window[: newline if newline > limit // 2 else len(window)].rstrip()
