"""Tests for ircc/backlog/client.py, shaped on the live page read 2026-11-14."""

from __future__ import annotations

from datetime import date

import pytest

from maplestats_mcp.modules.ircc.backlog import client, constants
from maplestats_mcp.shared.errors import InvalidInput, UpstreamError, UpstreamUnavailable

# (English heading, French heading) of the seven tables, in the page's order.
_HEADINGS = (
    (
        "Backlog of federal high-skilled (Express Entry) applications",
        "Travailleurs hautement qualifiés (fédéral)",
    ),
    (
        "Backlog Provincial Nominee Program (Express&nbsp;Entry)",
        "Programme des candidats des provinces (Entrée express)",
    ),
    ("Backlog of spouses, partners and children", "Époux, conjoints de fait ou enfants à charge"),
    ("Backlog of citizenship grant applications", "Demandes de citoyenneté"),
    ("Backlog of temporary resident visas (TRV)", "Visa de résident temporaire (VRT)"),
    ("Backlog of study permits", "Permis d’études"),
    ("Backlog of work permits", "Permis de travail"),
)

_EN_ROWS = (("Jan 22", "89%", "-"), ("Aug 22", "90%", "86%"), ("Oct 25", "-", "20%"))
_FR_ROWS = (("janv. 22", "89 %", "-"), ("août 22", "90 %", "86 %"), ("oct. 25", "-", "20 %"))


def _page(lang: str = "en", rows=None, headings=None, drop: int = 0) -> str:
    header = ("Month", "Backlog (Actual)", "Backlog (Projected)")
    if lang == "fr":
        header = ("Mois", "Arriéré (Réel)", "Arriéré (Projeté)")
    body = rows or (_EN_ROWS if lang == "en" else _FR_ROWS)
    out = ["<html><body><h3>Page title</h3><ul><li>x</li></ul>"]
    for heading_en, heading_fr in (headings or _HEADINGS)[: len(_HEADINGS) - drop]:
        heading = heading_en if lang == "en" else heading_fr
        out.append(f"<h3>{heading}</h3><iframe src='x'></iframe><details><summary>s</summary>")
        out.append("<table><thead><tr>")
        out.extend(f'<th scope="col">{c}</th>' for c in header)
        out.append("</tr></thead><tbody>")
        for month, actual, projected in body:
            out.append(
                f'<tr><th scope="row">{month}</th><td>{actual}</td><td>{projected}</td></tr>'
            )
        out.append("</tbody></table></details>")
    out.append("<table><tr><th>Other</th><td>1</td></tr></table></body></html>")
    return "".join(out)


def _mock(httpx_mock, markup: str, lang: str = "en", status: int = 200) -> None:
    url = constants.PAGE_URL_EN if lang == "en" else constants.PAGE_URL_FR
    httpx_mock.add_response(url=url, text=markup, status_code=status, is_reusable=True)


def test_parse_english_page_reads_seven_programs_and_dashes() -> None:
    parsed = client.parse_page(_page("en"), "en")
    assert list(parsed) == [p[0] for p in constants.PROGRAMS]
    rows = parsed["express_entry_federal"]
    assert [r.month for r in rows] == [date(2022, 1, 1), date(2022, 8, 1), date(2025, 10, 1)]
    assert (rows[0].backlog_actual_pct, rows[0].backlog_projected_pct) == (89.0, None)
    assert (rows[1].backlog_actual_pct, rows[1].backlog_projected_pct) == (90.0, 86.0)
    assert (rows[2].backlog_actual_pct, rows[2].backlog_projected_pct) == (None, 20.0)


def test_parse_french_page_reads_spaced_percentages_and_month_names() -> None:
    parsed = client.parse_page(_page("fr"), "fr")
    rows = parsed["work_permit"]
    assert [r.month for r in rows] == [date(2022, 1, 1), date(2022, 8, 1), date(2025, 10, 1)]
    assert rows[0].backlog_actual_pct == 89.0
    assert rows[2].backlog_projected_pct == 20.0


