"""check_answer: the last call before an answer that reports figures."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.answer_check import client
from maplestats_mcp.modules.answer_check.schemas import AnswerCheck, CitedFigure


@tool
async def check_answer(
    question: str,
    figures: list[CitedFigure],
    summed: bool = False,
    lang: Literal["en", "fr"] = "en",
) -> AnswerCheck:
    """Check an answer's figures against the source before replying: call it
    once, with the question and every figure the answer will report.

    Use for: verifying the numbers in a draft answer. Each figure gives
    `value`, `unit` and `period` as the answer writes them, `geography`
    if known, and its source: `vector_id`, or `product_id` + `coordinate`
    (StatCan), or `boc_series` (Bank of Canada). The server re-reads them
    and returns only problems, each with a fix (an empty list when clean):
    value differs from the published one, a missed scale (thousands), a
    newer period published, a series for another place than the question
    names (each figure against its own `geography`, else the places asked),
    a table with no member for the place (with the tables to search), an
    unadjusted series where an adjusted one exists, E, F or suppressed
    flags, current vs constant or chained dollars, an index given as
    dollars, surveys that should not be compared, and figures known not
    to be published at the asked geography, with where they could come
    from (public microdata, custom tabulation, RTRA, RDC). `summed=True`
    says the answer adds the figures together. `value` null means the
    answer will say the figure is not published. Only StatCan and Bank of
    Canada figures are checked: others come back in `notes` as not
    checked, with nothing to fix.
    Keywords: check my answer, verify figures, fact-check, validate
    numbers, sanity check, before replying, wrong value, outdated figure,
    newer period, geography mismatch, not published, custom tabulation.
    Mots-clés : vérifier ma réponse, vérifier les chiffres, contrôle des
    chiffres, valider une réponse, chiffre erroné, données périmées,
    dernière période, géographie, non publié, totalisation personnalisée.
    """
    return await client.check_answer(question, figures, summed, lang)
