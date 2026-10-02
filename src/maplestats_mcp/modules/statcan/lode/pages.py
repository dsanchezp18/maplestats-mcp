"""Parsers for StatCan's LODE landing page and www150 product pages.

Markup confirmed live 2026-10-02. The landing page is one
`<section class="panel">` per database: an `<h3>` title, `<p>` text whose
first link is the product page, then a `<ul>` of "date - Version n" items
(French: "24 septembre 2026 - Version 2.0", and "1 er mars 2019" with a
stray space). Product pages are plain server-rendered HTML with the ZIP
links in anchors, "Release date: ..." and "Date modified: ..." text, and
(for most databases) a variables list: "name: description;" in one
paragraph (ODHF, ODSRF) or one `<li>` per variable "name - description"
(ODB).
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from datetime import date
from urllib.parse import urljoin, urlparse

from maplestats_mcp.modules.statcan.lode import constants
from maplestats_mcp.modules.statcan.lode.schemas import LodeRelease

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
    "juillet": 7, "août": 8, "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11,
    "décembre": 12, "decembre": 12,
}  # fmt: skip
_EN_DATE = re.compile(r"([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})")
_FR_DATE = re.compile(r"(\d{1,2})\s*(?:er)?\s+([A-Za-zéûÉ]+)\s+(\d{4})")
_VERSION = re.compile(r"Version\s*[\d.]+", re.IGNORECASE)
_OGL = re.compile(
    r"Open Government Licen[cs]e\s*[-–—]*\s*Canada|"
    r"Licence du gouvernement ouvert du Canada",
    re.IGNORECASE,
)
_PROVINCE_FILE = re.compile(
    r"(?:^|[_-])(NL|PE|NS|NB|QC|ON|MB|SK|AB|BC|YT|NT|NU)(?:[_-]\d)?(?:[_-]v\d+)?\.zip$",
    re.IGNORECASE,
)


def text_of(fragment: str) -> str:
    """Tag-free, entity-decoded text with single spaces."""
    without_tags = re.sub(r"<[^>]+>", " ", fragment)
    return " ".join(html.unescape(without_tags).replace("\xa0", " ").split())


def parse_date(text: str) -> str | None:
    """An English or French long date as ISO 8601, or None."""
    clean = text.replace("\xa0", " ")
    match = _EN_DATE.search(clean)
    if match and match.group(1).lower() in _MONTHS:
        return date(
            int(match.group(3)), _MONTHS[match.group(1).lower()], int(match.group(2))
        ).isoformat()
    match = _FR_DATE.search(clean)
    if match and match.group(2).lower() in _MONTHS:
        return date(
            int(match.group(3)), _MONTHS[match.group(2).lower()], int(match.group(1))
        ).isoformat()
    return None


def parse_release(line: str) -> LodeRelease:
    version = _VERSION.search(line)
    return LodeRelease(
        date=parse_date(line),
        version=version.group(0).replace("  ", " ") if version else None,
        label=line,
    )


@dataclass
class LandingEntry:
    title: str
    page_url: str
    description: str
    releases: list[LodeRelease] = field(default_factory=list)


def parse_landing(page: str) -> list[LandingEntry]:
    entries: list[LandingEntry] = []
    for section in page.split('<section class="panel')[1:]:
        title = re.search(r"<h3[^>]*>(.*?)</h3>", section, re.DOTALL)
        link = re.search(r'<p>\s*<a[^>]+href="([^"]+)"', section) or re.search(
            r'<a[^>]+href="([^"]+)"', section
        )
        if not title or not link:
            continue
        paragraphs = [text_of(p) for p in re.findall(r"<p>(.*?)</p>", section, re.DOTALL)]
        marker = re.compile(r"^(Release date|Dates? de diffusion)", re.IGNORECASE)
        description = " ".join(p for p in paragraphs if p and not marker.match(p))
        items = [text_of(li) for li in re.findall(r"<li[^>]*>(.*?)</li>", section, re.DOTALL)]
        entries.append(
            LandingEntry(
                title=text_of(title.group(1)),
                page_url=html.unescape(link.group(1)),
                description=description,
                releases=[parse_release(item) for item in items if parse_date(item)],
            )
        )
    return entries


@dataclass
class Download:
    url: str
    label: str


@dataclass
class ProductPage:
    release_date: str | None
    date_modified: str | None
    licence: str | None
    downloads: list[Download]
    fields: list[tuple[str, str]]


def parse_downloads(page: str, page_url: str) -> list[Download]:
    found: dict[str, Download] = {}
    for href, label in re.findall(
        r'<a[^>]+href="([^"]+\.zip)"[^>]*>(.*?)</a>', page, re.DOTALL | re.IGNORECASE
    ):
        url = urljoin(page_url, html.unescape(href))
        parsed = urlparse(url)
        if parsed.hostname != constants.ALLOWED_HOST:
            continue
        name = text_of(label) or url.rsplit("/", 1)[-1]
        found.setdefault(url, Download(url=url, label=name))
    return list(found.values())


_FIELD = re.compile(r"^([A-Za-z_][\w]*)\s*(?::|-|–)\s*(.+)$")


def parse_fields(page: str) -> list[tuple[str, str]]:
    """The product page's variable list, as (name, description) pairs."""
    start = re.search(
        r"variables(?:[^.:<]|<[^>]+>){0,160}(?:as follows|suivante)", page, re.IGNORECASE
    )
    if not start:
        return []
    chunk = page[start.end() : start.end() + 12000]
    end = re.search(r"For more information|Pour plus de|Pour obtenir plus", chunk)
    chunk = chunk[: end.start()] if end else chunk
    items = [text_of(li) for li in re.findall(r"<li[^>]*>(.*?)</li>", chunk, re.DOTALL)]
    if not items:
        items = [part.strip() for part in text_of(chunk).split(";")]
    pairs: list[tuple[str, str]] = []
    for item in items:
        match = _FIELD.match(item.strip().lstrip(":").strip())
        if match:
            pairs.append((match.group(1), match.group(2).strip().rstrip(".;")))
    return pairs


def parse_product(page: str, page_url: str) -> ProductPage:
    text = text_of(re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", "", page))
    released = re.search(
        r"(?:Release date|Date de diffusion)\s*:\s*([^:]{0,40}?\d{4})", text, re.IGNORECASE
    )
    modified = re.search(
        r"(?:Date modified|Date de modification)\s*:?\s*(\d{4}-\d{2}-\d{2})", text, re.IGNORECASE
    )
    return ProductPage(
        release_date=parse_date(released.group(1)) if released else None,
        date_modified=modified.group(1) if modified else None,
        licence=constants.OGL if _OGL.search(text) else None,
        downloads=parse_downloads(page, page_url),
        fields=parse_fields(page),
    )


def file_format(url: str) -> str:
    name = url.rsplit("/", 1)[-1].lower()
    for marker in ("geojson", "gpkg", "parquet"):
        if marker in name:
            return marker
    return "zip"


def file_provinces(url: str) -> list[str]:
    match = _PROVINCE_FILE.search(url.rsplit("/", 1)[-1])
    return [match.group(1).upper()] if match else []
