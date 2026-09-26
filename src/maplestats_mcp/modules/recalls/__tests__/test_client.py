"""Tests for modules/recalls/client.py, shaped on live 2026-09-26 payloads."""

from __future__ import annotations

from datetime import date

import httpx
import pytest

from maplestats_mcp.modules.recalls import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError

EN_URL = constants.DUMP_URLS["en"]
FR_URL = constants.DUMP_URLS["fr"]
MODIFIED = {"Last-Modified": "Sat, 26 Sep 2026 02:19:23 GMT"}


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


def _en(nid, title, org, category, *, product=None, issue="", cls="", updated=None, archived="0"):
    return {
        "NID": nid,
        "Title": title,
        "URL": f"https://recalls-rappels.canada.ca/en/alert-recall/{nid}",
        "Organization": org,
        "Product": product,
        "Issue": issue,
        "What you should do": "",
        "Category": category,
        "Recall class": cls,
        "Last updated": updated,
        "Archived": archived,
    }


# Rows copied from the live English dump, trimmed. Quirks kept: padded
# titles, &amp; entities, null Product, null Last updated (Transport
# Canada), "--" recall class, a class range, zero-width spaces.
EN_ROWS = [
    _en(
        "82667",
        "Go! Beanz brand Roasted Broadbeans recalled due to undeclared milk",
        "CFIA",
        "Candy, confectionary, snacks and sweeteners",
        product="Roasted Broadbeans (Ketchup and Salt &amp; Pepper flavors)",
        issue="Milk",
        cls="Class 3",
        updated="2026-09-24",
    ),
    _en(
        "82686",
        "Sanofi-Aventis Canada Inc. recalling certain insulin pens and cartridges",
        "Communications and Public Affairs Branch",
        "Biologic or vaccine",
        issue="Product safety",
        cls="Type I - Type II",
        updated="2026-09-25",
    ),
    _en(
        "82680",
        "Transport Canada Recall - 2026432 - FORD",
        "TC",
        "Light Truck & Van",
        product="Light Truck & Van recalled by FORD",
        issue="Fuel System",
        updated="2026-09-23",
    ),
    _en("67746", "Transport Canada Recall - 2018078 - ", "TC", "Light Truck & Van"),
    _en(
        "82650",
        "\u200b\u200bINMO AIR3 Smart Glasses \u200brecalled due to burn hazard",
        "Consumer product safety",
        "Electronics",
        issue="Burn hazard",
        cls="--",
        updated="2026-09-24",
    ),
    _en(
        "62944",
        "  Trichome JWC recalls one lot of Wagners Blue Lime Pie dried cannabis ",
        "Controlled substances and cannabis",
        "Cannabis",
        issue="Suspected quality concern",
        updated="2021-10-28",
    ),
    _en(
        "48704",
        "  Certain Safie's brand Sweet Pickled Beets may contain pieces of glass ",
        "CFIA",
        "Food",
        issue="Extraneous material",
        cls="Class 2",
        updated="2011-12-30",
        archived="1",
    ),
    _en(
        "70001",
        "Health Canada warns about unauthorized products",
        "Communications and Public Affairs Branch",
        "Household items",
        updated="2024-03-01",
    ),
]

FR_ROWS = [
    {
        "NID": "82667",
        "Titre": "Rappel de gourganes grillées de marque Go! Beanz en raison de la présence "
        "non déclarée de lait",
        "URL": "https://recalls-rappels.canada.ca/fr/avis-rappel/82667",
        "Organization": "ACIA",
        "Produit": "Gourganes grillées",
        "Problème": "Lait",
        "Ce que vous devriez faire": "",
        "Catégorie": "Bonbons, confiseries, collations et édulcorants",
        "Classe de rappel": "Classe 3",
        "Dernière mise à jour": "2026-09-24",
        "Archivé": "0",
    },
    {
        "NID": "44621",
        "Titre": "  Présence possible de la bactérie E. coli O157:H7 dans divers produits de "
        "BŒUF HACHÉ ",
        # The one live French row whose URL is a bare /fr/node/ path.
        "URL": "https://recalls-rappels.canada.ca/fr/node/44621",
        "Organization": "ACIA",
        "Produit": None,
        "Problème": "E.\u00a0coli O157:H7",
        "Ce que vous devriez faire": "",
        "Catégorie": "Aliments",
        "Classe de rappel": "Classe 1",
        "Dernière mise à jour": "2012-09-25",
        "Archivé": "1",
    },
]


def _dump(httpx_mock, rows=EN_ROWS, url=EN_URL):
    httpx_mock.add_response(url=url, json=rows, headers=MODIFIED)


