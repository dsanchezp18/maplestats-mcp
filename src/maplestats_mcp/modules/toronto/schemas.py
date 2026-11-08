from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class DatasetSource(BaseModel):
    """Which open.toronto.ca table the rows come from and how to cite it."""

    dataset: str = Field(description="Dataset title on open.toronto.ca.")
    landing_page: str
    resource_id: str = Field(
        description="DataStore resource id; ckan_datastore_search with portal='toronto' reads "
        "the same table unchanged."
    )
    licence: str = Field(description="Open Government Licence - Toronto, with its link.")
    citation: str = Field(description="A citation line to quote with the figures.")


class ProfileRow(BaseModel):
    category: str | None
    topic: str | None
    characteristic: str = Field(description="Indicator label, leading spaces removed.")
    level: int = Field(
        description="Depth in the census hierarchy (0 = top line), read from the label's "
        "leading spaces: '  Renter' is level 1 under 'Total - Private households by tenure'."
    )
    data_source: str | None = Field(
        description="The census product the row comes from (2016 only), e.g. "
        "'Census Profile 98-316-X2016001'."
    )
    value: str | None = Field(description="The neighbourhood's value as published.")
    value_number: float | None = Field(description="`value` as a number, when it is one.")
    city_value: str | None = Field(description="The City of Toronto value as published.")
    city_value_number: float | None


class NeighbourhoodProfile(BaseModel):
    census_year: int
    neighbourhood: str = Field(description="Neighbourhood name as the City writes it.")
    neighbourhood_number: str | None = Field(
        description="The City's 140-model neighbourhood number (2016 table only)."
    )
    topic_filter: str | None
    characteristic_filter: str | None
    total_matched: int
    returned_count: int
    offset: int
    rows: list[ProfileRow]
    topics: list[str] = Field(description="Every topic in this census year's table, in order.")
    source: DatasetSource
    provenance: Provenance


class ApartmentEvaluation(BaseModel):
    rsn: str = Field(description="RentSafeTO registration number of the building.")
    address: str | None
    ward: str | None = Field(description="City ward number, '01' to '25'.")
    ward_name: str | None
    property_type: str | None = Field(description="PRIVATE, TCHC or SOCIAL HOUSING.")
    year_built: int | None
    year_registered: int | None
    storeys: int | None
    units: int | None
    evaluation_date: str | None = Field(description="Date the evaluation was completed.")
    score: float | None = Field(description="Current building evaluation score, 0 to 100.")
    proactive_score: float | None
    reactive_score: float | None
    areas_evaluated: int | None
    latitude: float | None
    longitude: float | None
    evaluations_on_record: int = Field(
        description="Evaluations of this building in the 2023-current table."
    )


class ApartmentEvaluations(BaseModel):
    latest_only: bool
    ward_filter: str | None
    address_filter: str | None
    sort: str
    total_matched: int
    returned_count: int
    offset: int
    evaluations: list[ApartmentEvaluation]
    source: DatasetSource
    provenance: Provenance


class ScoreGroup(BaseModel):
    key: str = Field(description="Ward number, property type, or 'all' for the city.")
    label: str | None = Field(description="Ward name, when grouping by ward.")
    buildings: int
    units: int = Field(description="Sum of confirmed units in those buildings.")
    mean_score: float | None
    median_score: float | None
    p25_score: float | None = Field(description="25th percentile of building scores.")
    min_score: float | None
    max_score: float | None


class ApartmentScoreSummary(BaseModel):
    group_by: Literal["ward", "property_type"]
    evaluated_since: int | None = Field(
        description="Only buildings whose latest evaluation is in this year or later."
    )
    buildings: int
    groups: list[ScoreGroup]
    city: ScoreGroup
    source: DatasetSource
    provenance: Provenance


class CountGroup(BaseModel):
    key: str
    label: str | None = Field(description="Ward name, when grouping by ward.")
    registrations: int
    share: float = Field(description="Share of all registrations, 0 to 1.")


class ShortTermRentalSummary(BaseModel):
    group_by: Literal["ward", "property_type", "postal_code"]
    registrations: int
    groups: list[CountGroup]
    source: DatasetSource
    provenance: Provenance


class Inspection(BaseModel):
    establishment_id: str | None
    establishment: str | None
    address: str | None
    inspection_date: str | None
    status: str | None = Field(description="Pass, Conditional Pass or Closed.")
    severity: str | None = Field(
        description="Of the infraction: 'M - Minor', 'S - Significant', 'C - Crucial'; "
        "'None' when the inspection found none."
    )
    infraction: str | None
    deficiency: str | None
    outcome: str | None
    outcome_date: str | None
    amount_fined: float | None
    latitude: float | None
    longitude: float | None


class InspectionSearch(BaseModel):
    establishment_filter: str | None
    address_filter: str | None
    status_filter: str | None
    total_matched: int
    returned_count: int
    offset: int
    inspections: list[Inspection]
    source: DatasetSource
    provenance: Provenance
