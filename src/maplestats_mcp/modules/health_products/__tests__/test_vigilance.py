"""Canada Vigilance report API and extract scan, on live-shaped data (2026-10-03)."""

from __future__ import annotations

import gzip
import io
import random
import re
import zipfile

import pytest
from pytest_httpx import IteratorStream

from maplestats_mcp.modules.health_products.vigilance import client, constants, extract
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError

BASE = "https://health-products.canada.ca/api/canada-vigilance/"
FOLDER = "cvponline_extract_20260531"


def _url(endpoint: str, query: str = "") -> re.Pattern[str]:
    return re.compile(re.escape(f"{BASE}{endpoint}/?") + query)


def _row(reaction_id, report_id, pt, pt_fr, soc, soc_fr) -> str:
    fields = [str(reaction_id), str(report_id), "", "", "", pt, pt_fr, soc, soc_fr, "v.29.0"]
    return '"' + '"$"'.join(fields) + '"'


REACTIONS = "\n".join(
    [
        _row(2601, 26, "Rash", "Rash", "Skin and subcutaneous tissue disorders",
             "Affections de la peau et du tissu sous-cutané"),
        _row(2901, 29, "Headache", "Céphalée", "Nervous system disorders",
             "Affections du système nerveux"),
        _row(9001, 908853423, "Myocarditis", "Myocardite", "Cardiac disorders",
             "Affections cardiaques"),
        _row(9002, 908853423, "Viral myocarditis", "Myocardite virale",
             "Infections and infestations", "Infections et infestations"),
    ]
) + "\n"  # fmt: skip


