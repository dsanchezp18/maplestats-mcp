"""Typed responses for IRCC's processing-times files."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance

TimeStatus = Literal["available", "no_time_available", "not_enough_data", "unparsed"]
TimeUnit = Literal["minutes", "hours", "days", "weeks", "months", "years"]
Qualifier = Literal["about", "more_than", "less_than"]
Basis = Literal["processing_time", "forward_looking"]


class ProcessingTime(BaseModel):
    """One processing time as IRCC publishes it, with its parts read out."""

    text: str = Field(description="IRCC's text as published, e.g. 'About 6 months', '123 days'.")
    status: TimeStatus = Field(
        description="'available' when the text gives a duration; 'no_time_available' and "
        "'not_enough_data' are IRCC's own wordings; 'unparsed' when the text has a shape "
        "MapleStats does not read (the text is still given)."
    )
    amount: float | None = None
    unit: TimeUnit | None = None
    qualifier: Qualifier | None = Field(
        default=None, description="'about', 'more_than' or 'less_than' when IRCC says so."
    )
    approx_days: float | None = Field(
        default=None,
        description="amount converted to days (a month is 30.44 days), only to sort or compare; "
        "IRCC publishes the text, not this number.",
    )


class ApplicationType(BaseModel):
    type_id: str = Field(
        description="IRCC's own key for the type, used by ircc_processing_get_time."
    )
    label: str
    category: str
    category_label: str
    by_country: bool = Field(
        description="True when IRCC publishes one time per country of residence."
    )
    basis: Basis = Field(
        description="'forward_looking': IRCC's estimate for an application submitted now, from "
        "its inventory and expected processing (permanent residence, citizenship, in-Canada "
        "extensions). 'processing_time': the time IRCC's tool shows for the type, which its "
        "page describes as how long it took to process 80% of applications in the past or "
        "its commitment for most complete applications."
    )
    last_updated: str | None = Field(description="IRCC's 'last updated' text for this type's file.")
    last_updated_date: date | None = None
    update_cadence: str | None = Field(
        default=None, description="How often IRCC says it refreshes this file."
    )
    source_url: str = Field(description="The JSON file this type is read from.")


class ApplicationTypeList(BaseModel):
    types: list[ApplicationType]
    returned_count: int
    category: str | None = None
    page_url: str = Field(description="IRCC's 'Check processing times' page.")
    note: str = Field(description="What these figures are and are not.")
    provenance: Provenance


class CountryTime(BaseModel):
    country_code: str = Field(description="ISO 3166 alpha-2 code as IRCC keys it.")
    country_name: str
    component: str | None = Field(
        default=None,
        description="For privately sponsored refugees: 'sponsor' (the sponsorship application) "
        "or 'refugee' (the refugee's permanent residence application).",
    )
    time: ProcessingTime


class ProcessingTimeResult(BaseModel):
    application_type: ApplicationType
    time: ProcessingTime | None = Field(
        description="The single time, for a type that does not vary by country; null for a "
        "by-country type (see countries)."
    )
    people_waiting: int | None = Field(
        default=None,
        description="Applications IRCC says are waiting, for forward-looking types "
        "(rounded by IRCC, 'About 53,900 people waiting').",
    )
    people_waiting_text: str | None = None
    countries: list[CountryTime] = Field(
        description="One entry per country of residence (two for privately sponsored refugees), "
        "longest time first; empty for a type that does not vary by country."
    )
    country: str | None = Field(default=None, description="The country asked for, if any.")
    returned_count: int
    page_url: str
    note: str = Field(description="What these figures are and are not.")
    provenance: Provenance
