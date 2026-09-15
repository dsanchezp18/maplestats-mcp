"""Small parsing helpers for the JSON quirks government APIs commonly have.

`obj.get(key, [])` only applies its default when `key` is absent — if
the key is present with a JSON `null` value (confirmed live against
StatCan WDS's `surveyCode`/`subjectCode` fields, which are `null` on
some cubes rather than `[]`), `.get` still returns `None`, which then
fails Pydantic's `list[str]` validation. `list_or_empty` coalesces both
cases to an empty list.
"""

from __future__ import annotations

from typing import Any


def list_or_empty(obj: dict[str, Any], key: str) -> list[Any]:
    return obj.get(key) or []
