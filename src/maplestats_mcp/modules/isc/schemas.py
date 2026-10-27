"""Typed responses for the ISC / CIRNAC module."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance

AdvisoryKind = Literal["boil_water", "do_not_consume", "do_not_use", "other"]


class FirstNationSummary(BaseModel):
    band_number: int = Field(description="Registry group (band) number, as in the profiles.")
    name: str = Field(description="Registry group name in the language asked for.")
    region: str | None = Field(default=None, description="ISC region.")
    province: str | None = Field(default=None, description="Province or territory.")
    province_code: str | None = None
    district: str | None = Field(default=None, description="ISC district, where one is given.")
    year: int = Field(description="Year of the registered population below.")
    registered_population: int | None = Field(
        default=None, description="Registered under the Indian Act, all residences, that year."
    )
    on_reserve: int | None = Field(
        default=None, description="Registered living on reserve or Crown land."
    )
    off_reserve: int | None = None


class FirstNationList(BaseModel):
    first_nations: list[FirstNationSummary] = Field(default_factory=list)
    returned_count: int
    total_matched: int
    year: int = Field(description="Latest year in the registered population dataset.")
    provenance: Provenance


class TribalCouncil(BaseModel):
    number: int
    name: str


class Reserve(BaseModel):
    number: str = Field(description="Reserve number as published, with leading zeros.")
    name: str
    location: str | None = Field(default=None, description="Legal description as published.")
    hectares: float | None = None


class Official(BaseModel):
    title: str = Field(description="Chief, Councillor, etc. as published.")
    surname: str
    given_name: str
    appointment_date: date | None = None
    expiry_date: date | None = None


class Governance(BaseModel):
    membership_authority: str | None = Field(
        default=None, description="Section 10 or section 11 band (Indian Act)."
    )
    election_system: str | None = Field(
        default=None,
        description="Indian Act, First Nations Elections Act, custom or self-government.",
    )
    council_quorum: str | None = Field(
        default=None, description="A number, or the page's note when not published."
    )
    officials: list[Official] = Field(default_factory=list)


class Geography(BaseModel):
    region: str | None = None
    zone: str | None = Field(default=None, description="Geographic zone 1-4 (remoteness).")
    zone_description: str | None = None
    sub_zone: str | None = None
    sub_zone_description: str | None = None
    environmental_index: str | None = Field(default=None, description="A-D (latitude).")
    environmental_index_description: str | None = None
    city: str | None = None
    service_centre: str | None = None
    most_populated_site: str | None = None


class FirstNationProfile(BaseModel):
    band_number: int
    name: str = Field(description="Official name.")
    phonetic_spelling: str | None = None
    address: str | None = None
    postal_code: str | None = None
    phone: str | None = None
    fax: str | None = None
    website: str | None = None
    tribal_council: TribalCouncil | None = None
    reserves: list[Reserve] = Field(default_factory=list)
    total_reserve_hectares: float | None = Field(
        default=None,
        description="Computed by MapleStats: the sum of `reserves[].hectares`. Reserves "
        "with no published area are left out of it; `reserves_without_hectares` counts them.",
    )
    reserves_without_hectares: int = Field(
        default=0,
        description="Reserves listed with no area, so not in `total_reserve_hectares`.",
    )
    governance: Governance
    geography: Geography
    profile_url: str
    provenance: Provenance


class ResidenceCount(BaseModel):
    residence: str = Field(
        description="own_reserve, other_reserve, own_crown_land, other_band_crown_land, "
        "no_band_crown_land or off_reserve."
    )
    label: str = Field(description="The page's own label, in the language asked for.")
    men: int | None = None
    women: int | None = None
    total: int | None = Field(
        default=None,
        description="Computed by MapleStats: men + women (the page gives no total per "
        "residence); null when either is missing.",
    )


class AnnualPopulation(BaseModel):
    year: int
    on_reserve_men: int | None = None
    on_reserve_women: int | None = None
    on_reserve: int | None = Field(default=None, description="On reserve or Crown land.")
    off_reserve_men: int | None = None
    off_reserve_women: int | None = None
    off_reserve: int | None = None
    men: int | None = None
    women: int | None = None
    total: int | None = None


class RegisteredPopulation(BaseModel):
    band_number: int
    name: str
    as_of: str | None = Field(
        default=None, description="The profile's month, e.g. 'September, 2026'."
    )
    as_of_month: str | None = Field(default=None, description="The same month as YYYY-MM.")
    by_residence: list[ResidenceCount] = Field(default_factory=list)
    men: int | None = Field(
        default=None,
        description="Computed by MapleStats: the sum of `by_residence[].men`; null when "
        "any residence lacks it.",
    )
    women: int | None = Field(
        default=None,
        description="Computed by MapleStats: the sum of `by_residence[].women`; null when "
        "any residence lacks it.",
    )
    total: int | None = Field(
        default=None, description="Total registered population, as the page gives it."
    )
    annual: list[AnnualPopulation] = Field(
        default_factory=list,
        description="Yearly figures (December 31) from ISC's open dataset, oldest first.",
    )
    annual_source: str = Field(description="URL of the yearly dataset.")
    notes: list[str] = Field(default_factory=list)
    provenance: Provenance


class LongTermAdvisory(BaseModel):
    advisory_id: str
    status: Literal["current", "lifted"]
    band_number: int | None = Field(default=None, description="The community's band number.")
    community: str
    province: str | None = None
    province_code: str | None = None
    region: str | None = None
    water_system: str | None = None
    advisory_type: str = Field(description="As published, in the language asked for.")
    kind: AdvisoryKind
    date_set: date | None = Field(default=None, description="When the advisory was issued.")
    date_long_term: date | None = Field(
        default=None, description="When it became long-term (in place more than a year)."
    )
    date_lifted: date | None = Field(default=None, description="Lifted advisories only.")
    population_affected: str | None = Field(default=None, description="A range, as published.")
    corrective_measure: str | None = None
    project_phase: str | None = Field(
        default=None,
        description="Feasibility, Design, Initial Assessment, Construction or Complete.",
    )
    recommended_to_lift: bool = Field(
        default=False,
        description="An environmental public health officer recommended lifting it.",
    )
    latitude: float | None = None
    longitude: float | None = None


class LongTermAdvisoryList(BaseModel):
    generated: date | None = Field(default=None, description="The map file's GenerateDate.")
    status: Literal["current", "lifted", "all"]
    current_count: int = Field(description="Current advisories nationally, before filters.")
    lifted_count: int = Field(description="Lifted advisories nationally, before filters.")
    communities_with_current: int = Field(
        description="Communities with a current advisory nationally."
    )
    advisories: list[LongTermAdvisory] = Field(default_factory=list)
    returned_count: int
    total_matched: int
    data_url: str = Field(description="The map's JSON file, found on the page at run time.")
    notes: list[str] = Field(default_factory=list)
    provenance: Provenance


class ShortTermAdvisory(BaseModel):
    region: str = Field(description="ISC region of the table (ATLANTIC, QUEBEC, ...).")
    first_nation: str
    community: str | None = None
    water_system: str | None = None
    code: str = Field(description="The page's code: BWA, DNC, DNU (AEE, ANPB, ANU in French).")
    kind: AdvisoryKind
    date_set: date | None = None
    date_revoked: date | None = Field(default=None, description="None while in effect.")
    active: bool
    population: str | None = Field(default=None, description="A range, or unknown.")
    isc_supported: bool | None = Field(
        default=None, description="The system's infrastructure is financially supported by ISC."
    )


class ShortTermAdvisoryList(BaseModel):
    as_of: date | None = Field(default=None, description="The page's own 'As of' date.")
    in_effect_count: int | None = Field(
        default=None, description="The page's own count of advisories in effect."
    )
    advisories: list[ShortTermAdvisory] = Field(default_factory=list)
    returned_count: int
    total_matched: int
    notes: list[str] = Field(default_factory=list)
    provenance: Provenance
