"""Quebec general election results from Elections Quebec's open data.

Checked live 2026-10-01: https://donnees.electionsquebec.qc.ca/production/provincial/
resultats/archives/gen<YYYY-MM-DD>/resultats.json exists for the 14 general elections
from 1973-10-29 to 2022-10-03 (the same files the site's result pages read). Each has
`statistiques` (province totals and a `partisPolitiques` list with party names) and
`circonscriptions` (one entry per riding with `candidats` already sorted by votes, and
`nbElecteurInscrit`, `nbVoteValide`, `nbVoteRejete`, `tauxParticipation`). The 1973 to 2012
files omit the 2014 onward fields (numeroCandidat, party numbers, update stamps). No file
flags the winner, so the candidate with the most votes is the elected one (125 of 125 in
2022 reconcile with the CAQ 90, PLQ 21, QS 11, PQ 3 seat counts).
"""

from __future__ import annotations

import json
from typing import Any

from maplestats_mcp.modules.elections_provincial import constants
from maplestats_mcp.modules.elections_provincial.common import (
    Candidate,
    District,
    fetch_bytes,
    finish_shares,
    mark_winners,
)
from maplestats_mcp.shared.errors import UpstreamError


def file_url(source_key: str) -> str:
    return f"{constants.QC_BASE}/gen{source_key}/resultats.json"


def _int(value: Any) -> int | None:
    return None if value in (None, "") else int(value)


def _float(value: Any) -> float | None:
    return None if value in (None, "") else float(value)


def parse(body: bytes) -> list[District]:
    try:
        data = json.loads(body.decode("utf-8"))
        ridings = data["circonscriptions"]
    except (UnicodeDecodeError, ValueError, KeyError, TypeError) as exc:
        raise UpstreamError(f"elections_provincial: unexpected Quebec results file: {exc}") from exc

    names = {
        str(p.get("abreviationPartiPolitique")): str(p["nomPartiPolitique"])
        for p in data.get("statistiques", {}).get("partisPolitiques", [])
        if p.get("abreviationPartiPolitique") and p.get("nomPartiPolitique")
    }
    districts: list[District] = []
    for riding in ridings:
        district = District(
            name=str(riding["nomCirconscription"]),
            number=str(riding["numeroCirconscription"]),
            electors=_int(riding.get("nbElecteurInscrit")),
            valid_votes=_int(riding.get("nbVoteValide")),
            rejected_ballots=_int(riding.get("nbVoteRejete")),
            turnout=_float(riding.get("tauxParticipation")),
        )
        for entry in riding.get("candidats", []):
            code = entry.get("abreviationPartiPolitique")
            full_name = " ".join(
                part for part in (entry.get("prenom"), entry.get("nom")) if part
            ).strip()
            district.candidates.append(
                Candidate(
                    name=full_name or None,
                    party=names.get(str(code), code),
                    party_code=code,
                    votes=int(entry["nbVoteTotal"]),
                    share=_float(entry.get("tauxVote")),
                )
            )
        mark_winners(district)
        finish_shares(district)
        districts.append(district)
    if not districts:
        raise UpstreamError("elections_provincial: the Quebec results file has no ridings.")
    return districts


async def fetch(source_key: str) -> list[District]:
    body = await fetch_bytes(file_url(source_key), context=f"elections_provincial:qc:{source_key}")
    return parse(body)
