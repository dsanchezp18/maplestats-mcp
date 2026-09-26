"""MCP tools for the Canada Gazette."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.gazette import client, constants
from maplestats_mcp.modules.gazette.schemas import IssueList, IssueNotices, NoticeText

Lang = Literal["en", "fr"]
Part = Literal[1, 2]


@tool
async def gazette_list_issues(
    part: Part = 1, limit: int = constants.ISSUES_DEFAULT, lang: Lang = "en"
) -> IssueList:
    """List recent Canada Gazette issues (Part I notices, Part II regulations).

    Use for: finding an issue date to open with gazette_get_issue. Part I
    (weekly, Saturdays) carries government notices, commission notices
    and proposed regulations; Part II (every second Wednesday) carries
    registered regulations (SOR) and statutory instruments (SI).
    Keywords: Canada Gazette, government notices, proposed regulations,
    regulations, SOR, orders in council, official publication, Part I.
    Mots-clés : Gazette du Canada, avis du gouvernement, projets de
    règlement, règlements, DORS, décrets, publication officielle, Partie I.
    """
    return await client.list_issues(part, limit=limit, lang=lang)


@tool
async def gazette_get_issue(
    part: Part = 1, issue_date: str | None = None, lang: Lang = "en"
) -> IssueNotices:
    """List every notice or regulation in one Canada Gazette issue.

    Use for: seeing what was published on a date (default: the latest
    issue), grouped by section (government notices, commissions,
    proposed regulations, miscellaneous notices) with the department
    and act for Part I, or the SOR/SI instruments for Part II.
    `issue_date` is YYYY-MM-DD from gazette_list_issues.
    Keywords: Canada Gazette issue, table of contents, notices,
    regulations, department, act, SOR, SI, publication date.
    Mots-clés : édition de la Gazette du Canada, table des matières,
    avis, règlements, ministère, loi, DORS, TR.
    """
    return await client.get_issue(part, issue_date, lang)


@tool
async def gazette_get_notice(url: str, lang: Lang = "en") -> NoticeText:
    """Read the text of one Canada Gazette notice or regulation.

    Use for: the wording of a notice, proposed regulation (with its
    Regulatory Impact Analysis Statement) or registered regulation.
    `url` comes from gazette_get_issue; the language follows the URL
    (open the French issue for French text).
    Keywords: Canada Gazette notice text, regulation text, RIAS, regulatory
    impact, proposed regulation, order, Canada Gazette, notice.
    Mots-clés : texte de l'avis, texte du règlement, REIR, résumé de l'étude
    d'impact, projet de règlement, décret, Gazette du Canada, avis.
    """
    return await client.get_notice(url, lang)
