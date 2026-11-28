"""Review fixes in shared/ocr.py: the page cache follows the document, and the caller's
time budget bounds the page being read."""

from __future__ import annotations

import asyncio
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

from maplestats_mcp.shared import ocr
from tests.pdf_builder import build_pdf, scan

ENGINE = ocr.Engine("/usr/bin/tesseract", "5.5", "eng+fra")
URL = "https://www150.statcan.gc.ca/n1/pub/15-203-x/scan-eng.pdf"
PGM = b"P5\n1 1\n255\n\x00"


@pytest.fixture(autouse=True)
def _forget_the_installed_engine(monkeypatch):
    monkeypatch.delenv("MAPLE_OCR", raising=False)
    monkeypatch.delenv("MAPLE_OCR_MEMORY_MB", raising=False)
    ocr.reset()
    yield
    ocr.reset()


async def _read(body: bytes, numbers: list[int], seconds: float = 40.0) -> ocr.OcrRun:
    return await ocr.read_pages(
        body, numbers, engine=ENGINE, url=URL, lang="en", seconds=seconds, context="ctx"
    )


# --- the cache follows the document, not only its URL ------------------------------------


async def test_a_document_replaced_at_the_same_url_is_read_again(monkeypatch):
    reads: list[int] = []

    def read(body, number, engine, dpi, wait, memory_mb):
        reads.append(len(body))
        return ocr._Recognised(f"text of a {len(body)} byte file", 92.0, dpi)

    monkeypatch.setattr(ocr, "_read_page", read)
    old, new = build_pdf([scan()]), build_pdf([scan(), scan()])
    assert old != new
    first = await _read(old, [1])
    replaced = await _read(new, [1])
    # Page 1 of the new file is read, not served from the old file's entry.
    assert reads == [len(old), len(new)]
    assert replaced.pages[0].text != first.pages[0].text
    assert not replaced.pages[0].cached
    # The same bytes at the same URL still come from the cache.
    again = await _read(new, [1])
    assert again.pages[0].cached and reads == [len(old), len(new)]


# --- the caller's budget bounds a page, not only the gaps between pages ------------------


def _fake_child(tmp_path: Path, body: str) -> list[str]:
    script = tmp_path / "fake_tesseract.py"
    script.write_text(textwrap.dedent(body), encoding="utf-8")
    return [sys.executable, str(script)]


def _slow_child(monkeypatch, tmp_path: Path) -> list[subprocess.Popen]:
    command = _fake_child(tmp_path, "import time\ntime.sleep(60)\n")
    monkeypatch.setattr(ocr, "_command", lambda engine, dpi, memory_mb: command)
    created: list[subprocess.Popen] = []
    real = subprocess.Popen

    def spy(*args, **kwargs):
        child = real(*args, **kwargs)
        created.append(child)
        return child

    monkeypatch.setattr(ocr.subprocess, "Popen", spy)
    return created


def test_tesseract_stops_at_the_seconds_it_is_given_and_says_it_was_the_budget(
    monkeypatch, tmp_path
):
    created = _slow_child(monkeypatch, tmp_path)
    monkeypatch.setattr(ocr, "PAGE_SECONDS", 30.0)
    started = time.monotonic()
    with pytest.raises(ocr._Stop) as stop:
        ocr._tesseract(PGM, ENGINE, 200, 0, 0.5)
    # "time" is the caller's budget; "timeout" stays for a page over PAGE_SECONDS.
    assert stop.value.kind == "time"
    assert time.monotonic() - started < 10
    assert len(created) == 1 and created[0].poll() is not None


async def test_a_page_running_past_the_budget_is_stopped_and_not_an_error(monkeypatch, tmp_path):
    # PAGE_SECONDS alone would let this child run 6 s; the call has half a second.
    created = _slow_child(monkeypatch, tmp_path)
    monkeypatch.setattr(ocr, "PAGE_SECONDS", 6.0)
    monkeypatch.setattr(ocr, "_render_pgm", lambda body, number, dpi: PGM)
    started = time.monotonic()
    run = await _read(build_pdf([scan(), scan()]), [1, 2], seconds=0.5)
    elapsed = time.monotonic() - started
    assert run.pages == [] and run.stopped == "time" and run.unread == [1, 2]
    # The child was running: the stop is inside page 1, not before it.
    assert run.stopped_page == 1 and run.stopped_in_page is True
    assert elapsed < 5.5, f"the page ran {elapsed:.1f} s on a 0.5 s budget"
    assert len(created) == 1 and created[0].poll() is not None


async def test_a_budget_gone_once_the_engine_is_free_stops_before_the_page_began(monkeypatch):
    # The engine is free only after the budget has gone (the wait for it used the time): the
    # page is not drawn, and the stop says the work on it never began, which the note for a
    # call that read nothing needs to word ("before it could start", not "while reading").
    class _LateSlot:
        def acquire(self, timeout: float) -> bool:
            time.sleep(0.4)
            return True

        def release(self) -> None:
            pass

    drawn: list[int] = []

    def render(body, number, dpi):
        drawn.append(number)
        return PGM

    monkeypatch.setattr(ocr, "_slot", _LateSlot())
    monkeypatch.setattr(ocr, "_render_pgm", render)
    run = await _read(build_pdf([scan(), scan()]), [1, 2], seconds=0.3)
    assert run.pages == [] and run.stopped == "time" and run.unread == [1, 2]
    assert run.stopped_page == 1 and run.stopped_in_page is False
    assert drawn == []


