"""The website generator (scripts/build_site.py) must stay in step with the server.

Its hand-kept tables (SOURCES, FAMILIES, PORTAL_PLACES) must cover every
module, sub-API and portal, and the search it ships to the browser must
rank tools exactly as search_tools does, because the site says it does.
The French pages must read as French: English only where it is marked.
"""

from __future__ import annotations

import asyncio
import importlib.util
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

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
        boxes = re.findall(r"<pre><code>(.*?)</code></pre>", text, re.DOTALL)
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
