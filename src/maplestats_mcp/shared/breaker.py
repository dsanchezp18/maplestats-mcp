"""Per-host circuit breaker for upstream requests, and the per-host error counts /stats shows.

Every client shared/http.py creates sends through it, so a host that keeps
failing stops costing each caller its full timeout. After
MAPLE_BREAKER_FAILURES failures in a row within MAPLE_BREAKER_WINDOW_SECONDS
(timeouts, connection errors, 5xx answers, Cloudflare challenges) the host's
breaker opens: requests to it raise CircuitOpen at once, without being sent.
After MAPLE_BREAKER_COOLDOWN_SECONDS one request goes through as a probe;
an answer closes the breaker, a failure opens it for another cooldown.

What does not count: a 4xx answer (the caller's input, or a rate limit the
host answered), and a second failure inside one logical call. The retrying
helpers in shared/http.py and shared/retrying.py run each call in
`one_call()`, so a call whose three attempts all time out is one failure,
not three. Any answer that is not a failure resets the count, so a host
that fails now and then (geo.statcan.gc.ca answered 6 of 10 requests on
2026-09-27) is never cut off by its bad moments alone.

The state is per process and in memory. It holds host names only, never
paths, query strings or anything a caller typed beyond the host its tool
reaches; tools that take a URL accept only their publisher's hosts.
"""

from __future__ import annotations

import ipaddress
import math
import threading
import time
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from maplestats_mcp import config
from maplestats_mcp.shared.errors import UpstreamUnavailable
from maplestats_mcp.shared.fr_typography import call_error, french_spacing

FailureKind = Literal["timeout", "network", "server_error", "cloudflare"]
FAILURE_KINDS: tuple[FailureKind, ...] = ("timeout", "network", "server_error", "cloudflare")
State = Literal["closed", "open", "half_open"]

# Hosts tracked at most; the server reaches about 200, so this only bounds memory.
MAX_HOSTS = 500
# The wait a refused caller is told while another request probes the host.
_PROBE_WAIT_SECONDS = 5.0


class CircuitOpen(UpstreamUnavailable):
    """Refused without sending: the host's breaker is open after repeated failures."""


@dataclass
class _Host:
    streak: list[float] = field(default_factory=list)
    state: State = "closed"
    open_until: float = 0.0
    probing: bool = False
    errors: Counter[str] = field(default_factory=Counter)
    rejected: int = 0
    opened: int = 0


@dataclass
class _Call:
    counted: set[str]
    server_errors: frozenset[int] | None


_call: ContextVar[_Call | None] = ContextVar("maplestats_breaker_call", default=None)


@contextmanager
def one_call(server_errors: frozenset[int] | None = None) -> Iterator[None]:
    """Count at most one failure per host for the requests made inside (a call and its retries).

    `server_errors` names the 5xx statuses that are failures here; None means
    every 5xx. shared/retrying.py passes its retryable set, so a status a
    caller declared a deterministic answer (IMDB's unknown-survey 500) does
    not count against the host. A nested call keeps the outer one's rules.
    """
    if _call.get() is not None:
        yield
        return
    token = _call.set(_Call(set(), server_errors))
    try:
        yield
    finally:
        _call.reset(token)


def is_failure_status(status: int) -> bool:
    call = _call.get()
    if call is not None and call.server_errors is not None:
        return status in call.server_errors
    return status >= 500


def _trackable(host: str) -> bool:
    """Named hosts only: an IP address or localhost is no publisher to report."""
    if not host or host == "localhost":
        return False
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return True
    return False


def _clock_time(when: datetime, lang_fr: bool) -> str:
    return f"{when.hour} h {when.minute:02d}" if lang_fr else f"{when:%H:%M}"


