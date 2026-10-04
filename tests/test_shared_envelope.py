from __future__ import annotations

import pytest

from maplestats_mcp.shared import i18n
from maplestats_mcp.shared.envelope import (
    STATCAN_LICENCE,
    make_provenance,
    raise_error,
    raise_typed,
)
from maplestats_mcp.shared.errors import InvalidInput, NotFound
from maplestats_mcp.shared.models import Provenance


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


@pytest.mark.parametrize(
    ("source", "url"),
    [
        ("statcan-wds", "https://www150.statcan.gc.ca/t1/wds/rest/x"),
        ("statcan_sdg", "https://example.github.io/x"),
        ("other-module", "https://www12.statcan.gc.ca/x"),
    ],
)
def test_statcan_results_carry_the_open_licence_note(source, url):
    prov = make_provenance(source=source, url=url, cached=False, schema_name="t.M")
    assert prov.licence is not None
    assert "Statistics Canada Open Licence" in prov.licence
    assert "endorsed" in prov.licence


def test_french_provenance_has_french_shared_phrases():
    prov = make_provenance(
        source="statcan-wds",
        url="https://x.statcan.gc.ca",
        cached=False,
        schema_name="t",
        lang="fr",
    )
    assert prov.licence is not None
    assert prov.licence.startswith("Source\u00a0: Statistique Canada.")
    assert "https://www.statcan.gc.ca/fr/reference/licence" in prov.licence
    assert "approuvées par Statistique Canada" in prov.licence
    assert "reproduce_code" in prov.reproduce and "appelez" in prov.reproduce


def test_english_provenance_is_unchanged_by_default():
    prov = make_provenance(source="statcan-wds", url="https://x", cached=False, schema_name="t")
    assert prov.licence == STATCAN_LICENCE
    assert prov.reproduce == Provenance.model_fields["reproduce"].default


def test_raise_typed_picks_the_class_template():
    with pytest.raises(NotFound, match="^Aucune correspondance trouvée\u00a0: rien$"):
        raise_typed(NotFound, "rien", lang="fr")
    with pytest.raises(InvalidInput, match="^Invalid input: bad$"):
        raise_typed(InvalidInput, "bad")


def test_modules_can_register_templates():
    i18n.register({"testmodule.empty": {"en": "Nothing for {x}.", "fr": "Rien pour {x}."}})
    i18n.register({"testmodule.empty": {"en": "Nothing for {x}.", "fr": "Rien pour {x}."}})
    with pytest.raises(InvalidInput, match="^Rien pour Ottawa.$"):
        raise_error(InvalidInput, "testmodule.empty", lang="fr-CA", x="Ottawa")
    with pytest.raises(ValueError, match="already registered"):
        i18n.register({"testmodule.empty": {"en": "Other text."}})


def test_other_sources_have_no_licence_note():
    prov = make_provenance(
        source="boc-valet", url="https://www.bankofcanada.ca/x", cached=False, schema_name="t.M"
    )
    assert prov.licence is None
