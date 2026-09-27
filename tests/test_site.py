"""The website generator (scripts/build_site.py) must stay in step with the server.

Its hand-kept tables (SOURCES, FAMILIES, PORTAL_PLACES) must cover every
module, sub-API and portal, and the search it ships to the browser must
rank tools exactly as search_tools does, because the site says it does.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

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

    for key in (*site.CASE_KEYS, "counts", "statcan"):
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
