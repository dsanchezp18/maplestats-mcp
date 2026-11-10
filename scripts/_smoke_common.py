"""Shared helper for live smoke tests that skip a sustained upstream outage."""

from __future__ import annotations

import re

from maplestats_mcp.shared.errors import UpstreamError, UpstreamUnavailable

# Exit status for a run that was cut short by an outage: not a failure of ours, but not a
# pass either (sysexits.h's EX_TEMPFAIL). smoke.yml retries a non-zero run once.
SKIPPED_EXIT = 75
_skipped: list[str] = []


def is_upstream_outage(exc: BaseException) -> bool:
    """True for a timeout, a network failure, a Cloudflare challenge or an HTTP 5xx.

    A 4xx or a changed response shape is not an outage: it is a possible
    regression, so the smoke test must still fail on it.
    """
    if isinstance(exc, UpstreamUnavailable):
        return True
    return isinstance(exc, UpstreamError) and re.search(r"HTTP 5\d\d", str(exc)) is not None


def skip_outage(source: str, exc: BaseException, *, rest_runs: bool = False) -> None:
    """Report an outage that stopped a smoke run, or raise anything else again.

    The caller keeps going to its verdict, so a check that already failed
    still fails the run; only the checks after the outage are skipped.
    """
    if not is_upstream_outage(exc):
        raise exc
    _skipped.append(source)
    rest = "the other checks still run" if rest_runs else "the remaining checks did not run"
    print(f"SKIP: {source} unavailable ({exc}); {rest}")


def skip_reloading(source: str, table: str) -> None:
    """Report a DataStore table that is empty because its publisher is reloading it.

    open.canada.ca reloads its proactive disclosure tables in place: on 2026-11-05 the
    grants table answered 0 rows for hours while contracts held every row twice. An
    empty table is that reload, not a regression, so the checks that read it are skipped.
    """
    _skipped.append(source)
    print(f"SKIP: {source} is reloading ({table} has 0 rows); the remaining checks did not run")


def skip_stale(source: str, detail: str) -> None:
    """Report a check skipped because one publisher page lags another.

    CFIA updates its yearly totals and its per-disease pages on different days, and a
    CDN edge can serve an older copy of one of them: on 2026-11-10 GitHub's runner got a
    CWD page last modified 2026-09-10 beside totals current to 2026-10-31. Two pages that
    disagree because one is older is the publisher's lag, not a parser regression.
    """
    _skipped.append(source)
    print(f"SKIP: {source} pages disagree because one is older ({detail})")


def verdict(name: str, ok: bool) -> int:
    """Print the run's verdict and return its exit status.

    A run whose checks were skipped for an outage used to print PASSED and exit 0, so a
    source that was down every week looked healthy. It now reports SKIPPED and exits
    SKIPPED_EXIT; a check that failed before the outage still fails the run.
    """
    if not ok:
        print(f"\n{name} SMOKE TEST FAILED")
        return 1
    if _skipped:
        print(f"\n{name} SMOKE TEST SKIPPED ({', '.join(_skipped)} unavailable): not a pass")
        return SKIPPED_EXIT
    print(f"\n{name} SMOKE TEST PASSED")
    return 0
