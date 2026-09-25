from __future__ import annotations

import pytest

from maplestats_mcp.shared.envelope import make_provenance, raise_error
from maplestats_mcp.shared.errors import InvalidInput


def test_make_provenance_stamps_required_fields():
    prov = make_provenance(
        source="test-source", url="https://example.invalid/x", cached=True, schema_name="test.Model"
    )
    assert prov.source == "test-source"
    assert prov.cached is True
    assert prov.schema_name == "test.Model"
    assert prov.queried_at is not None


def test_raise_error_raises_the_given_exception_type_with_formatted_message():
    with pytest.raises(InvalidInput) as exc_info:
        raise_error(InvalidInput, "error.invalid_input", lang="en", detail="bad coordinate")
    assert "bad coordinate" in str(exc_info.value)


def test_raise_error_uses_french_message_when_lang_fr():
    with pytest.raises(InvalidInput) as exc_info:
        raise_error(InvalidInput, "error.invalid_input", lang="fr", detail="mauvaise valeur")
    assert "invalide" in str(exc_info.value)