class CircuitBreaker:
    """Breaker state and error counts for every upstream host, in memory."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._hosts: dict[str, _Host] = {}
        # Parsing runs in worker threads; a lock keeps the counts whole if a
        # request is ever made from one.
        self._lock = threading.Lock()

    def reset(self) -> None:
        with self._lock:
            self._hosts.clear()

    def before_request(self, host: str) -> bool:
        """Raise CircuitOpen when `host` is refused; True when this request is the probe."""
        if not config.get_breaker_enabled():
            return False
        with self._lock:
            entry = self._hosts.get(host)
            if entry is None or entry.state == "closed":
                return False
            now = self._clock()
            if entry.state == "open" and now >= entry.open_until:
                entry.state = "half_open"
            if entry.state == "half_open" and not entry.probing:
                entry.probing = True
                return True
            entry.rejected += 1
            wait = max(entry.open_until - now, _PROBE_WAIT_SECONDS if entry.probing else 1.0)
        raise _refusal(host, wait)

    def record_failure(self, host: str, kind: FailureKind, *, probe: bool = False) -> None:
        call = _call.get()
        repeat = call is not None and host in call.counted
        with self._lock:
            entry = self._hosts.get(host)
            if entry is None:
                if repeat or len(self._hosts) >= MAX_HOSTS or not _trackable(host):
                    return
                entry = self._hosts[host] = _Host()
            if not repeat:
                entry.errors[kind] += 1
                if call is not None:
                    call.counted.add(host)
            if not config.get_breaker_enabled():
                return
            now = self._clock()
            # A failed probe, or any failure while a probe is due, reopens at once.
            if probe or entry.state == "half_open":
                self._open(entry, now)
                return
            # Requests sent before the breaker opened can still fail after it.
            if repeat or entry.state == "open":
                return
            window = config.get_breaker_window_seconds()
            entry.streak = [t for t in entry.streak if now - t <= window]
            entry.streak.append(now)
            if len(entry.streak) >= config.get_breaker_failures():
                self._open(entry, now)

    def record_success(self, host: str) -> None:
        """The host answered: clear its count and close its breaker."""
        with self._lock:
            entry = self._hosts.get(host)
            if entry is not None:
                entry.streak.clear()
                entry.state = "closed"
                entry.probing = False

    def release(self, host: str, *, probe: bool) -> None:
        """Neither answer nor failure (a cancelled request, a 403): let the next request probe."""
        if not probe:
            return
        with self._lock:
            entry = self._hosts.get(host)
            if entry is not None:
                entry.probing = False

    def _open(self, entry: _Host, now: float) -> None:
        entry.state = "open"
        entry.open_until = now + config.get_breaker_cooldown_seconds()
        entry.probing = False
        entry.streak.clear()
        entry.opened += 1

    def _view(self, entry: _Host, now: float, wall: datetime) -> tuple[State, str | None]:
        """The state as a reader sees it, and when an open breaker lets a probe through."""
        if entry.state != "open":
            return entry.state, None
        if now >= entry.open_until:
            return "half_open", None
        retry_at = wall + timedelta(seconds=entry.open_until - now)
        return "open", retry_at.isoformat(timespec="seconds")

    def snapshot(self) -> dict[str, Any]:
        """Settings, then every host that failed or is not closed, for /stats."""
        now, wall = self._clock(), datetime.now(UTC)
        hosts: dict[str, dict[str, Any]] = {}
        with self._lock:
            for host in sorted(self._hosts):
                entry = self._hosts[host]
                state, retry_at = self._view(entry, now, wall)
                hosts[host] = {
                    "state": state,
                    "probe_after": retry_at,
                    "errors": {kind: entry.errors[kind] for kind in FAILURE_KINDS},
                    "refused": entry.rejected,
                    "times_opened": entry.opened,
                }
        return {
            "breaker": {
                "enabled": config.get_breaker_enabled(),
                "failures_to_open": config.get_breaker_failures(),
                "window_seconds": config.get_breaker_window_seconds(),
                "cooldown_seconds": config.get_breaker_cooldown_seconds(),
            },
            "hosts": hosts,
        }

    def open_hosts(self) -> list[tuple[str, str | None]]:
        """(host, probe time or None when a probe is due) for every breaker not closed."""
        now, wall = self._clock(), datetime.now(UTC)
        with self._lock:
            views = [(host, self._view(entry, now, wall)) for host, entry in self._hosts.items()]
        return sorted((host, at) for host, (state, at) in views if state != "closed")


def _refusal(host: str, wait: float) -> CircuitOpen:
    seconds = max(1, math.ceil(wait))
    when = datetime.now(UTC) + timedelta(seconds=seconds)
    failures = config.get_breaker_failures()
    return call_error(
        CircuitOpen,
        f"{host} failed {failures} times in a row (timeouts, connection errors or server "
        "errors), so MapleStats has paused requests to it rather than make you wait for "
        f"another timeout. Try again after {_clock_time(when, False)} UTC (in about "
        f"{seconds} s).",
        f"{host} a échoué {failures} fois de suite (délais dépassés, erreurs de connexion ou "
        "erreurs du serveur) ; MapleStats suspend donc ses requêtes vers ce service plutôt que "
        f"de vous faire attendre un autre délai. Réessayez après {_clock_time(when, True)} UTC "
        f"(dans environ {seconds} s).",
    )


# The process-wide breaker every shared client sends through.
BREAKER = CircuitBreaker()


def render_status(breaker: CircuitBreaker | None = None) -> str:
    """The docs://status text: hosts whose breaker is open now, in English and French."""
    breaker = breaker or BREAKER
    lines = ["# MapleStats MCP — upstream status / état des sources", ""]
    if not config.get_breaker_enabled():
        lines.append("EN: The circuit breaker is off (MAPLE_BREAKER=0): every request is sent.")
        lines.append(
            french_spacing(
                "FR: Le disjoncteur est désactivé (MAPLE_BREAKER=0) : chaque requête est envoyée."
            )
        )
        return "\n".join(lines)
    hosts = breaker.open_hosts()
    if not hosts:
        lines.append("EN: No host is paused; every upstream is called normally.")
        lines.append(
            french_spacing("FR: Aucun hôte n'est suspendu ; chaque source est appelée normalement.")
        )
        return "\n".join(lines)
    lines.append(
        f"EN: {len(hosts)} host(s) failed repeatedly. Tools that call them fail at once with "
        "UpstreamUnavailable until a probe request gets an answer."
    )
    lines.append(
        french_spacing(
            f"FR: {len(hosts)} hôte(s) ont échoué à répétition. Les outils qui les appellent "
            "échouent aussitôt (UpstreamUnavailable) jusqu'à ce qu'une requête de sondage "
            "obtienne une réponse."
        )
    )
    lines.append("")
    for host, probe_after in hosts:
        if probe_after is None:
            lines.append(f"- {host}: probe due, the next request is sent")
            lines.append(french_spacing(f"  {host} : sondage dû, la prochaine requête est envoyée"))
        else:
            lines.append(f"- {host}: paused until {probe_after}")
            lines.append(french_spacing(f"  {host} : suspendu jusqu'à {probe_after}"))
    return "\n".join(lines)
