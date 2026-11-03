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


def skip_outage(source: str, exc: BaseException) -> None:
    """Report an outage that stopped a smoke run, or raise anything else again.

    The caller keeps going to its verdict, so a check that already failed
    still fails the run; only the checks after the outage are skipped.
    """
    if not is_upstream_outage(exc):
        raise exc
    _skipped.append(source)
    print(f"SKIP: {source} unavailable ({exc}); the remaining checks did not run")


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