async def test_search_cleans_rows_sorts_newest_and_hides_archived(httpx_mock):
    _dump(httpx_mock)
    result = await client.search(limit=10)
    ids = [r.recall_id for r in result.recalls]
    # Newest last-updated first; the dateless TC row last; archived 48704 hidden.
    assert ids == [82686, 82667, 82650, 82680, 70001, 62944, 67746]
    assert result.total_matched == 7
    beans = result.recalls[1]
    assert beans.product == "Roasted Broadbeans (Ketchup and Salt & Pepper flavors)"
    assert (beans.agency, beans.product_types, beans.recall_class) == ("cfia", ["food"], "Class 3")
    glasses = result.recalls[2]
    assert glasses.title == "INMO AIR3 Smart Glasses recalled due to burn hazard"
    assert glasses.recall_class is None
    assert result.recalls[6].last_updated is None
    assert result.provenance.as_of is not None and result.provenance.as_of.year == 2026
    assert "archived" in (result.provenance.coverage or "")


async def test_derived_agency_product_type_and_tc_number(httpx_mock):
    _dump(httpx_mock)
    result = await client.search(include_archived=True, limit=50)
    by_id = {r.recall_id: r for r in result.recalls}
    assert by_id[82686].agency == "health_canada"
    assert by_id[82686].product_types == ["health_product"]
    # Cannabis is a consumer product on the site, not a health product.
    assert by_id[62944].product_types == ["consumer_product"]
    # Communications-branch advisory on household items -> consumer product.
    assert by_id[70001].product_types == ["consumer_product"]
    assert by_id[82680].tc_recall_number == "2026432"
    assert by_id[67746].tc_recall_number == "2018078"
    assert by_id[82667].tc_recall_number is None


async def test_filters(httpx_mock):
    _dump(httpx_mock)
    assert [r.recall_id for r in (await client.search("MILK beans")).recalls] == [82667]
    vehicles = await client.search(product_type="vehicle")
    assert {r.recall_id for r in vehicles.recalls} == {82680, 67746}
    # A date filter drops notices with no date.
    dated = await client.search(agency="transport_canada", updated_from="2026-01-01")
    assert [r.recall_id for r in dated.recalls] == [82680]
    # "Type I" matches one side of a range but never "Type II" alone.
    assert [r.recall_id for r in (await client.search(recall_class="type i")).recalls] == [82686]
    archived = await client.search(recall_class="Class 2", include_archived=True)
    assert [r.recall_id for r in archived.recalls] == [48704]
    assert (await client.search(recall_class="Class 2")).total_matched == 0
    toys = await client.search(category="electro")
    assert [r.recall_id for r in toys.recalls] == [82650]
    paged = await client.search(limit=2, offset=2)
    assert [r.recall_id for r in paged.recalls] == [82650, 82680]
    assert paged.total_matched == 7


async def test_french_dump_folds_accents_and_class_names(httpx_mock):
    _dump(httpx_mock, FR_ROWS, FR_URL)
    boeuf = await client.search("boeuf hache", include_archived=True, lang="fr")
    assert [r.recall_id for r in boeuf.recalls] == [44621]
    row = boeuf.recalls[0]
    assert row.issue == "E. coli O157:H7"
    assert row.title.startswith("Présence possible")
    assert (row.agency, row.product_types) == ("cfia", ["food"])
    classe = await client.search(recall_class="Class 3", lang="fr")
    assert [r.recall_id for r in classe.recalls] == [82667]


async def test_summarize_groups(httpx_mock):
    _dump(httpx_mock)
    years = await client.summarize("year")
    assert [(g.key, g.count) for g in years.groups] == [
        ("2011", 1),
        ("2021", 1),
        ("2024", 1),
        ("2026", 4),
        ("unknown", 1),
    ]
    assert years.total_matched == 8
    agencies = await client.summarize("agency", include_archived=False)
    assert [(g.key, g.count) for g in agencies.groups] == [
        ("health_canada", 4),
        ("transport_canada", 2),
        ("cfia", 1),
    ]
    classes = await client.summarize("recall_class", top=2)
    assert classes.groups[0].key == "(none)" and classes.groups_total == 4
    assert "first 2 of 4" in (classes.provenance.limits or "")


async def test_validation(httpx_mock):
    with pytest.raises(InvalidInput):
        await client.search(limit=0)
    with pytest.raises(InvalidInput):
        await client.summarize("brand")
    with pytest.raises(InvalidInput):
        await client.get_recall("RA-82667")
    with pytest.raises(InvalidInput):
        await client.get_recall("abc")
    _dump(httpx_mock)
    with pytest.raises(InvalidInput):
        await client.search(agency="fda")  # type: ignore[arg-type]
    with pytest.raises(InvalidInput):
        await client.search(updated_from="2026/01/01")
    with pytest.raises(InvalidInput):
        await client.search(updated_from="2026-02-01", updated_to="2026-01-01")