def _extract(reactions: str = REACTIONS, *, members: tuple[str, ...] | None = None) -> bytes:
    """A ZIP shaped like the live one (deflated, sizes in local headers), gzip-encoded."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        names = members or ("drug_products.txt", "gender_lx.txt", "reactions.txt", "reports.txt")
        for name in names:
            body = reactions if name == "reactions.txt" else '"1"$"LASIX PARENTERAL INJ"\n'
            archive.writestr(f"{FOLDER}/{name}", body.encode("utf-8"))
    return gzip.compress(buffer.getvalue())


def _serve(httpx_mock, body: bytes) -> None:
    # Served in 64 KB pieces, as a network read delivers it.
    pieces = [body[i : i + 65536] for i in range(0, len(body), 65536)]
    httpx_mock.add_response(
        url=constants.EXTRACT_URL,
        stream=IteratorStream(pieces),
        headers={"Content-Encoding": "gzip", "Last-Modified": "Wed, 02 Sep 2026 11:59:19 GMT"},
    )


async def test_reaction_search_reads_only_through_reactions(httpx_mock):
    _serve(httpx_mock, _extract())
    result = await client.search_reactions("myocard")
    assert result.complete
    assert result.reports_matched == 1 and result.reaction_rows_matched == 2
    assert result.reports[0].report_id == 908853423
    assert result.top_reactions == {"Myocarditis": 1, "Viral myocarditis": 1}
    assert result.extract_folder == FOLDER
    assert result.provenance.as_of is not None and result.provenance.as_of.year == 2026


async def test_french_terms_and_organ_class_filter(httpx_mock):
    _serve(httpx_mock, _extract())
    result = await client.search_reactions("céphalée", system_organ_class="nerveux", lang="fr")
    assert result.top_reactions == {"Céphalée": 1}
    assert result.by_system_organ_class == {"Affections du système nerveux": 1}
    assert (result.provenance.coverage or "").startswith("toutes les lignes de réaction")
    assert "n'est pas un taux d'incidence" in (result.provenance.limits or "")
    with pytest.raises(InvalidInput, match="^Entrée invalide : donnez au moins 3 lettres"):
        await client.search_reactions("ab", lang="fr")


def test_stop_reason_in_french():
    assert client._stop_reason_fr("the 25 s time limit") == "limite de temps de 25 s"
    assert client._stop_reason_fr("the 40 MB read ceiling") == "plafond de lecture de 40 Mo"


async def test_missing_reactions_file_is_an_error(httpx_mock):
    _serve(httpx_mock, _extract(members=("drug_products.txt", "reports.txt")))
    with pytest.raises(UpstreamError, match="no reactions.txt"):
        await client.search_reactions("rash")


async def test_ceiling_returns_a_partial_result(httpx_mock):
    rng = random.Random(1)
    lines = [
        _row(i, i, f"Term {rng.getrandbits(160):040x}", "x", "Soc", "Soc") for i in range(60_000)
    ]
    _serve(httpx_mock, _extract("\n".join(lines) + "\n"))
    matcher = extract.ReactionMatcher("term", "", 0, "en")
    outcome = await extract.scan_reactions(matcher, max_bytes=1, max_seconds=60)
    assert not outcome.complete and outcome.stop_reason and "ceiling" in outcome.stop_reason
    assert 0 < matcher.rows < 60_000


def test_zip_walker_rejects_streamed_members():
    header = b"PK\x03\x04" + bytes(2) + (0x08).to_bytes(2, "little") + (8).to_bytes(2, "little")
    header += bytes(8) + bytes(8) + (3).to_bytes(2, "little") + bytes(2) + b"a/r"
    walker = extract.ZipWalker("/r", lambda data: None)
    with pytest.raises(UpstreamError, match="no sizes"):
        walker.feed(header)


async def test_search_validates_input():
    with pytest.raises(InvalidInput):
        await client.search_reactions("ab")
    with pytest.raises(InvalidInput):
        await client.search_reactions("rash", max_scan_mb=500)


REPORT = {
    "report_id": 908853423, "report_no": "E2B_08853423", "version_no": 0,
    "date_received": "2026-05-30", "date_int_received": "2026-05-30", "mah_no": "2026SA0086109",
    "report_type_code": "8", "report_type_name": "Study", "gender_code": "1", "gender_name": "Male",
    "age": 56.0, "age_y": 56.0, "age_unit": "Years", "outcome_code": "07",
    "outcome": "Recovered/resolved", "weight": 0.0, "weight_unit": "", "height": 0.0,
    "height_unit": "", "seriousness_code": "01", "seriousness": "Serious", "death": "2",
    "disability": "2", "congenital_anomaly": "2", "life_threatening": "2", "hosp_required": "1",
    "other_medically_imp_cond": "1", "reporter_type_code": "", "reporter_type": "",
    "source_code": "07", "source_name": "MAH", "pt_name": "Myocarditis",
    "soc_name": "Cardiac disorders", "duration": 0.0, "duration_unit": "", "drug_name": "DUPILUMAB",
    "cpd_flag": 0,
}  # fmt: skip


async def test_report_counts_only_criteria_marked_1(httpx_mock):
    # Newer reports mark an unmet criterion "2", older ones leave it empty.
    httpx_mock.add_response(url=_url("report", r"id=908853423"), json=REPORT)
    httpx_mock.add_response(
        url=_url("reportdrug", r"id=908853423"),
        json=[{"report_drug_id": 5384117, "report_id": 908853423, "drug_product_id": 25992,
               "drug_name": "DUPILUMAB", "drug_involv_name": "Suspect",
               "route_admin_name": "Subcutaneous", "unit_dose_qty": 300.0, "dose_unit_name": None,
               "frequency": 1, "freq_time": 2.0, "frequency_time": "1 every 2 Weeks",
               "freq_time_unit": "Weeks", "therapy_duration": 0.0, "therapy_duration_unit": "",
               "dosage_form": "SOLUTION", "indication_name": "Dermatitis atopic"}],
    )  # fmt: skip
    report = await client.get_report(908853423)
    assert report.serious_criteria == [
        "Hospitalization required",
        "Other medically important condition",
    ]
    assert report.drugs[0].role == "Suspect" and report.drugs[0].dose == "300"
    assert report.weight is None and report.age == "56 Years"


async def test_unknown_report_is_the_all_null_object(httpx_mock):
    blank = {key: None for key in REPORT} | {"report_id": 0, "age": 0.0, "version_no": 0}
    httpx_mock.add_response(url=_url("report", r"id=300000"), json=blank)
    httpx_mock.add_response(url=_url("reportdrug", r"id=300000"), json=[])
    with pytest.raises(NotFound):
        await client.get_report(300000)


async def test_code_tables(httpx_mock):
    tables = {
        "outcome": [{"outcome_id": 1911, "outcome_code": "11", "outcome_name": "Fatale"}],
        "seriousness": [{"seriousness_id": 2001, "seriousness_code": "01", "seriousness": "Grave"}],
        "source": [{"source_id": 1003, "source_code": "03", "source": "Hôpital"}],
        "gender": [{"gender_id": 41, "gender_code": "1", "gender_name": "Masculin"}],
        "reporttype": [{"report_type_id": 70095009, "report_type_code": "7",
                        "report_type": "Déclaration spontanée"}],
    }  # fmt: skip
    for endpoint, rows in tables.items():
        httpx_mock.add_response(url=_url(endpoint, r"type=json&lang=fr$"), json=rows)
    result = await client.list_codes(lang="fr")
    assert result.tables["outcome"][0].label == "Fatale"
    assert result.tables["report_type"][0].code == "7"
