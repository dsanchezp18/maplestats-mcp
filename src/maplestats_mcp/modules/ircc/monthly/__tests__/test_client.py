"""Tests on rows trimmed from the live IRCC files (2026-09-25)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from maplestats_mcp.modules.ircc.monthly import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError

_HERE = Path(__file__).parent
_PR = (_HERE / "pr_pt_immcat.tsv").read_bytes()
_PR_URL = constants.FILE_PREFIX + "ODP-PR-PT_IMMCAT.csv"
_CATALOGUE = {
    "success": True,
    "result": {
        "count": 2,
        "results": [
            {
                "id": "f7e5498e",
                "title": "Permanent Residents – Monthly IRCC Updates",
                "title_translated": {
                    "en": "Permanent Residents – Monthly IRCC Updates",
                    "fr": "Résidents permanents – Mises à jour mensuelles d’IRCC",
                },
                "resources": [
                    {
                        "format": "CSV",
                        "url": _PR_URL,
                        "name": "[rounded - not for calculations]  Canada - PR by province",
                        "name_translated": {"fr": "[arrondi] Canada - RP par province"},
                    },
                    {"format": "XLSX", "url": constants.FILE_PREFIX + "EN_ODP-PR.xlsx"},
                ],
            },
            {
                "id": "01c85d28",
                "title": "(ARCHIVED) Syrian Refugees – Monthly IRCC Updates",
                "resources": [
                    {"format": "CSV", "url": constants.FILE_PREFIX + "ODP-Syrian.csv", "name": "x"}
                ],
            },
        ],
    },
}


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


@pytest.fixture
def catalogue(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.CKAN_SEARCH_URL}?q=title%3A%22Monthly+IRCC+Updates%22&rows=50",
        json=_CATALOGUE,
        is_reusable=True,
    )


@pytest.fixture
def live(httpx_mock, catalogue):
    httpx_mock.add_response(url=_PR_URL, content=_PR, is_reusable=True)


def test_parse_long_table():
    parsed = client.parse_table(_PR)
    assert [d.key for d in parsed.dimensions] == [
        "province_territory",
        "immigration_category_main_category",
    ]
    assert parsed.periods == ["month", "quarter", "year"]
    assert parsed.rows[0].value == 1205 and parsed.rows[0].month == 7
    assert parsed.rows[2].value is None  # '--'
    assert parsed.dimensions[0].fr["Quebec"] == "Québec"


def test_parse_value_column_before_dimensions_and_unpaired_column():
    parsed = client.parse_table((_HERE / "dli.tsv").read_bytes())
    assert [d.key for d in parsed.dimensions] == [
        "dli_province_territory",
        "designated_learning_instituion",
    ]
    assert parsed.dimensions[1].column_fr is None
    assert [r.value for r in parsed.rows] == [10070, None]


def test_parse_comma_file_ignores_copy_columns():
    parsed = client.parse_table((_HERE / "copies.csv").read_bytes())
    assert [d.key for d in parsed.dimensions] == ["age"]
    assert parsed.rows[0].value == 20


def test_lumped_english_label_keeps_rows_and_falls_back_in_french():
    body = (
        b"EN_CENSUS_METROPOLITAN_AREA\tFR_REGION\tTOTAL\n"
        b"Other - Ontario\tWeak metropolitan influenced zone (Ontario)\t5200\n"
        b"Other - Ontario\tModerate metropolitan influenced zone (Ontario)\t4185\n"
    )
    parsed = client.parse_table(body)
    assert [r.value for r in parsed.rows] == [5200, 4185]
    assert parsed.dimensions[0].fr["Other - Ontario"] == "Other - Ontario"


def test_headerless_file_is_reported():
    with pytest.raises(UpstreamError, match="header"):
        client.parse_table((_HERE / "headerless.tsv").read_bytes())


async def test_catalogue_strips_brackets_and_hides_archived(catalogue):
    result = await client.list_tables()
    assert [t.table_id for t in result.tables] == ["ODP-PR-PT_IMMCAT"]
    assert result.tables[0].title == "Canada - PR by province"
    assert result.total_tables == 2
    everything = await client.list_tables(include_archived=True, lang="fr")
    assert everything.tables[-1].archived
    assert everything.tables[0].dataset.startswith("Résidents permanents")


async def test_describe(live):
    result = await client.describe_table("odp-pr-pt_immcat.csv")
    assert result.first_period == "2025-12" and result.last_period == "2026-07"
    assert result.suppressed_cells == 2
    assert result.dimensions[0].values == ["Alberta", "Quebec"]


async def test_query_rows_are_chronological_and_keep_latest(live):
    result = await client.query_table("ODP-PR-PT_IMMCAT", limit=2)
    assert [r.period for r in result.rows] == ["2026-07", "2026-07"]
    assert result.total_matched == 7


async def test_query_filters_in_french_and_totals_by_year(live):
    result = await client.query_table(
        "ODP-PR-PT_IMMCAT",
        {"province_territory": "Québec"},
        period="year",
        group_by=[],
        lang="fr",
    )
    assert result.applied_filters == {"EN_PROVINCE_TERRITORY": "Quebec"}
    by_year = {r.period: (r.value, r.suppressed_cells) for r in result.rows}
    assert by_year == {"2025": (None, 1), "2026": (900, 1)}


async def test_query_group_and_rank(live):
    result = await client.query_table(
        "ODP-PR-PT_IMMCAT",
        year_from=2026,
        period="quarter",
        group_by=["province_territory"],
        sort="value_desc",
    )
    top = result.rows[0]
    assert (top.period, top.dimensions, top.value, top.cells) == (
        "2026-Q3",
        {"province_territory": "Alberta"},
        1615,
        2,
    )


async def test_bad_inputs(live):
    with pytest.raises(NotFound):
        await client.query_table("ODP-NOPE")
    with pytest.raises(InvalidInput, match="unknown dimension"):
        await client.query_table("ODP-PR-PT_IMMCAT", {"region": "x"})
    with pytest.raises(InvalidInput, match="no value"):
        await client.query_table("ODP-PR-PT_IMMCAT", {"province_territory": "Atlantis"})


async def test_french_errors(live):
    with pytest.raises(NotFound, match="Aucune correspondance trouvée : ircc_monthly : aucun"):
        await client.query_table("ODP-NOPE", lang="fr")
    with pytest.raises(InvalidInput, match="dimension inconnue"):
        await client.query_table("ODP-PR-PT_IMMCAT", {"region": "x"}, lang="fr")
    with pytest.raises(InvalidInput, match="n'a pas de valeur"):
        await client.query_table("ODP-PR-PT_IMMCAT", {"province_territory": "Atlantis"}, lang="fr")
    with pytest.raises(InvalidInput, match="Entrée invalide.*limit doit être"):
        await client.query_table("ODP-PR-PT_IMMCAT", limit=0, lang="fr")
    with pytest.raises(InvalidInput, match="est postérieur à year_to"):
        await client.query_table("ODP-PR-PT_IMMCAT", year_from=2026, year_to=2020, lang="fr")


def test_french_headerless_file_is_reported():
    with pytest.raises(UpstreamError, match="sans ligne d'en-tête"):
        client.parse_table((_HERE / "headerless.tsv").read_bytes(), lang="fr")


async def test_french_note_and_provenance(live):
    result = await client.query_table("ODP-PR-PT_IMMCAT", limit=2, lang="fr")
    assert result.note.startswith("IRCC arrondit")
    assert "(supprimés) ;" in result.note
    assert result.provenance.limits == result.note
    assert result.provenance.freshness is not None
    assert result.provenance.freshness.startswith("mensuelle ; IRCC ajoute")
    catalogue = await client.list_tables(lang="fr")
    assert catalogue.provenance.coverage == "jeux de données archivés exclus"
    assert catalogue.provenance.freshness == "IRCC met à jour les fichiers chaque mois"


async def test_english_note_and_provenance_unchanged(live):
    # limit=3 keeps all of 2026-07's rows; limit=2 would cut through that period, which the
    # note now says (see test_limit_cutting_the_earliest_period_is_said).
    result = await client.query_table("ODP-PR-PT_IMMCAT", limit=3)
    assert result.note == constants.ROUNDING_NOTE
    assert result.provenance.freshness == (
        "monthly; IRCC adds the latest month and may revise earlier ones"
    )


class _CountingStream(httpx.AsyncByteStream):
    """A body with no Content-Length that counts the chunks the client pulled."""

    def __init__(self, chunks: int, size: int) -> None:
        self.chunks, self.size, self.pulled = chunks, size, 0

    async def __aiter__(self):
        for _ in range(self.chunks):
            self.pulled += 1
            yield b"x" * self.size


async def test_oversized_table_stops_at_the_cap_instead_of_loading_it(
    httpx_mock, catalogue, monkeypatch
):
    monkeypatch.setattr(constants, "MAX_FILE_BYTES", 1_000)
    body = _CountingStream(chunks=50, size=500)
    httpx_mock.add_response(url=_PR_URL, stream=body)
    with pytest.raises(UpstreamError, match="larger than 1,000 bytes"):
        await client.describe_table("ODP-PR-PT_IMMCAT")
    assert body.pulled <= 3


_ODD_TOTALS = (
    b"EN_YEAR\tEN_QUARTER\tEN_MONTH\tEN_PROVINCE_TERRITORY\tTOTAL\n"
    b"2026\tQ3\tJul\tAlberta\t1,205\n"
    b"2026\tQ3\tJul\tQuebec\t<5\n"
    b"2026\tQ3\tJul\tOntario\tn/a\n"
    b"2026\tQ3\tJul\tManitoba\t--\n"
)


def test_an_unreadable_total_cell_is_unknown_not_a_failed_table():
    parsed = client.parse_table(_ODD_TOTALS)
    assert [r.value for r in parsed.rows] == [1205, None, None, None]
    # "--" is IRCC's own suppression mark; "<5" and "n/a" are the odd ones.
    assert parsed.unreadable_cells == 2 and parsed.unreadable_example == "<5"


async def test_unreadable_cells_are_reported_in_the_note(httpx_mock, catalogue):
    httpx_mock.add_response(url=_PR_URL, content=_ODD_TOTALS, is_reusable=True)
    described = await client.describe_table("ODP-PR-PT_IMMCAT")
    assert described.suppressed_cells == 1 and described.unreadable_cells == 2
    assert "2 TOTAL cells were not counts" in described.note and "'<5'" in described.note
    queried = await client.query_table("ODP-PR-PT_IMMCAT", lang="fr")
    assert "2 cellules TOTAL n'étaient pas des nombres" in queried.note


# ------------------------------------------------- incomplete periods, odd period cells, limit

_MONTH_ABBR = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _monthly_tsv(*spans: tuple[int, int, int]) -> bytes:
    """One Alberta row of 100 for each month of every (year, first_month, last_month) span."""
    lines = ["EN_YEAR\tEN_QUARTER\tEN_MONTH\tEN_PROVINCE_TERRITORY\tTOTAL"]
    for year, first, last in spans:
        for month in range(first, last + 1):
            quarter = (month - 1) // 3 + 1
            lines.append(f"{year}\tQ{quarter}\t{_MONTH_ABBR[month - 1]}\tAlberta\t100")
    return ("\n".join(lines) + "\n").encode()


async def test_partial_latest_year_is_flagged_and_the_figures_stay(httpx_mock, catalogue):
    # The year sums the months published so far, so 2026 (Jan-Jul) looked like a sharp
    # drop next to 2025 with nothing saying why. The sums themselves must not change.
    httpx_mock.add_response(url=_PR_URL, content=_monthly_tsv((2025, 1, 12), (2026, 1, 7)))
    result = await client.query_table("ODP-PR-PT_IMMCAT", period="year", group_by=[])
    assert {r.period: r.value for r in result.rows} == {"2025": 1200, "2026": 700}
    assert "2026 has 7 of 12 months (Jan to Jul)" in result.note
    assert "2025 has" not in result.note
    assert "2026 has 7 of 12 months" in (result.provenance.limits or "")


async def test_partial_periods_are_flagged_in_french_and_by_quarter(httpx_mock, catalogue):
    httpx_mock.add_response(url=_PR_URL, content=_monthly_tsv((2024, 10, 12), (2025, 1, 12)))
    first = await client.query_table("ODP-PR-PT_IMMCAT", period="year", group_by=[], lang="fr")
    # The first year of the table starts in October, which is also a partial period.
    assert "2024 compte 3 mois sur 12 (oct. à déc.)" in first.note
    assert "2025 compte" not in first.note

    httpx_mock.add_response(url=_PR_URL, content=_monthly_tsv((2026, 1, 7)))
    cache_module._caches.clear()
    quarters = await client.query_table("ODP-PR-PT_IMMCAT", period="quarter", group_by=[])
    assert [(r.period, r.value) for r in quarters.rows] == [
        ("2026-Q1", 300),
        ("2026-Q2", 300),
        ("2026-Q3", 100),
    ]
    assert "2026-Q3 has 1 of 3 months (Jul)" in quarters.note
    assert "2026-Q1" not in quarters.note


async def test_complete_periods_and_the_finest_grain_add_no_note(httpx_mock, catalogue):
    httpx_mock.add_response(url=_PR_URL, content=_monthly_tsv((2025, 1, 12), (2026, 1, 7)))
    by_month = await client.query_table("ODP-PR-PT_IMMCAT")
    assert by_month.note == constants.ROUNDING_NOTE
    full_years = await client.query_table("ODP-PR-PT_IMMCAT", period="year", year_to=2025)
    assert full_years.note == constants.ROUNDING_NOTE


async def test_year_of_a_quarterly_table_is_flagged_by_quarters(httpx_mock, catalogue):
    body = (
        b"EN_YEAR\tEN_QUARTER\tEN_PROVINCE_TERRITORY\tTOTAL\n"
        b"2025\tQ1\tAlberta\t10\n2025\tQ2\tAlberta\t10\n2025\tQ3\tAlberta\t10\n"
        b"2025\tQ4\tAlberta\t10\n2026\tQ1\tAlberta\t10\n2026\tQ2\tAlberta\t10\n"
    )
    httpx_mock.add_response(url=_PR_URL, content=body)
    result = await client.query_table("ODP-PR-PT_IMMCAT", period="year", group_by=[])
    assert "2026 has 2 of 4 quarters (Q1 to Q2)" in result.note


def test_month_and_quarter_cells_in_other_spellings_are_read():
    months = ["January", "Février", "Sept.", "août", "juil.", "mai", "7", "Dec"]
    quarters = ["Q1 2024", "T2", "q3", "Quarter 4", "2024-Q1", "Q1", "Q2", "Q3"]
    body = "EN_YEAR\tEN_QUARTER\tEN_MONTH\tTOTAL\n" + "".join(
        f"2024\t{q}\t{m}\t5\n" for q, m in zip(quarters, months, strict=True)
    )
    parsed = client.parse_table(body.encode())
    assert [r.month for r in parsed.rows] == [1, 2, 9, 8, 7, 5, 7, 12]
    assert [r.quarter for r in parsed.rows] == [1, 2, 3, 4, 1, 1, 2, 3]
    assert all(not r.unread_time for r in parsed.rows)

    quarter_only = "EN_YEAR\tEN_QUARTER\tTOTAL\n" + "".join(
        f"2024\t{q}\t5\n" for q in ("Q1 2024", "T2", "q3", "Quarter 4", "2024-Q1")
    )
    assert [r.quarter for r in client.parse_table(quarter_only.encode()).rows] == [1, 2, 3, 4, 1]


def test_a_quarter_written_right_after_the_year_is_read():
    # "2024Q1" fell into the unread-period row because a digit before the Q was refused;
    # a letter before it still is ("Dept2" is not a T2).
    for text, quarter in (("2024Q1", 1), ("2024q3", 3), ("2025T2", 2), ("2024Quarter 4", 4)):
        assert client._quarter_of(text) == quarter, text
    assert client._quarter_of("Dept2") is None
    assert client._quarter_of("Q12") is None
    assert client._quarter_of("Q1 2024") == 1


async def test_unreadable_periods_are_counted_not_pooled_silently(httpx_mock, catalogue):
    body = (
        b"EN_YEAR\tEN_QUARTER\tEN_MONTH\tEN_PROVINCE_TERRITORY\tTOTAL\n"
        b"2026\tQ1\tJan\tAlberta\t100\n"
        b"2026\tQ1\tSmarch\tAlberta\t40\n"
        b"2026\tQ1\tFlop\tAlberta\t60\n"
    )
    httpx_mock.add_response(url=_PR_URL, content=body, is_reusable=True)
    result = await client.query_table("ODP-PR-PT_IMMCAT", group_by=[])
    # The pooled row stays (figures unchanged), and the note says what it holds.
    assert {r.period: r.value for r in result.rows} == {None: 100, "2026-01": 100}
    assert "2 matched rows have no readable period (for example 'Smarch')" in result.note
    french = await client.query_table("ODP-PR-PT_IMMCAT", group_by=[], lang="fr")
    assert "2 lignes retenues n'ont pas de période lisible (par exemple 'Smarch')" in french.note
    # Rows a filter drops are not counted.
    other = await client.query_table(
        "ODP-PR-PT_IMMCAT", {"province_territory": "Alberta"}, year_from=2027, group_by=[]
    )
    assert "no readable period" not in other.note


async def test_limit_cutting_the_earliest_period_is_said(live):
    # 2026-07 has 3 rows, 2026-06 has 2 and 2025-12 has 2; limit=4 keeps one of 2026-06's.
    cut = await client.query_table("ODP-PR-PT_IMMCAT", limit=4)
    assert [r.period for r in cut.rows] == ["2026-06", "2026-07", "2026-07", "2026-07"]
    assert "earliest period shown, 2026-06, lists 1 of its 2 rows" in cut.note
    assert "limit" in cut.note
    whole = await client.query_table("ODP-PR-PT_IMMCAT", limit=5)
    assert "earliest period shown" not in whole.note
    ranked = await client.query_table("ODP-PR-PT_IMMCAT", limit=4, sort="value_desc")
    assert "earliest period shown" not in ranked.note
