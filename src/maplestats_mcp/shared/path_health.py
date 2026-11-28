"""Which StatCan paths answered with Cloudflare's bot check lately, as this server saw them.

The check is not host-wide. On 2026-11-18 www150.statcan.gc.ca answered the Web Data
Service (/t1/wds/rest/) and challenged SDMX (/t1/wds/sdmx/), the CIMT trade API (/t1/cimt/),
The Daily's RSS feeds and the catalogue pages (shared/challenge_notes.py lists the paths).
The circuit breaker (shared/breaker.py) keeps one state per host, or per path group of these two
StatCan hosts (the groups below, so a slow group pauses only itself), and a challenge never
opens it: it is counted for /stats only. The breaker therefore cannot say which tools a
challenge took down. This keeps the finer fact: for each path group below, when a challenge
was last seen and whether the path has answered since.

Two producers, neither of which sends a request of its own:

- every real call: `raise_if_cloudflare_challenge` and `BreakerClient.send` (shared/http.py)
  note a challenge, or an answer, for the path they just used;
- `statcan_check_access`, whose fresh report names each service as answering or blocked.

A path counts as challenged for TTL_SECONDS after its last challenge, unless it answered
after that. The TTL is the one statcan_check_access keeps its report for (15 minutes): past
it the path is treated as open again until a call meets the check anew, so a lifted block
stops showing within a quarter of an hour. plan_query and search_tools read this to mark the
tools that have no other route on a challenged path and to list the working route first.
With nothing challenged, both leave their output exactly as it was.

MapleStats never tries to pass the check (no browser-like User-Agent, headless browser,
proxy, cookie or fingerprint change); this only remembers what it was told.
"""

from __future__ import annotations

import time
from collections.abc import Collection
from dataclasses import dataclass
from typing import Any

WWW150 = "www150.statcan.gc.ca"
WWW12 = "www12.statcan.gc.ca"

# A challenge seen longer ago than this no longer counts (statcan_check_access's cache TTL).
TTL_SECONDS = 15 * 60

# (key, host, path prefixes), matched in this order. www12 is one group because the whole
# host sits behind the check.
PATHS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("wds", WWW150, ("/t1/wds/rest/",)),
    ("sdmx", WWW150, ("/t1/wds/sdmx/",)),
    ("cimt", WWW150, ("/t1/cimt/",)),
    ("rss", WWW150, ("/n1/rss/",)),
    # Delta files are asked for at /delta/{date}.zip (statcan/delta/constants.py), which
    # answers 301 to /n1/delta/ (what statcan/delta/archive.py reads directly): both are files.
    ("files", WWW150, ("/n1/tbl/", "/n1/delta/", "/delta/")),
    ("daily", WWW150, ("/n1/dai-quo/", "/n1/daily-quotidien/")),
    ("pages", WWW150, ("/n1/en/", "/n1/fr/")),
    ("pub", WWW150, ("/n1/pub/",)),
    ("census", WWW12, ("/",)),
)
_HOSTS = frozenset(host for _, host, _ in PATHS)

_clock = time.monotonic
# key -> [monotonic time of the last challenge, of the last answer]; at most len(PATHS) + 1.
_seen: dict[str, list[float | None]] = {}


def path_key(host: str, path: str) -> str | None:
    """The group a path belongs to, or None for a host or path this does not follow.

    A /n1/pub/ page is challenged but its .zip files (PUMF, LODE) are not, so a zip is
    its own group, "pub_zip".
    """
    if host not in _HOSTS:
        return None
    for key, group_host, prefixes in PATHS:
        if host == group_host and path.startswith(prefixes):
            return "pub_zip" if key == "pub" and path.lower().endswith(".zip") else key
    return None


def record_challenge(host: str, path: str) -> None:
    key = path_key(host, path)
    if key is not None:
        _seen.setdefault(key, [None, None])[0] = _clock()


def record_answer(host: str, path: str) -> None:
    """The path answered something other than the check (any status but a challenge)."""
    key = path_key(host, path)
    if key is not None:
        _seen.setdefault(key, [None, None])[1] = _clock()


def challenged_now() -> frozenset[str]:
    """The path groups that answered with the check within TTL_SECONDS and not since."""
    now = _clock()
    return frozenset(
        key
        for key, (challenged, answered) in _seen.items()
        if challenged is not None
        and now - challenged <= TTL_SECONDS
        and (answered is None or answered < challenged)
    )


def reset() -> None:
    _seen.clear()


@dataclass(frozen=True)
class Dependency:
    """Tools that have no other route while one path group is challenged.

    Only a tool that cannot answer without the path is listed: the sdmx_ tools read the
    same series from WDS on their own, statcan_daily_get_releases reads the archive, and
    wds_get_full_table_download still gives a script that rebuilds the table, so none of
    them is marked. tests/test_planner_blocked.py checks each prefix against the tools'
    own constants.
    """

    key: str
    prefixes: tuple[str, ...]
    label_en: str
    label_fr: str
    # The working route, in a clause that follows "use": the nearest data via another door.
    use_en: str
    use_fr: str


DEPENDENCIES: tuple[Dependency, ...] = (
    Dependency(
        "cimt",
        ("cimt_",),
        "StatCan's CIMT API",
        "l'API CICM de StatCan",
        "wds_get_cube_metadata on 12-10-0011-01",
        "wds_get_cube_metadata sur 12-10-0011-01",
    ),
    Dependency(
        "pages",
        ("statcan_reference_", "statcan_pumf_search", "statcan_pumf_list_files"),
        "StatCan's catalogue pages",
        "les pages du catalogue de StatCan",
        "wds_search_cubes",
        "wds_search_cubes",
    ),
)


def dependency_blocking(tool: str, challenged: frozenset[str]) -> Dependency | None:
    """The dependency that takes `tool` down while its path group is challenged, if any."""
    for dependency in DEPENDENCIES:
        if dependency.key in challenged and tool.startswith(dependency.prefixes):
            return dependency
    return None


def mark_results(results: Any, challenged: Collection[str]) -> Any:
    """search_tools' results with each blocked tool marked: `blocked: true`, a note as its description and no arguments.

    `results` comes back as it came in when no path is challenged, or when it is not a list
    of tool dicts (the "No tools matched" text).
    """
    if not challenged or not isinstance(results, list):
        return results
    frozen = frozenset(challenged)
    marked = []
    for result in results:
        name = str(result.get("name", "")) if isinstance(result, dict) else ""
        dependency = dependency_blocking(name, frozen)
        if dependency is None:
            marked.append(result)
            continue
        # The note replaces the description and the argument signature or schema: a blocked
        # tool is not to be called, only named. This keeps a result list no longer than it was.
        note = f"Blocked now ({dependency.label_en}): do not call; use {dependency.use_en}."
        kept = {k: v for k, v in result.items() if k not in ("arguments", "inputSchema")}
        marked.append({**kept, "description": note, "blocked": True})
    return marked
