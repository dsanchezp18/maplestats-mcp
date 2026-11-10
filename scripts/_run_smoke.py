"""Run one live smoke script; an outage that stops it is a skip, not a failure.

smoke.yml runs every script through this. Most scripts let an exception end the
run, so a source answering HTTP 500 or timing out turned the whole job red
(open.alberta.ca on 2026-11-09 and 2026-11-10). Here an uncaught outage
(_smoke_common.is_upstream_outage: a timeout, a network failure, a Cloudflare
challenge, an HTTP 5xx) exits SKIPPED_EXIT, unless a check had already printed
FAIL, which still fails the run. Any other exception is a failure as before.

Usage: python scripts/_run_smoke.py smoke_test_ckan
"""

from __future__ import annotations

import io
import runpy
import sys
from pathlib import Path
from typing import TextIO

import httpx
from _smoke_common import SKIPPED_EXIT, is_upstream_outage

HERE = Path(__file__).resolve().parent


class _Tee(io.TextIOBase):
    """Pass output through and note whether a check printed FAIL."""

    def __init__(self, inner: TextIO) -> None:
        self.inner = inner
        self.failed = False

    def write(self, text: str) -> int:
        if any(line.lstrip().startswith("FAIL") for line in text.splitlines()):
            self.failed = True
        return self.inner.write(text)

    def flush(self) -> None:
        self.inner.flush()


def _is_outage(exc: BaseException) -> bool:
    # A raw httpx 5xx or transport error that a script's own client let through.
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return is_upstream_outage(exc)


def main(script: str) -> int:
    path = HERE / f"{script.removesuffix('.py')}.py"
    # The script sees only its own name: smoke_test_modules reads argv as a filter.
    sys.argv = [str(path)]
    tee = _Tee(sys.stdout)
    sys.stdout = tee
    try:
        runpy.run_path(str(path), run_name="__main__")
    except SystemExit as done:
        code = done.code
        return code if isinstance(code, int) else (0 if code is None else 1)
    # Re-raised unless it is an outage, so only an outage is skipped.
    except Exception as exc:
        if not _is_outage(exc) or tee.failed:
            raise
        print(f"SKIP: {script} stopped by an outage ({type(exc).__name__}: {exc})")
        print(f"\n{script} SKIPPED: a source was unavailable; not a pass")
        return SKIPPED_EXIT
    finally:
        sys.stdout = tee.inner
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
