"""Check the links of the built website (build/site/).

Internal links (pages, assets and #fragments, including the absolute URLs
that name this site) are checked against the files on disk; tests/test_site.py
runs that part on every test run. With --external, every other http(s) link
is also requested once, which needs the network:

    uv run python scripts/build_site.py
    uv run python scripts/check_site_links.py --external
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import defaultdict
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urldefrag, urljoin, urlsplit

import httpx

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SITE = ROOT / "build" / "site"
SITE_URL = "https://maplestats.danielstats.io/"

# Links a browser hands to another program, or that only an MCP client can use.
SKIP_SCHEMES = ("mailto:", "cursor:", "vscode:", "data:", "javascript:")
# The MCP endpoint answers a plain GET with an error by design (the connect
# page says so); /health is the address that shows it is up.
SKIP_EXTERNAL = ("https://maplestats-mcp.onrender.com/mcp",)
EXTRA_EXTERNAL = ("https://maplestats-mcp.onrender.com/health",)


class _Links(HTMLParser):
    """Every id on a page, and every href/src it points to."""

    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.add(values["id"] or "")
        if tag == "a" and values.get("name"):
            self.ids.add(values["name"] or "")
        for attr in ("href", "src"):
            link = values.get(attr)
            if link and not (tag == "link" and values.get("rel") in {"preconnect", "dns-prefetch"}):
                self.links.append(link)


def _parse(page: Path) -> _Links:
    parser = _Links()
    parser.feed(page.read_text(encoding="utf-8"))
    return parser


def scan(site: Path) -> tuple[list[str], dict[str, list[str]]]:
    """Broken internal links, and the external links with the pages using them."""
    pages = {page: _parse(page) for page in sorted(site.rglob("*.html"))}
    ids = {page.resolve(): parsed.ids for page, parsed in pages.items()}
    broken: list[str] = []
    external: dict[str, list[str]] = defaultdict(list)
    for page, parsed in pages.items():
        where = page.relative_to(site).as_posix()
        base = SITE_URL + where
        for link in parsed.links:
            if link.startswith(SKIP_SCHEMES):
                continue
            url = urljoin(base, link)
            if not url.startswith(SITE_URL):
                if urlsplit(url).scheme in {"http", "https"}:
                    external[urldefrag(url).url].append(where)
                continue
            path, fragment = urldefrag(url)
            relative = unquote(path[len(SITE_URL) :]) or "index.html"
            if relative.endswith("/"):
                relative += "index.html"
            target = (site / relative).resolve()
            if not target.is_file():
                broken.append(f"{where}: {link} (no file {relative})")
            elif fragment and target.suffix == ".html" and fragment not in ids.get(target, set()):
                broken.append(f"{where}: {link} (no id #{fragment})")
    return broken, external


async def _check(client: httpx.AsyncClient, url: str) -> str | None:
    try:
        response = await client.head(url)
        # Several servers refuse HEAD; a GET is the request a reader makes.
        if response.status_code >= 400:
            response = await client.get(url)
    except httpx.HTTPError as exc:
        return f"{type(exc).__name__}: {exc}"
    if response.status_code == 403:
        # Bot protection answers a script 403 and a browser the page; checked
        # by hand when first seen (mcprush.com, 2026-10-03), so not a failure.
        return "HTTP 403 (blocks scripts? open it in a browser)"
    if response.status_code >= 400:
        return f"HTTP {response.status_code}"
    return None


async def check_external(urls: list[str]) -> dict[str, str]:
    limit = asyncio.Semaphore(8)
    headers = {
        "User-Agent": "maplestats-mcp site link check (+https://github.com/dsanchezp18/maplestats-mcp)"
    }
    async with httpx.AsyncClient(
        follow_redirects=True, timeout=30, headers=headers, http2=True
    ) as client:

        async def one(url: str) -> tuple[str, str | None]:
            async with limit:
                return url, await _check(client, url)

        results = await asyncio.gather(*(one(url) for url in urls))
    return {url: problem for url, problem in results if problem}


def main() -> int:
    parser = argparse.ArgumentParser(description="Check the links of the built website.")
    parser.add_argument("site", nargs="?", type=Path, default=DEFAULT_SITE)
    parser.add_argument("--external", action="store_true", help="also request every external link")
    args = parser.parse_args()
    if not (args.site / "index.html").is_file():
        print(f"No built site in {args.site}; run scripts/build_site.py first.", file=sys.stderr)
        return 2
    broken, external = scan(args.site)
    for line in broken:
        print("internal:", line)
    failed = bool(broken)
    if args.external:
        urls = sorted(set(external) - set(SKIP_EXTERNAL) | set(EXTRA_EXTERNAL))
        problems = asyncio.run(check_external(urls))
        for url, problem in sorted(problems.items()):
            print(
                f"external: {url} -> {problem} (on {', '.join(sorted(set(external.get(url, []))))})"
            )
        hard = [problem for problem in problems.values() if not problem.startswith("HTTP 403")]
        print(
            f"{len(urls)} external links checked, {len(hard)} failed, {len(problems) - len(hard)} refused a script."
        )
        failed = failed or bool(hard)
    print(
        f"{sum(1 for _ in args.site.rglob('*.html'))} pages, {len(broken)} broken internal links."
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
