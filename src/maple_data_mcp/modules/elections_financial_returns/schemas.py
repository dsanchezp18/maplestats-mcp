from __future__ import annotations

from pydantic import BaseModel

from maple_data_mcp.shared.models import Provenance


class ElectionOption(BaseModel):
    id: str
    label: str
    group: str | None = None


class ElectionList(BaseModel):
    act: str
    elections: list[ElectionOption]
    provenance: Provenance


class FilterOption(BaseModel):
    id: str
    label: str


class Candidate(BaseModel):
    client_id: str
    last_name: str
    first_name: str
    party: str
    electoral_district: str


class CandidateSearchResult(BaseModel):
    election_id: str
    candidates: list[Candidate]
    returned_count: int
    total_found: int
    available_parties: list[FilterOption]
    available_provinces: list[FilterOption]
    provenance: Provenance


class FinancialReturnPart(BaseModel):
    candidate_client_id: str
    election_id: str
    part_code: str
    part_label: str
    return_status: str
    export_header: dict[str, str]
    sections: dict[str, list[dict[str, object]]]
    provenance: Provenance
