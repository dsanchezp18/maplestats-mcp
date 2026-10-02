"""Alberta general election results from Elections Alberta's official results site.

Checked live 2026-10-01 against officialresults.elections.ab.ca for the general elections
of 2008 (EventId 12), 2012 (21), 2015 (31), 2019 (60) and 2023 (101):

- orResultsPGE.cfm?EventId=N is one page with a province total row and one row per
  electoral division: ED code (a link to orResultsED.cfm), name, voting locations (or
  polls), one vote count per party and the turnout. Party codes are the column headers
  and a table at the end of the page decodes them. The HTML is old and unbalanced
  (upper-case tags, unclosed cells, bare '&' in links), so it is read with regular
  expressions over the text that follows each tag, not with an HTML tree. A party with
  no candidate shows 0 (or an empty cell), which cannot be told from zero votes, so zero
  columns are dropped.
- orWinningCandidates.cfm?EventId=N lists the winner of each division with name, party and
  votes. It is the only place the summary pages name candidates; per-division pages name
  all of them but would take 87 requests for one election.

The division's candidate with the most votes is the elected one; the winners page supplies
the name when its vote count matches (they did for all 87 divisions in 2023).
"""

from __future__ import annotations

import html
import re

from maplestats_mcp.modules.elections_provincial import constants
from maplestats_mcp.modules.elections_provincial.common import (
    Candidate,
    District,
    fetch_bytes,
    finish_shares,
    mark_winners,
)
from maplestats_mcp.shared.errors import UpstreamError

_FLAGS = re.IGNORECASE
_ROW_START = re.compile(r"<tr[\s>]", _FLAGS)
_ED_LINK = re.compile(r"orResultsED\.cfm\?ED=([^&\"]+)&", _FLAGS)
_HEADER_CELL = re.compile(r"<th(?:\s[^>]*)?>([^<]*)", _FLAGS)
_CELL = re.compile(r"<td(?:\s[^>]*)?>([^<]*)", _FLAGS)
_WINNER_ROW = re.compile(
    r"<tr>\s*<td>(\d+)</td>\s*<td>([^<]*)</td>\s*<td[^>]*>([^<]*)</td>\s*"
    r"<td>([^<]*)</td>\s*<td>([^<]*)</td>",
    _FLAGS,
)
_PARTY_ROW = re.compile(r"<td>([^<]+)</td>\s*<td>([^<]+)</td>", _FLAGS)


def results_url(event_id: str) -> str:
    return f"{constants.AB_BASE}/orResultsPGE.cfm?EventId={event_id}"


def winners_url(event_id: str) -> str:
    return f"{constants.AB_BASE}/orWinningCandidates.cfm?EventId={event_id}"


def _text(cell: str) -> str:
    return html.unescape(cell).replace("\xa0", " ").strip()


def _counts(cell: str) -> list[int]:
    """Vote counts in one cell: usually one, several for independents in the same district."""
    return [int(float(token.replace(",", ""))) for token in _text(cell).split()]


def parse_winners(page: str) -> dict[str, tuple[str, int]]:
    """Winner name and votes by ED code."""
    return {
        code: (_text(name), _counts(votes)[0])
        for code, _ed, name, _party, votes in _WINNER_ROW.findall(page)
    }


def parse_results(page: str, winners: dict[str, tuple[str, int]]) -> list[District]:
    start = page.lower().find('id="datatbl"')
    if start < 0:
        raise UpstreamError("elections_provincial: Alberta results page has no results table.")
    table = page[start:]
    first_row = _ED_LINK.search(table)
    if first_row is None:
        raise UpstreamError("elections_provincial: Alberta results page has no division rows.")

    headers = [_text(h) for h in _HEADER_CELL.findall(table[: first_row.start()])]
    # Headers read ED, ED Name, Voting (Locations) or Number (of Polls), the party codes
    # and Voter (Turnout).
    codes = headers[3:-1]
    if len(codes) < 2:
        raise UpstreamError("elections_provincial: Alberta results table has no party columns.")

    names = dict(_PARTY_ROW.findall(table[table.lower().find("party name") :]))
    names = {_text(k): _text(v) for k, v in names.items()}

    districts: list[District] = []
    for chunk in _ROW_START.split(table):
        link = _ED_LINK.search(chunk)
        if link is None:
            continue
        cells = [_text(c) for c in _CELL.findall(chunk)]
        if len(cells) != len(codes) + 4:
            raise UpstreamError(
                f"elections_provincial: Alberta division {link.group(1)} has {len(cells)} "
                f"cells, expected {len(codes) + 4}."
            )
        ed_code = link.group(1)
        district = District(name=cells[1], number=ed_code)
        turnout = cells[-1]
        district.turnout = float(turnout) if turnout else None
        winner = winners.get(ed_code)
        for code, cell in zip(codes, cells[3:-1], strict=True):
            for votes in _counts(cell):
                if votes == 0:
                    continue
                district.candidates.append(
                    Candidate(
                        name=None,
                        party=names.get(code, code),
                        party_code=code,
                        votes=votes,
                        share=None,
                    )
                )
        mark_winners(district)
        if winner is not None:
            for candidate in district.candidates:
                if candidate.elected and candidate.votes == winner[1]:
                    candidate.name = winner[0]
        finish_shares(district)
        districts.append(district)
    if not districts:
        raise UpstreamError("elections_provincial: Alberta results page has no divisions.")
    return districts


async def fetch(event_id: str) -> list[District]:
    context = f"elections_provincial:ab:{event_id}"
    page = (await fetch_bytes(results_url(event_id), context=context)).decode(
        "utf-8", errors="replace"
    )
    winners_page = (await fetch_bytes(winners_url(event_id), context=context)).decode(
        "utf-8", errors="replace"
    )
    return parse_results(page, parse_winners(winners_page))