async def test_a_budget_spent_mid_run_keeps_the_pages_read_and_names_the_rest(monkeypatch):
    def read(body, number, engine, dpi, wait, memory_mb):
        if number == 2:
            raise ocr._Stop("time")
        return ocr._Recognised(f"Page text {number}", 92.0, dpi)

    monkeypatch.setattr(ocr, "_read_page", read)
    run = await _read(build_pdf([scan()] * 3), [1, 2, 3])
    assert [p.number for p in run.pages] == [1]
    assert run.stopped == "time" and run.unread == [2, 3]


# --- a call that joins another call's read is not stopped by that call's budget ------------


async def _two_calls(monkeypatch, outcome: str, owner_seconds: float, waiter_seconds: float):
    """Two calls for page 1 of one document: the first starts the read, the second joins
    it while it runs. The read lasts 0.6 s; `outcome` is what it ends in when the first
    call's budget is spent ("budget"), or always ("failed")."""
    reads: list[float] = []
    started = threading.Event()

    def read(body, number, engine, dpi, wait, memory_mb):
        reads.append(time.monotonic())
        started.set()
        time.sleep(0.6)
        end = ocr._budget_end.get()
        if outcome == "failed":
            raise ocr._Stop("failed", "boom")
        if end is not None and time.monotonic() > end:
            raise ocr._Stop("time")
        return ocr._Recognised("Page text", 92.0, dpi)

    monkeypatch.setattr(ocr, "_read_page", read)
    body = build_pdf([scan()])
    owner = asyncio.create_task(_read(body, [1], seconds=owner_seconds))
    # The second call starts once the first is inside its read, so it joins that read.
    await asyncio.to_thread(started.wait, 10)
    waiter = asyncio.create_task(_read(body, [1], seconds=waiter_seconds))
    results = await asyncio.gather(owner, waiter, return_exceptions=True)
    return results, reads


async def test_a_call_with_time_left_is_not_stopped_by_the_budget_of_the_call_it_joined(
    monkeypatch,
):
    (owner, waiter), reads = await _two_calls(monkeypatch, "budget", 0.3, 30.0)
    # The first call ran out of time inside the page...
    assert isinstance(owner, ocr.OcrRun) and owner.pages == [] and owner.stopped == "time"
    # ...the second had 30 s: it reads the page itself instead of inheriting that stop.
    assert isinstance(waiter, ocr.OcrRun)
    assert [p.text for p in waiter.pages] == ["Page text"] and waiter.stopped is None
    assert len(reads) == 2


async def test_a_stop_about_the_page_itself_is_still_shared(monkeypatch):
    (owner, waiter), reads = await _two_calls(monkeypatch, "failed", 30.0, 30.0)
    # A page that cannot be read fails both calls from one attempt: no second try.
    assert isinstance(owner, Exception) and isinstance(waiter, Exception)
    assert "page 1 could not be read by OCR: boom" in str(waiter)
    assert len(reads) == 1


async def test_a_waiter_whose_own_budget_is_spent_stops_at_the_time_limit(monkeypatch):
    # Both calls have little time: the joined read ends in the owner's stop, and the
    # waiter, past its own budget too, reports the time limit, not an error.
    (owner, waiter), reads = await _two_calls(monkeypatch, "budget", 0.3, 0.4)
    assert isinstance(owner, ocr.OcrRun) and owner.stopped == "time"
    assert isinstance(waiter, ocr.OcrRun) and waiter.pages == [] and waiter.stopped == "time"
    assert len(reads) == 1


# --- the document's hash is not computed on the event loop -------------------------------


async def test_the_cache_key_hashes_the_file_off_the_event_loop_and_keeps_its_form(monkeypatch):
    import hashlib

    keys: list[str] = []
    hashed_on: list[int] = []
    real_sha256 = hashlib.sha256
    body = build_pdf([scan()])

    def spy(data=b"", **kwargs):
        if data is body:
            hashed_on.append(threading.get_ident())
        return real_sha256(data, **kwargs)

    async def fetch(key, ttl, fetcher):
        keys.append(key)
        return ocr._Recognised("Page text", 92.0, 200), False

    monkeypatch.setattr(ocr.hashlib, "sha256", spy)
    monkeypatch.setattr(ocr.cache, "cached_fetch", fetch)
    run = await _read(body, [1])

    assert [p.number for p in run.pages] == [1]
    # The hash ran, and in a worker thread, not the one running the event loop.
    assert len(hashed_on) == 1 and hashed_on[0] != threading.get_ident()
    # The key is what it was when the hash ran in the loop: 32 hex characters of the file's
    # SHA-256 between the URL and the page number.
    digest = real_sha256(body).hexdigest()[:32]
    assert keys == [f"ocr:{URL}:{digest}:1:{ocr.RENDER_DPI}:{ENGINE.version}:{ENGINE.languages}"]