async def test_dump_format_change_and_outage_raise(httpx_mock):
    httpx_mock.add_response(url=EN_URL, json=[{"NID": "1", "Titre": "x"}])
    with pytest.raises(UpstreamError, match="format changed"):
        await client.search()
    httpx_mock.add_response(url=EN_URL, status_code=404)
    with pytest.raises(UpstreamError):
        await client.search()


async def test_dump_is_cached(httpx_mock):
    _dump(httpx_mock)
    first = await client.search()
    second = await client.summarize("agency")
    assert (first.provenance.cached, second.provenance.cached) == (False, True)


# Trimmed from the live current-layout page for NID 82667 (English).
CURRENT_PAGE = """<html><body><main>
<div class="region region-header"><div class="h3" id="wb-cont-nav">Notification</div>
<h1 class="gc-thickline" id="wb-cont"><span>Go! Beanz brand Roasted Broadbeans recalled due to
undeclared milk</span></h1></div>
<details class="ar-brand-details"><div class="field field--name-field-brand-ref field--items">
<div class="field--item"><a href="/en/search/site?f%5B1%5D=brand%3A4937">Go! Beanz</a></div>
</div></details>
<div class="field field--name-field-last-updated field--label-inline">
<div class="field--label">Last updated</div>
<div class="field field--name-field-last-updated field--item">
<time datetime="2026-09-24T12:00:00Z">2026-09-24</time></div></div>
<section class="ar-summary ar-section"><h2>Summary</h2>
<div class="field field--name-field-product field--label-inline"><div class="field--label">Product</div>
<div class="field field--name-field-product field--item">Roasted Broadbeans (Ketchup and Salt &amp;
Pepper flavors)</div></div>
<div class="field field--name-field-issue-type field--label-inline"><div class="field--label">Issue</div>
<div class="field field--name-field-issue-type field--items">
<div class="field--item">Food - Allergen - Milk</div></div></div>
<div class="field field--name-field-action field--label-inline"><div class="field--label">What to do</div>
<div class="field field--name-field-action field--item"><p>Do not use, sell, serve or distribute the
affected products.</p></div></div>
<div class="field field--name-field-distribution-region field--items">
<div class="field--item">New Brunswick</div><div class="field--item">Ontario</div></div>
</section>
<section class="ar-affected-products ar-section"><h2>Affected products</h2>
<table><thead><tr><th><p>Brand</p></th><th><p>Product</p></th><th><p>UPC</p></th></tr></thead>
<tbody><tr><td><p>Go! Beanz</p></td><td><p>Roasted Broadbeans Ketchup</p></td>
<td><p>Best before: JUN/14/2028<br>LOT: JSCA26005</p></td></tr></tbody></table></section>
<section class="ar-issue-long ar-section"><h2>Issue</h2>
<div class="field field--name-field-issue-long field--item"><p>Recalled due to <a href="#x">undeclared
milk</a>.</p></div></section>
<section class="ar-additional-info ar-section"><h2>Additional information</h2>
<details><summary>Details</summary>
<div><strong class="views-label views-label-changed">Original published date: </strong>
<time datetime="2026-09-25T11:07:31-04:00">2026-09-25</time></div>
<div class="field field--name-field-recall-type field--item">Notification</div>
<div class="field field--name-field-category field--items">
<div class="field--item">Food - Candy, confectionary, snacks and sweeteners</div></div>
<div class="field field--name-field-companies field--item"><p>Recalling firm: Jimmy Sévigny Inc.</p></div>
<div class="field field--name-node-id field--label-inline"><div class="field--label">Published by</div>
<div class="field--item"><span class="field field--name-field-organization field--item">Canadian Food
Inspection Agency</span></div></div>
<div class="field field--label-inline"><div class="field--label">Recall class</div>
<div class="field--item"><div class="field field--name-field-hazard-type field--items">
<div class="field--item">Class 3</div></div></div></div>
<div class="field field--label-inline"><div class="field--label">Recall date</div>
<div class="field--item"><div class="field field--name-field-recall-date field--item">
<time datetime="2026-09-22T12:00:00Z">2026-09-22</time></div></div></div>
<div class="field field--name-node-id field--label-inline"><div class="field--label">Identification
number</div><div class="field--item">RA-82667</div></div>
<div class="field field--label-inline"><div class="field--label"><span class="field
field--name-field-organization field--item">Canadian Food Inspection Agency</span> ID</div>
<div class="field--item"><div class="field field--name-field-cfia-id field--items">
<div class="field--item">17541</div></div></div></div>
</details></section>
</main></body></html>"""

