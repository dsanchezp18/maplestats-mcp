"""The website generator (scripts/build_site.py) must stay in step with the server.

Its hand-kept tables (SOURCES, FAMILIES, PORTAL_PLACES) must cover every
module, sub-API and portal, and the search it ships to the browser must
rank tools exactly as search_tools does, because the site says it does.
The French pages must read as French: English only where it is marked.
"""

from __future__ import annotations

import asyncio
import base64
import html
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULES = ROOT / "src" / "maplestats_mcp" / "modules"


def _load_builder():
    spec = importlib.util.spec_from_file_location("build_site", ROOT / "scripts" / "build_site.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolve their module through sys.modules while executing.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


site = _load_builder()

# English and French queries, including accents, plurals and ties.
QUERIES = [
    "rental vacancy rates",
    "Bank of Canada policy rate",
    "consumer price index",
    "federal contract awards",
    "PUMF bootstrap weights",
    "tide times Halifax",
    "census profile income",
    "wildfire burned area",
    "taux de chômage",
    "taux directeur de la Banque du Canada",
    "taux d'inoccupation des logements locatifs",
    "loyers",
    "hopital",
    "mises en chantier",
    "superficie brûlée feux de forêt",
    "ronde d'invitations entrée express",
]


def test_every_module_has_site_metadata():
    modules = {p.name for p in MODULES.iterdir() if p.is_dir() and not p.name.startswith("_")}
    missing = sorted(modules - set(site.SOURCES))
    stale = sorted(set(site.SOURCES) - modules)
    assert not missing, f"Add these modules to SOURCES in scripts/build_site.py: {missing}"
    assert not stale, f"SOURCES lists modules that no longer exist: {stale}"


def test_every_portal_has_a_place():
    families = {
        "ckan": site.CKAN_PORTALS,
        "arcgis_hub": site.ARCGIS_PORTALS,
        "socrata": site.SOCRATA_PORTALS,
    }
    for family, portals in families.items():
        assert set(portals) == set(site.PORTAL_PLACES[family]), (
            f"PORTAL_PLACES[{family!r}] in scripts/build_site.py is out of sync with its PORTALS"
        )
    places = {place for table in site.PORTAL_PLACES.values() for place, _ in table.values()}
    assert places - {""} <= set(site.PLACES)
    for source in site.SOURCES.values():
        assert set(source.places) <= set(site.PLACES)


def test_family_titles_match_folders():
    for key in site.FAMILIES:
        module, _, family = key.partition("/")
        assert (MODULES / module / family / "tools.py").exists(), f"stale FAMILIES entry {key!r}"


async def test_site_search_ranks_like_search_tools():
    modules = await site.collect_modules()
    index = site.build_index(modules)
    for query in QUERIES:
        ranked = site.rank(index, query)[: index["top"]]
        assert [index["tools"][i][0] for i in ranked] == await site.server_search(query), query


async def test_site_builds(tmp_path: Path):
    out = tmp_path / "site"
    stats = await site.build(out)
    templates = sorted(p.name for p in (ROOT / "site").glob("*.html"))
    assert stats["pages"] == 2 * len(templates)
    for name in templates:
        assert (out / name).is_file()
        assert (out / "fr" / name).is_file()
    for asset in ("site.css", "site.js", "search-index.json", "modules.json"):
        assert (out / "assets" / asset).is_file()
    assert (out / "llms.txt").is_file()


async def test_statcan_page_counts_come_from_the_registry(tmp_path: Path):
    """statcan.html builds in both languages and shows the registry's StatCan counts.

    Every family is listed once, every tool link names a real tool, and every
    trimmed JSON box is still JSON once its // comment lines are dropped.
    """
    import html
    import json
    import re

    modules = await site.collect_modules()
    statcan = next(m for m in modules if m.key == "statcan")
    families = {t.family for t in statcan.tools}
    await site.build(tmp_path / "site")
    tool_names = {t.name for m in modules for t in m.tools}
    count_tables = next(
        call["response"]["total_count"]
        for call in site.load_case("counts")["calls"]
        if call["name"] == "wds_list_all_cubes"
    )
    pages = {
        "en": tmp_path / "site" / "statcan.html",
        "fr": tmp_path / "site" / "fr" / "statcan.html",
    }
    for lang, page in pages.items():
        text = page.read_text(encoding="utf-8")
        assert f'<p class="fig">{len(statcan.tools)}</p>' in text
        assert f"{'in' if lang == 'en' else 'en'} {len(families)} famil" in text
        assert f'<p class="fig">{site.number(count_tables, lang)}</p>' in text
        index = text[text.index('<div class="post-families') :]
        index = index[: index.index("</section>")]
        assert index.count('<div class="post-family">') == len(site.STATCAN_GROUPS)
        assert index.count("<li>") == len(families)
        linked = set(re.findall(r'tools\.html#t-([a-z0-9_]+)"', text))
        assert linked and linked <= tool_names
        boxes = re.findall(r"<pre tabindex=\"0\"><code>(.*?)</code></pre>", text, re.DOTALL)
        assert len(boxes) >= 12
        for box in boxes:
            plain = html.unescape(re.sub(r"<[^>]+>", "", box))
            json.loads(
                "\n".join(ln for ln in plain.split("\n") if not ln.lstrip().startswith("//"))
            )


def test_case_captures_are_complete():
    """Each case study is recorded calls with their source and, for the first, scripts."""
    import json

    french = [path.stem for path in site.CASES_DIR.glob("*_fr.json")]
    # A French capture stands in for a case on the French pages, so it needs its case.
    assert {key.removesuffix("_fr") for key in french} <= set(site.CASE_KEYS)
    for key in (*site.CASE_KEYS, *french, "counts", "statcan", site.POLICY_RATE):
        case = json.loads((site.CASES_DIR / f"{key}.json").read_text(encoding="utf-8"))
        assert case["captured"] and case["calls"], key
        for call in case["calls"]:
            assert call["name"], key
            response = call["response"]
            provenance = (response[0] if isinstance(response, list) else response)["provenance"]
            assert provenance["url"].startswith("https://"), key
        if key == "counts":
            continue
        first = case["calls"][0]
        # A web page the tool parses has no script, only reproduce_code's note why.
        assert {"r", "python"} <= set(first["scripts"]) or first["script_notes"], key


def test_french_captures_match_their_english_day():
    """A <key>_fr capture is recorded with <key>, so both pages show one day's data."""
    import json

    for path in site.CASES_DIR.glob("*_fr.json"):
        french = json.loads(path.read_text(encoding="utf-8"))
        english = site.load_case(path.stem.removesuffix("_fr"))
        assert french["captured"] == english["captured"], path.name


def test_capturing_a_case_captures_its_french_twin():
    spec = importlib.util.spec_from_file_location(
        "capture_cases", ROOT / "scripts" / "capture_cases.py"
    )
    assert spec and spec.loader
    capture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(capture)
    assert capture.with_twins(["cards"]) == ["cards", "cards_fr"]
    assert capture.with_twins(["cards_fr", "boc"]) == ["cards", "cards_fr", "boc"]
    assert capture.with_twins(["boc", "boc"]) == ["boc"]
    # Every French capture on disk has a twin in CASES, so a recapture keeps them in step.
    for path in site.CASES_DIR.glob("*_fr.json"):
        assert path.stem in capture.CASES and path.stem.removesuffix("_fr") in capture.CASES


def test_build_refuses_an_output_that_holds_sources(tmp_path: Path):
    """The build replaces its output wholesale; it must never replace sources."""
    for out in (
        ROOT,
        ROOT.parent,
        ROOT / "site",
        ROOT / "site" / "out",
        ROOT / "src",
        ROOT / "src" / "maplestats_mcp",
        ROOT / "site" / "..",
    ):
        with pytest.raises(SystemExit):
            site.safe_out(out)
    assert site.safe_out(ROOT / "build" / "site") == ROOT / "build" / "site"
    assert site.safe_out(tmp_path / "site") == (tmp_path / "site").resolve()


async def test_failed_build_keeps_the_last_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    out = tmp_path / "site"
    out.mkdir()
    (out / "index.html").write_text("old", encoding="utf-8")

    def broken(stage: Path, *args: object) -> int:
        (stage / "index.html").write_text("half", encoding="utf-8")
        raise RuntimeError("render failed")

    monkeypatch.setattr(site, "_write_site", broken)
    with pytest.raises(RuntimeError):
        await site.build(out)
    assert (out / "index.html").read_text(encoding="utf-8") == "old"
    assert [p.name for p in tmp_path.iterdir()] == ["site"]


def test_agent_prompt_is_the_same_everywhere():
    """The setup prompt reads word for word the same on the site and in the README."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert f"> {site.AGENT_PROMPT['en']}" in readme
    for page in ("index.html", "connect.html"):
        template = (site.SITE / page).read_text(encoding="utf-8")
        assert "{{agent_prompt}}" in template, page


def test_french_pages_link_to_french_pages():
    """A French page's links stay in fr/; only the language switch goes to English."""
    page = (
        '<html lang="fr" data-root="../"><link href="../assets/site.css" rel="stylesheet">'
        '<a href="../tools.html#t-wds_search_cubes">x</a> <a href="../index.html#how">y</a>'
        '<a class="lang" href="../cases.html" hreflang="en">English</a>'
        '<a href="https://example.org/a.html">z</a>'
    )
    out = site.french_links(page)
    assert 'href="tools.html#t-wds_search_cubes"' in out
    assert 'href="index.html#how"' in out
    assert 'href="../cases.html" hreflang="en"' in out
    assert 'href="../assets/site.css"' in out
    assert 'href="https://example.org/a.html"' in out
    assert 'data-pages=""' in out


# --------------------------------------------------------------------------
# French pages read as French.
# --------------------------------------------------------------------------

# Common English words and the site's own English labels. On a French page,
# English is allowed only inside code or an element marked lang="en" (the
# server's English docstrings, the planner's plan, reproduce_code's notes).
ENGLISH_MARKERS = re.compile(
    r"\b(?:the|and|of|with|from|this|that|you|your|is|are|to|for)\b"
    r"|\b(?:Use for|Keywords|Request|Response|Show|Copy|Copied|Caveat|Result|Value|tools)\b"
    r"|\b(?:queried|Queried|Source URL)\b|\bSource:"
    r"|\b(?:January|February|March|April|June|July|August|September|October|November|December)\b"
)
# Names that contain such words and stay as they are in French.
ALLOWED_NAMES = re.compile(
    r"Bank of Canada Valet|Model Context Protocol|Beyond 20/20"
    r"|\b[a-z0-9]+(?:_[a-z0-9]+)+\b"  # tool and argument names
)
_LITERAL = {"script", "style", "code", "pre", "kbd", "samp"}
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta"}
_VOID |= {"source", "wbr"}
_TEXT_ATTRS = ("title", "aria-label", "placeholder", "alt")


class _FrenchText(HTMLParser):
    """The text a reader of a page sees in French: text and text attributes."""

    def __init__(self) -> None:
        super().__init__()
        self.stack: list[tuple[str, str, bool]] = [("", "", False)]
        self.chunks: list[str] = []

    def _french(self) -> bool:
        lang = next((lang for _, lang, _ in reversed(self.stack) if lang), "")
        return lang.startswith("fr") and not self.stack[-1][2]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        literal = self.stack[-1][2] or tag in _LITERAL
        self.stack.append((tag, values.get("lang") or "", literal))
        if self._french():
            self.chunks += [values[a] or "" for a in _TEXT_ATTRS if values.get(a)]
            if tag == "meta" and values.get("name") == "description":
                self.chunks.append(values.get("content") or "")
        if tag in _VOID:
            self.stack.pop()

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self.stack.pop()

    def handle_endtag(self, tag: str) -> None:
        if any(name == tag for name, _, _ in self.stack[1:]):
            while self.stack.pop()[0] != tag:
                pass

    def handle_data(self, data: str) -> None:
        # Collapse ASCII whitespace only: the no-break spaces are what is checked.
        text = re.sub(r"[ \t\r\n]+", " ", data).strip(" ")
        if text.strip() and self._french():
            self.chunks.append(text)


def french_text(page: Path) -> list[str]:
    parser = _FrenchText()
    parser.feed(page.read_text(encoding="utf-8"))
    return parser.chunks


@pytest.fixture(scope="module")
def built_site(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("built") / "site"
    asyncio.run(site.build(out))
    return out


def test_french_pages_have_no_unmarked_english(built_site: Path):
    """English on a French page is either code or inside a lang="en" element."""
    pages = sorted((built_site / "fr").glob("*.html"))
    assert pages
    leaks = []
    for page in pages:
        for chunk in french_text(page):
            if ENGLISH_MARKERS.search(ALLOWED_NAMES.sub("", chunk)):
                leaks.append(f"fr/{page.name}: {chunk[:120]}")
    assert not leaks, "English on French pages:\n" + "\n".join(leaks[:25])


def test_french_pages_space_their_punctuation(built_site: Path):
    """No plain space where French wants a no-break one, and none missing."""
    problems = []
    for page in sorted((built_site / "fr").glob("*.html")):
        for chunk in french_text(page):
            # A plain space before the mark, or no space at all.
            plain = re.search(r" [:;?!%»]|« |\w[;?!](?:\s|$)|\w:(?:\s|$)|\d%", chunk)
            if plain:
                problems.append(f"fr/{page.name}: …{chunk[max(0, plain.start() - 30) :][:70]}")
    assert not problems, "French punctuation spacing:\n" + "\n".join(problems[:25])


def test_french_punctuation_rules():
    fix = site.french_punctuation
    nb, nnb = "\u00a0", "\u202f"
    assert fix("Le plus simple : demandez") == f"Le plus simple{nb}: demandez"
    assert fix("directement; chaque chiffre") == f"directement{nnb}; chaque chiffre"
    assert fix("depuis 2020?") == f"depuis 2020{nnb}?"
    assert fix("13,3 %") == f"13,3{nnb}%"
    assert fix("«texte»") == f"«{nb}texte{nb}»"
    # URLs, times, codes and a mark already spaced are left alone.
    for same in ("https://ouvert.canada.ca", "EPSG:4326", "a;b", f"fin{nb}: suite", "18 h 27"):
        assert fix(same) == same
    # A mark at the start of a text follows a tag: it is spaced if a word precedes.
    assert fix(": notes", before="e") == f"{nb}: notes"
    assert fix(": notes", before=" ") == ": notes"


def test_french_typography_skips_code_and_english():
    page = (
        '<html lang="fr"><p title="Note: x">Résultat: <code>a: b</code>'
        '<span lang="en">Source: here</span> fin?</p><script>if(a?b:c);</script></html>'
    )
    out = site.french_typography(page)
    assert 'title="Note\u00a0: x"' in out
    assert "Résultat\u00a0: <code>a: b</code>" in out
    assert '<span lang="en">Source: here</span>' in out
    assert "fin\u202f?" in out
    assert "<script>if(a?b:c);</script>" in out


def _snippet_json(page: str, code_id: str) -> dict[str, Any]:
    match = re.search(rf'<code id="{code_id}">(.*?)</code>', page, re.DOTALL)
    assert match, code_id
    return json.loads(html.unescape(re.sub(r"<[^>]+>", "", match.group(1))))


def test_install_links_match_the_snippets(built_site: Path):
    """Both one-click links decode to the launch command the snippets show."""
    for page in ("index.html", "connect.html", "fr/index.html", "fr/connect.html"):
        text = (built_site / page).read_text(encoding="utf-8")
        cursor = _snippet_json(text, "cl-cursor-1")["mcpServers"]["maplestats"]
        vscode = _snippet_json(text, "cl-vscode-1")["servers"]["maplestats"]
        assert cursor["args"] == vscode["args"] == site.UVX_ARGS, page
        assert " ".join([cursor["command"], *cursor["args"]]) == site.UVX_COMMAND, page
        assert f"-- {site.UVX_COMMAND}</code>" in text, page

        href = re.search(r'href="(cursor://[^"]+)"', text)
        assert href, page
        query = parse_qs(urlsplit(html.unescape(href.group(1))).query)
        assert query["name"] == ["maplestats"], page
        assert json.loads(base64.b64decode(query["config"][0])) == cursor, page

        href = re.search(r'href="vscode:mcp/install\?([^"]+)"', text)
        assert href, page
        config = json.loads(unquote(html.unescape(href.group(1))))
        expected = {"name": "maplestats", "command": vscode["command"], "args": vscode["args"]}
        assert config == expected, page


# --------------------------------------------------------------------------
# The browser's search is the server's, run by node on the shipped files.
# --------------------------------------------------------------------------

# Words whose casefold() differs from a plain lower-casing, beside the usual.
FOLD_SAMPLES = [
    "Stra\u00dfe",
    "STRASSE",
    "Gro\u00dfhandel \u1e9e",
    "\u03a3\u038a\u03a3\u03a5\u03a6\u039f\u03a3",
    "\u1fb3 \u1fbc",
    "\u0152uvres compl\u00e8tes",
    "h\u00f4pitaux",
    "\ufb01nance",
    "journaux, prix et taux",
]

_NODE_SEARCH = """
const fs = require("fs");
const [siteJs, indexPath] = process.argv.slice(1);
const { tokenize, rank } = require(siteJs);
const index = JSON.parse(fs.readFileSync(indexPath, "utf8"));
const { queries, samples } = JSON.parse(fs.readFileSync(0, "utf8"));
process.stdout.write(JSON.stringify({
  ranked: queries.map((q) => rank(index, q).slice(0, index.top).map((i) => index.tools[i][0])),
  tokens: samples.map(tokenize),
}));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_site_js_search_matches_the_python_search(built_site: Path):
    """site.js, loaded by node, tokenizes and ranks as search.py and search_tools do.

    test_site_search_ranks_like_search_tools ties the Python ranking to the
    live search_tools; this ties the shipped JavaScript to that ranking.
    """
    node = shutil.which("node")
    assert node
    index_path = built_site / "assets" / "search-index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    queries = [*QUERIES, *FOLD_SAMPLES]
    result = subprocess.run(
        [node, "-e", _NODE_SEARCH, str(built_site / "assets" / "site.js"), str(index_path)],
        input=json.dumps({"queries": queries, "samples": FOLD_SAMPLES}),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=60,
    )
    got = json.loads(result.stdout)
    for query, names in zip(queries, got["ranked"], strict=True):
        expected = [index["tools"][i][0] for i in site.rank(index, query)[: index["top"]]]
        assert names == expected, query
    for sample, tokens in zip(FOLD_SAMPLES, got["tokens"], strict=True):
        assert tokens == site.tokenize(sample), sample


# --------------------------------------------------------------------------
# Accessibility and metadata of the built pages.
# --------------------------------------------------------------------------


def _pages(built_site: Path) -> list[Path]:
    pages = sorted(built_site.glob("*.html")) + sorted((built_site / "fr").glob("*.html"))
    return [p for p in pages if p.name != "404.html"]


def test_every_page_has_canonical_and_social_metadata(built_site: Path):
    pages = _pages(built_site)
    assert len(pages) == 2 * len(list((ROOT / "site").glob("*.html")))
    for page in pages:
        text = page.read_text(encoding="utf-8")
        lang = "fr" if page.parent.name == "fr" else "en"
        url = site.page_url(page.name, lang)
        where = f"{lang}/{page.name}"
        assert url.startswith(site.SITE_URL), where
        assert f'<link rel="canonical" href="{url}">' in text, where
        assert f'<meta property="og:url" content="{url}">' in text, where
        for code, other in (("en", "en"), ("fr", "fr"), ("x-default", "en")):
            href = site.page_url(page.name, other)
            assert f'<link rel="alternate" hreflang="{code}" href="{href}">' in text, where
        assert '<meta property="og:type" content="website">' in text, where
        locale, alternate = ("en_CA", "fr_CA") if lang == "en" else ("fr_CA", "en_CA")
        assert f'<meta property="og:locale" content="{locale}">' in text, where
        assert f'<meta property="og:locale:alternate" content="{alternate}">' in text, where
        assert '<meta name="twitter:card" content="summary_large_image">' in text, where
        assert f'<meta property="og:image" content="{site.SITE_URL}assets/og.png">' in text
        title = re.search(r"<title>(.*?)</title>", text)
        description = re.search(r'<meta name="description" content="([^"]*)">', text)
        og_title = re.search(r'<meta property="og:title" content="([^"]*)">', text)
        og_description = re.search(r'<meta property="og:description" content="([^"]*)">', text)
        assert title and description and og_title and og_description, where
        assert og_title.group(1) == title.group(1).strip(), where
        assert og_description.group(1) == description.group(1), where
        assert "\x00" not in text, where
    image = site.SITE / "assets" / "og.png"
    header = image.read_bytes()[:24]
    assert header[:8] == b"\x89PNG\r\n\x1a\n"
    assert int.from_bytes(header[16:20], "big") == 1200
    assert int.from_bytes(header[20:24], "big") == 630
    assert image.stat().st_size < 150_000


def test_sitemap_robots_and_not_found_page(built_site: Path):
    sitemap = (built_site / "sitemap.xml").read_text(encoding="utf-8")
    locs = re.findall(r"<loc>([^<]+)</loc>", sitemap)
    expected = [
        site.page_url(p.name, lang) for p in (ROOT / "site").glob("*.html") for lang in site.LANGS
    ]
    assert sorted(locs) == sorted(expected)
    robots = (built_site / "robots.txt").read_text(encoding="utf-8")
    assert f"Sitemap: {site.SITE_URL}sitemap.xml" in robots
    missing = (built_site / "404.html").read_text(encoding="utf-8")
    base = "/maplestats-mcp/"
    assert f'href="{base}assets/site.css"' in missing
    assert f'href="{base}fr/"' in missing and '<section lang="fr">' in missing
    # Every link and asset is absolute: the page is served at any depth.
    assert not re.findall(r'(?:href|src)="(?!/|https://)', missing)


def test_scrolling_boxes_take_keyboard_focus(built_site: Path):
    """Every code block and every table box can be reached, and scrolled, by keyboard."""
    for page in _pages(built_site):
        text = page.read_text(encoding="utf-8")
        where = page.relative_to(built_site)
        assert not re.search(r"<pre\b(?![^>]*tabindex)", text), where
        assert not re.search(r'<div class="cmd\b[^"]*">\s*<code\b(?![^>]*tabindex)', text), where
        for wrap in re.finditer(r'<div class="table-wrap[^"]*"([^>]*)>', text):
            attrs = wrap.group(1)
            assert 'role="region"' in attrs and 'tabindex="0"' in attrs, where
            label = re.search(r'aria-labelledby="([^"]+)"', attrs)
            assert label and f'<caption id="{label.group(1)}"' in text[wrap.end() :], where


def test_table_boxes_need_a_caption():
    with pytest.raises(SystemExit):
        site.focusable_scrollers('<div class="table-wrap"><table><thead></thead></table></div>')
    out = site.focusable_scrollers(
        '<pre><code>x</code></pre><div class="table-wrap post-wide"><table class="t">'
        '<caption class="sr">Cap</caption></table></div>'
    )
    assert '<pre tabindex="0">' in out
    assert 'role="region" aria-labelledby="tbl-1" tabindex="0"' in out
    assert '<caption id="tbl-1" class="sr">Cap</caption>' in out


def test_tab_panels_ship_visible_and_named(built_site: Path):
    """Without scripts every panel shows, headed by its tab's name."""
    for page in _pages(built_site):
        text = page.read_text(encoding="utf-8")
        panels = re.findall(r'<div role="tabpanel"[^>]*>', text)
        assert all(" hidden" not in panel for panel in panels), page
        assert text.count('<p class="tab-name">') == len(panels), page


def test_every_chart_is_followed_by_its_data(built_site: Path):
    for page in (built_site / "cases.html", built_site / "fr" / "cases.html"):
        text = page.read_text(encoding="utf-8")
        charts = re.findall(r'<svg\b[^>]*class="chart[^"]*"[^>]*>', text)
        # Nine charts; all but the square are drawn twice (wide and narrow, see
        # site_charts.responsive), and every drawing links the same table.
        wide = [svg for svg in charts if "chart-narrow" not in svg]
        assert len(wide) == 9, page
        assert len({re.search(r'aria-details="([^"]+)"', s).group(1) for s in wide}) == 9  # type: ignore[union-attr]
        for svg in charts:
            ident = re.search(r'aria-details="([^"]+)"', svg)
            assert ident, svg[:80]
            table = text.index(f'<details class="chart-data" id="{ident.group(1)}">')
            assert "<caption" in text[table : table + 600]
    french = (built_site / "fr" / "cases.html").read_text(encoding="utf-8")
    assert "<summary>Voir les donn\u00e9es</summary>" in french
    # French numbers: a comma for decimals, a narrow no-break space before %.
    assert re.search(r'<td class="num">\d+,\d\u202f%</td>', french)


def test_pages_make_no_third_party_requests(built_site: Path):
    """Fonts, scripts and styles come from the site itself, not a CDN.

    The one exception is the badges: live images from the services that
    list or score the server, lazily loaded, and only from BADGE_HOSTS.
    """
    fonts_css = (built_site / "assets" / "fonts.css").read_text(encoding="utf-8")
    for url in re.findall(r"url\(([^)]+)\)", fonts_css):
        assert (built_site / "assets" / url).is_file(), url
    for page in [*built_site.glob("*.html"), *(built_site / "fr").glob("*.html")]:
        text = page.read_text(encoding="utf-8")
        loaded = re.findall(r'<(?:link|script)\b[^>]*(?:href|src)="(https?://[^"]+)"', text)
        # Canonical, hreflang and og: URLs name this site; they load nothing.
        foreign = [u for u in loaded if not u.startswith(site.SITE_URL)]
        assert not foreign, (page.name, foreign)
        for img in re.findall(r'<img\b[^>]*src="https?://[^"]+"[^>]*>', text):
            src = html.unescape(re.search(r'src="([^"]+)"', img).group(1))  # type: ignore[union-attr]
            assert urlsplit(src).netloc in site.BADGE_HOSTS, (page.name, src)
            assert 'loading="lazy"' in img, (page.name, src)


def test_badges_match_the_readme(built_site: Path):
    """The site shows the README's badges, and the README shows the site's."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    in_readme = {html.unescape(u) for u in re.findall(r'<img src="(https://[^"]+)"', readme)}
    listed = {image for _, _, image, _, _ in site.BADGES}
    assert listed <= in_readme, listed - in_readme
    # Every README badge but the logo is on the site.
    assert {u for u in in_readme if "logo.svg" not in u} <= listed
    for page, group in (
        ("index.html", "user"),
        ("connect.html", "user"),
        ("contributing.html", "dev"),
    ):
        for lang_dir in ("", "fr/"):
            text = html.unescape((built_site / lang_dir / page).read_text(encoding="utf-8"))
            for grp, link, image, alt_en, alt_fr in site.BADGES:
                if grp == group:
                    assert f'src="{image}"' in text, (lang_dir + page, image)
                    assert (alt_fr if lang_dir else alt_en) in text, (lang_dir + page, alt_en)


def test_llms_txt_links_each_tool_to_its_entry(built_site: Path):
    text = (built_site / "llms.txt").read_text(encoding="utf-8")
    tools_page = (built_site / "tools.html").read_text(encoding="utf-8")
    links = re.findall(r"^- \[([^\]]+)\]\(([^)]+)\)", text, re.MULTILINE)
    anchors = [
        url.split("#", 1)[1] for _, url in links if url.startswith(site.SITE_URL + "tools.html#")
    ]
    assert len(anchors) == len(re.findall(r'<details class="tool" id="t-', tools_page))
    for anchor in anchors:
        assert f'id="{anchor}"' in tools_page, anchor
    for _, url in links:
        assert url.startswith(site.SITE_URL), url


def test_stylesheets_close_every_block():
    """Each section of a stylesheet starts at the top level.

    A merge once dropped the closing brace of `@media print`; browsers close
    an open block at the end of the file, so every rule after it silently
    applied to print only.
    """
    for sheet in (ROOT / "site" / "assets").glob("*.css"):
        depth = 0
        text = re.sub(
            r"/\*(?!\s*-{5,}).*?\*/", "", sheet.read_text(encoding="utf-8"), flags=re.DOTALL
        )
        for match in re.finditer(r"[{}]|/\*\s*-{5,}", text):
            token = match.group(0)
            if token == "{":
                depth += 1
            elif token == "}":
                depth -= 1
                assert depth >= 0, sheet.name
            else:
                line = text[: match.start()].count("\n") + 1
                assert depth == 0, f"{sheet.name}: section at line {line} opens inside a block"
        assert depth == 0, sheet.name


def test_demos_join_several_agencies(built_site: Path):
    """Each demo shows its recorded plan, charts with data, and every agency it asked."""
    agencies = {
        "alberta-rent": (
            "Statistics Canada",
            "Alberta Economic Dashboard",
            "Immigration, Refugees and Citizenship Canada",
            "Canada Mortgage and Housing Corporation",
        ),
        "rate-hikes": (
            "Bank of Canada",
            "Canada Mortgage and Housing Corporation",
            "Statistics Canada",
        ),
    }
    text = (built_site / "demos.html").read_text(encoding="utf-8")
    sections = re.split(r'<section class="wrap stanza demo" id="', text)[1:]
    assert [s.split('"', 1)[0] for s in sections] == list(agencies)
    for section in sections:
        key = section.split('"', 1)[0]
        assert "plan_query" in section and 'class="plan"' in section, key
        sources = section[section.index('<ul class="demo-sources">') :]
        for agency in agencies[key]:
            assert f"<strong>{agency}</strong>" in sources, (key, agency)
        # The joined table: one row per year, a heading per series with its agency.
        join = section[section.index('class="table-wrap demo-join"') :]
        assert join.count('<span class="demo-agency">') >= len(agencies[key]), key
        assert len(re.findall(r'<tr><th scope="row">20\d\d</th>', join)) >= 5, key
        # Every data call carries scripts; the plan does not.
        assert section.count('class="demo-scripts"') == section.count("Request: ") - 1, key
        assert "{{" not in section, key
    french = (built_site / "fr" / "demos.html").read_text(encoding="utf-8")
    assert "Banque du Canada" in french and 'aria-current="page">Démos' in french
