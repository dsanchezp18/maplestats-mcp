"""Small parsing helpers for the JSON quirks government APIs commonly have.

`obj.get(key, default)` only applies its default when `key` is absent —
if the key is present with a JSON `null` value (confirmed live against
StatCan WDS's `surveyCode`/`subjectCode` fields, which are `null` on
some cubes rather than `[]`), `.get` still returns `None`, which then
fails Pydantic validation against a non-optional field type.
`list_or_empty`/`get_or` coalesce both cases (absent key, present-null
value) to the caller's default.
"""

from __future__ import annotations

from typing import Any


def list_or_empty(obj: dict[str, Any], key: str) -> list[Any]:
    return obj.get(key) or []


def get_or[T](obj: dict[str, Any], key: str, default: T) -> Any | T:
    """Scalar counterpart to `list_or_empty`, for a required non-list
    field (an `int` count, for instance) that must never surface a bare
    JSON `null` to Pydantic as if it were a present, valid value."""
    value = obj.get(key)
    return default if value is None else value