def test_parse_ignores_tables_that_are_not_backlog_tables() -> None:
    assert len(client.parse_page(_page("en"), "en")) == 7


def test_parse_raises_when_a_table_is_missing() -> None:
    with pytest.raises(UpstreamError, match="6 program tables found, expected 7"):
        client.parse_page(_page("en", drop=1), "en")


def test_parse_raises_on_unknown_heading() -> None:
    headings = (("Percentage of something else", "Autre chose"), *_HEADINGS[1:])
    with pytest.raises(UpstreamError, match="matches no known program"):
        client.parse_page(_page("en", headings=headings), "en")


def test_parse_raises_on_unreadable_value_and_month() -> None:
    with pytest.raises(UpstreamError, match="neither a percentage"):
        client.parse_page(_page("en", rows=(("Jan 22", "n/a", "-"),)), "en")
    with pytest.raises(UpstreamError, match="not like 'Jan 22'"):
        client.parse_page(_page("en", rows=(("Q1 2022", "5%", "-"),)), "en")


@pytest.mark.asyncio
async def test_get_backlog_filters_program_and_months(httpx_mock) -> None:
    _mock(httpx_mock, _page("en"))
    result = await client.get_backlog("provincial nominee", since="2022-06", until="2025-10")
    assert [p.program_id for p in result.programs] == ["express_entry_pnp"]
    assert [r.month for r in result.rows] == [date(2022, 8, 1), date(2025, 10, 1)]
    program = result.programs[0]
    assert program.last_actual_month == date(2022, 8, 1)
    assert program.last_projected_month == date(2025, 10, 1)
    assert any("not a processing time" in note for note in result.notes)
    assert result.provenance.url == constants.PAGE_URL_EN


@pytest.mark.asyncio
async def test_get_backlog_french_labels(httpx_mock) -> None:
    _mock(httpx_mock, _page("fr"), lang="fr")
    result = await client.get_backlog("work_permit", lang="fr")
    assert result.programs[0].label == "Permis de travail"
    assert result.provenance.url == constants.PAGE_URL_FR


@pytest.mark.asyncio
async def test_get_backlog_rejects_bad_arguments_before_fetching() -> None:
    with pytest.raises(InvalidInput, match="matches several programs"):
        await client.get_backlog("permit")
    with pytest.raises(InvalidInput, match="matches no program"):
        await client.get_backlog("zzz")
    with pytest.raises(InvalidInput, match="since must be a month"):
        await client.get_backlog(since="last year")


@pytest.mark.asyncio
async def test_get_backlog_upstream_errors(httpx_mock) -> None:
    _mock(httpx_mock, "gone", status=404)
    with pytest.raises(UpstreamError, match="HTTP 404"):
        await client.get_backlog()


@pytest.mark.asyncio
async def test_get_backlog_upstream_5xx_is_unavailable(httpx_mock) -> None:
    _mock(httpx_mock, "down", status=503)
    with pytest.raises(UpstreamUnavailable):
        await client.get_backlog()


@pytest.mark.asyncio
async def test_get_backlog_argument_errors_are_french_for_a_french_call() -> None:
    # _parse_bound and _program_ids raised English-only messages whatever `lang` said.
    with pytest.raises(InvalidInput, match="Entrée invalide.*since doit être un mois"):
        await client.get_backlog(since="last year", lang="fr")
    with pytest.raises(InvalidInput, match="Entrée invalide.*until doit être un mois"):
        await client.get_backlog(until="2024-13", lang="fr")
    with pytest.raises(InvalidInput, match="Entrée invalide.*correspond à plusieurs programmes"):
        await client.get_backlog("permit", lang="fr")
    with pytest.raises(InvalidInput, match="Entrée invalide.*ne correspond à aucun programme"):
        await client.get_backlog("zzz", lang="fr")
