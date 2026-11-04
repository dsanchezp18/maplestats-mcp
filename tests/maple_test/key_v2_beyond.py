"""The Maple Test v2 questions beyond Statistics Canada and the Bank of Canada.

Two source files read each publisher directly, never through MapleStats:
sources_v2_a.py (ECCC climate and hydrometric data, the World Bank, BIS) and
sources_v2_b.py (Health Canada's Drug Product Database, IRCC Express Entry rounds,
the 2021 Census of Population). This module joins them and adds what the grader needs
for answers that are names or refusals rather than numbers.
"""

from __future__ import annotations

from typing import Any

from tests.maple_test import sources_v2_a, sources_v2_b

# Grading hints, by the source files' own ids. A name answer (a brand, a status) passes when
# the name appears; a refusal passes on its own wording for "this does not exist"; a flag
# question names its warning sign.
_HINTS: dict[str, dict[str, Any]] = {
    # A flag question that asks for a figure passes only with the figure (figure_required):
    # a flag alone is partial. The station-closure pattern once matched "connection
    # closed" (a tool error), so a closure must now be tied to the station or the year.
    "A-04": {
        "flag_pattern": r"(?:station|6158733)[^.]{0,80}(?<!connection )(?:clos(?:ed|ure)|"
        r"discontinu|decommission)|(?<!connection )(?:clos(?:ed|ure)|discontinu|"
        r"decommission)[^.]{0,80}(?:station|2013)|no longer report|stopped report|"
        r"6158731|successor|replacement station|replaced by",
        "figure_required": True,
    },
    "B-01": {"answer_contains": True},
    "B-02": {"answer_contains": True},
    "B-03": {"answer_contains": True},
    "B-04": {
        "absent_pattern": r"cancel+ed|no longer (?:sold|marketed|available|on the market)|"
        r"discontinued|not (?:currently )?marketed|withdrawn|nobody|no one|no company",
    },
    "B-08": {
        "absent_pattern": r"(?:has(?:n't| not)|have(?:n't| not)|not) (?:yet )?(?:been )?held|"
        r"(?:has(?:n't| not)|not) (?:yet )?taken place|no (?:such )?round|"
        r"(?:does(?:n't| not)|did(?:n't| not)) (?:yet )?exist|not (?:yet )?happened",
    },
    "B-12": {
        "flag_pattern": r"(?:no|not yet|hasn't|has not|haven't|have not|isn't|is not|aren't|"
        r"are not)[^.]{0,50}(?:2026 census|released|published|available|out yet)|"
        r"2026 census[^.]{0,80}(?:not|n't|until|due|expected)",
        "figure_required": True,
    },
}


def questions() -> list[dict[str, Any]]:
    out = []
    for q in [*sources_v2_a.questions(), *sources_v2_b.questions()]:
        out.append({**q, **_HINTS.get(q["id"], {}), "source_id": q["id"], "group": "beyond"})
    return out