# Trimmed from the live legacy (migrated) page for NID 48704 (French).
LEGACY_PAGE = """<html><body><main>
<div id="block-archived"><section class="alert alert-warning" id="archived">
<h2>Cette page Web a été archivée dans le Web</h2></section></div>
<div class="h3" id="wb-cont-nav">Notification</div>
<h1 class="gc-thickline" id="wb-cont"><span>  Certains Betteraves Marinées Sucrées de marque Safie's
</span></h1>
<div class="recall-alert-body"><div class="field field--name-body field--item">
<dl id="awr_details_header_container">
<dt>Date de début :</dt><dd>30 décembre 2011</dd>
<dt>Classification du risque :</dt><dd>Classe 2</dd>
<dt>Source :</dt><dd>Agence Canadienne d'Inspection des Aliments</dd>
</dl>
<h2 id="affected-touches">Produits touchés</h2>
<table><tr><th>Nom de marque</th><th>CUP</th></tr>
<tr><td>Safie's</td><td>0 41798 00145 9</td></tr></table>
<!-- Date Modified ends / Fin de la date de modification -->
<h2>Demandes des médias</h2><p>Relations avec les médias de l'ACIA<br>613-773-6600</p>
</div></div></main></body></html>"""


async def test_get_recall_follows_node_redirect_and_parses_current_page(httpx_mock):
    final = "https://recalls-rappels.canada.ca/en/alert-recall/go-beanz"
    httpx_mock.add_response(
        url=constants.NODE_URL.format(lang="en", nid=82667),
        status_code=302,
        headers={"Location": final},
    )
    httpx_mock.add_response(url=final, text=CURRENT_PAGE)
    detail = await client.get_recall(82667)
    assert (detail.layout, detail.url, detail.archived) == ("current", final, False)
    assert detail.title == "Go! Beanz brand Roasted Broadbeans recalled due to undeclared milk"
    assert detail.product == "Roasted Broadbeans (Ketchup and Salt & Pepper flavors)"
    assert detail.issue == ["Food - Allergen - Milk"]
    assert detail.category == ["Food - Candy, confectionary, snacks and sweeteners"]
    assert detail.what_to_do == "Do not use, sell, serve or distribute the affected products."
    assert detail.distribution == ["New Brunswick", "Ontario"]
    assert detail.brands == ["Go! Beanz"]
    assert (detail.recall_class, detail.agency, detail.alert_type) == (
        "Class 3",
        "cfia",
        "Notification",
    )
    assert detail.published_by == "Canadian Food Inspection Agency"
    assert detail.recall_date == date(2026, 9, 22)
    assert detail.last_updated == date(2026, 9, 24)
    assert detail.first_published == date(2026, 9, 25)
    assert detail.identification_number == "RA-82667"
    assert detail.agency_reference is not None
    assert detail.agency_reference.label == "Canadian Food Inspection Agency ID"
    assert detail.agency_reference.value == "17541"
    assert detail.tables[0].columns == ["Brand", "Product", "UPC"]
    assert detail.tables[0].rows == [
        ["Go! Beanz", "Roasted Broadbeans Ketchup", "Best before: JUN/14/2028; LOT: JSCA26005"]
    ]
    # Links stay inline; the table is not repeated in the section text.
    assert [(s.heading, s.text) for s in detail.sections] == [
        ("Issue", "Recalled due to undeclared milk.")
    ]


async def test_get_recall_parses_legacy_page(httpx_mock):
    httpx_mock.add_response(url=constants.NODE_URL.format(lang="fr", nid=48704), text=LEGACY_PAGE)
    detail = await client.get_recall("48704", lang="fr")
    assert (detail.layout, detail.archived) == ("legacy", True)
    assert detail.title == "Certains Betteraves Marinées Sucrées de marque Safie's"
    assert detail.details[0].label == "Date de début"
    assert detail.details[0].value == "30 décembre 2011"
    assert (detail.recall_class, detail.agency) == ("Classe 2", "cfia")
    assert detail.tables[0].columns == ["Nom de marque", "CUP"]
    assert detail.tables[0].rows == [["Safie's", "0 41798 00145 9"]]
    assert detail.legacy_text and "613-773-6600" in detail.legacy_text
    assert "Date Modified" not in detail.legacy_text


async def test_get_recall_unknown_and_non_recall_nodes(httpx_mock):
    httpx_mock.add_response(url=constants.NODE_URL.format(lang="en", nid=1), status_code=404)
    with pytest.raises(NotFound):
        await client.get_recall(1)
    httpx_mock.add_response(
        url=constants.NODE_URL.format(lang="en", nid=2),
        text="<html><main><h1>RSS feeds</h1><p>Subscribe</p></main></html>",
    )
    with pytest.raises(NotFound, match="not a recall"):
        await client.get_recall(2)


async def test_get_recall_retries_then_reports_outage(httpx_mock):
    url = constants.NODE_URL.format(lang="en", nid=3)
    for _ in range(3):
        httpx_mock.add_exception(httpx.ConnectTimeout("slow"), url=url)
    with pytest.raises(Exception, match="could not be reached"):
        await client.get_recall(3)
