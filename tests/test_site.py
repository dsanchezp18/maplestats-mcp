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
