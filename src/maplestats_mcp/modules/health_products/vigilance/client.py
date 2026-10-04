"""Client for Canada Vigilance: the report API and the extract search.

Checked live 2026-10-03 (see also ../api.py, constants.py, extract.py):

1. `report?id=` takes the report id and answers one object; an unknown
   id answers the all-null object with report_id 0, and a non-numeric id
   HTTP 400. Older reports have ids up to 6 digits (report_no "000000195");
   electronic (E2B) reports since have 9-digit ids such as 908853423
   (report_no "E2B_08853423"). The
   first call of a session took 5.5 s, later ones about 0.3 s.
2. Report ids are not dated in order: id 100000 is a 1969 study report
   while 50000 is from 1985, and many ids in between are unused (300000,
   400000, 800000 answer nothing). Ids are only roughly chronological.
3. `pt_name` and `soc_name` hold every reaction of the report, joined with
   ", "; the per-reaction `reaction?id=` takes a reaction id, which no
   report answer carries, so reactions come from the report itself.
4. Seriousness reads "Serious"/"Not Serious" (English) and "Grave"/"Non
   grave" (French); the death, disability and other criteria are "1"
   when met, and "2" (newer reports) or "" (older ones) when not.
5. `reportdrug?id=` takes the report id and lists every product on the
   report with its role (Suspect, Concomitant, ...), dose and indication.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any

from maplestats_mcp.modules.health_products import api
from maplestats_mcp.modules.health_products.vigilance import constants
from maplestats_mcp.modules.health_products.vigilance.extract import (
    ReactionMatcher,
    scan_reactions,
)
from maplestats_mcp.modules.health_products.vigilance.schemas import (
    ReactionReportHit,
    ReactionSearchResult,
    ReportDrug,
    VigilanceCode,
    VigilanceCodeTables,
    VigilanceReport,
)
from maplestats_mcp.shared.cache import cached_fetch, forget
from maplestats_mcp.shared.errors import InvalidInput, NotFound

# One extract scan at a time: each reads about 100 MB from canada.ca.
_SCAN_SLOT = asyncio.Semaphore(1)
_CRITERIA = {
    "death": ("Death", "Décès"),
    "disability": ("Disability", "Invalidité"),
    "congenital_anomaly": ("Congenital anomaly", "Anomalie congénitale"),
    "life_threatening": ("Life threatening", "Danger de mort"),
    "hosp_required": ("Hospitalization required", "Hospitalisation requise"),
    "other_medically_imp_cond": (
        "Other medically important condition",
        "Autre problème médical important",
    ),
}


def _measure(value: Any, unit: Any) -> str | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not number:
        return None
    return " ".join(x for x in (f"{number:g}", api.text(unit)) if x)


def _drug(row: dict[str, Any]) -> ReportDrug:
    return ReportDrug(
        drug_product_id=row.get("drug_product_id") or None,
        drug_name=api.text(row.get("drug_name")),
        role=api.text(row.get("drug_involv_name")),
        route=api.text(row.get("route_admin_name")),
        dose=_measure(row.get("unit_dose_qty"), row.get("dose_unit_name") or row.get("dose_unit")),
        frequency=api.text(row.get("frequency_time")),
        therapy_duration=_measure(row.get("therapy_duration"), row.get("therapy_duration_unit")),
        dosage_form=api.text(row.get("dosage_form")),
        indication=api.text(row.get("indication_name")),
    )


async def get_report(report_id: int, *, lang: str = "en") -> VigilanceReport:
    if report_id <= 0:
        api.fail(
            InvalidInput,
            "report_id must be a positive number, e.g. 950000 or 908853423.",
            "report_id doit être un nombre positif, p. ex. 950000 ou 908853423.",
            lang,
        )

    async def fetch() -> VigilanceReport:
        by_id = {"id": report_id}
        report, drugs = await asyncio.gather(
            api.get_json(constants.PATH_REPORT, by_id, lang=lang, timeout=60.0),
            api.get_json(constants.PATH_REPORT_DRUG, by_id, lang=lang, missing_ok=True),
        )
        rows = [r for r in api.as_list(report) if not api.is_blank(r, "report_id")]
        if not rows:
            api.fail(
                NotFound,
                f"Canada Vigilance has no adverse reaction report {report_id}.",
                f"Canada Vigilance n'a aucune déclaration d'effet indésirable {report_id}.",
                lang,
            )
        r = rows[0]
        index = 1 if lang == "fr" else 0
        return VigilanceReport(
            report_id=report_id,
            report_number=api.text(r.get("report_no")),
            version=r.get("version_no"),
            date_received=api.text(r.get("date_received")),
            initial_date_received=api.text(r.get("date_int_received")),
            report_type=api.text(r.get("report_type_name")),
            source=api.text(r.get("source_name")),
            reporter_type=api.text(r.get("reporter_type")),
            mah_number=api.text(r.get("mah_no")),
            sex=api.text(r.get("gender_name")),
            age=_measure(r.get("age"), r.get("age_unit")),
            age_years=float(r["age_y"]) if r.get("age_y") else None,
            weight=_measure(r.get("weight"), r.get("weight_unit")),
            height=_measure(r.get("height"), r.get("height_unit")),
            outcome=api.text(r.get("outcome")),
            serious=api.text(r.get("seriousness")),
            serious_criteria=[
                labels[index] for key, labels in _CRITERIA.items() if api.text(r.get(key)) == "1"
            ],
            reactions=api.text(r.get("pt_name")),
            system_organ_classes=api.text(r.get("soc_name")),
            reaction_duration=_measure(r.get("duration"), r.get("duration_unit")),
            drugs=[_drug(d) for d in api.as_list(drugs) if d.get("report_id")],
            provenance=api.provenance(
                f"{api.url_for(constants.PATH_REPORT)}?id={report_id}&lang={lang}&type=json",
                cached=False,
                schema="VigilanceReport",
                freshness=constants.API_FRESHNESS,
                limits=constants.CAUTION,
                lang=lang,
                freshness_fr=constants.API_FRESHNESS_FR,
                limits_fr=constants.CAUTION_FR,
            ),
        )

    result, cached = await cached_fetch(
        f"hc_vigilance:report:{report_id}:{lang}", constants.LOOKUP_TTL_SECONDS, fetch
    )
    if cached:
        result = result.model_copy(
            update={"provenance": result.provenance.model_copy(update={"cached": True})}
        )
    return result


async def list_codes(*, lang: str = "en") -> VigilanceCodeTables:
    async def fetch() -> dict[str, list[VigilanceCode]]:
        names = list(constants.CODE_TABLES)
        answers = await asyncio.gather(
            *(api.get_json(constants.CODE_TABLES[n], lang=lang) for n in names)
        )
        tables: dict[str, list[VigilanceCode]] = {}
        for name, answer in zip(names, answers, strict=True):
            codes: list[VigilanceCode] = []
            for row in api.as_list(answer):
                code = next((str(v) for k, v in row.items() if k.endswith("_code") and v), None)
                label = next(
                    (
                        str(v)
                        for k, v in row.items()
                        if not k.endswith(("_code", "_id")) and isinstance(v, str) and v
                    ),
                    None,
                )
                if code and label:
                    codes.append(VigilanceCode(code=code, label=label))
            tables[name] = codes
        return tables

    tables, cached = await cached_fetch(
        f"hc_vigilance:codes:{lang}", constants.CODES_TTL_SECONDS, fetch
    )
    return VigilanceCodeTables(
        tables=tables,
        provenance=api.provenance(
            api.url_for(constants.CODE_TABLES["outcome"]),
            cached=cached,
            schema="VigilanceCodeTables",
            freshness=constants.API_FRESHNESS,
            lang=lang,
            freshness_fr=constants.API_FRESHNESS_FR,
        ),
    )


def _stop_reason_fr(reason: str | None) -> str:
    """The extract reader's stop reason ("the 40 MB read ceiling", "the 25 s time limit")."""
    text = reason or ""
    number = "".join(ch for ch in text if ch.isdigit())
    if "time limit" in text:
        return f"limite de temps de {number} s"
    if "read ceiling" in text:
        return f"plafond de lecture de {number} Mo"
    return text


def _as_of(last_modified: str | None) -> datetime | None:
    if not last_modified:
        return None
    try:
        return parsedate_to_datetime(last_modified)
    except (TypeError, ValueError):
        return None


async def search_reactions(
    reaction: str = "",
    *,
    system_organ_class: str = "",
    min_report_id: int = 0,
    limit: int = constants.REPORTS_DEFAULT,
    max_scan_mb: int = constants.SCAN_MB_DEFAULT,
    lang: str = "en",
) -> ReactionSearchResult:
    reaction, soc = reaction.strip(), system_organ_class.strip()
    if len(reaction) < 3 and len(soc) < 3:
        api.fail(
            InvalidInput,
            "Give at least 3 letters of a reaction term (e.g. 'anaphyla', 'myocarditis') or of "
            "a system organ class (e.g. 'cardiac').",
            "donnez au moins 3 lettres d'un terme de réaction (p. ex. 'anaphyla', "
            "'myocardite') ou d'une classe de systèmes d'organes (p. ex. 'cardiaque').",
            lang,
        )
    if not 1 <= limit <= constants.REPORTS_MAX:
        api.fail(
            InvalidInput,
            f"limit must be between 1 and {constants.REPORTS_MAX}.",
            f"limit doit être compris entre 1 et {constants.REPORTS_MAX}.",
            lang,
        )
    if not constants.SCAN_MB_MIN <= max_scan_mb <= constants.SCAN_MB_MAX:
        low, high = constants.SCAN_MB_MIN, constants.SCAN_MB_MAX
        api.fail(
            InvalidInput,
            f"max_scan_mb must be between {low} and {high}.",
            f"max_scan_mb doit être compris entre {low} et {high}.",
            lang,
        )
    if min_report_id < 0:
        api.fail(
            InvalidInput,
            "min_report_id cannot be negative.",
            "min_report_id ne peut pas être négatif.",
            lang,
        )

    async def fetch() -> ReactionSearchResult:
        matcher = ReactionMatcher(reaction, soc, min_report_id, lang)
        async with _SCAN_SLOT:
            outcome = await scan_reactions(
                matcher,
                max_bytes=max_scan_mb * 1_000_000,
                max_seconds=constants.SCAN_SECONDS_MAX,
            )
        ids = sorted(matcher.hits, reverse=True)
        reports = [
            ReactionReportHit(
                report_id=i,
                reactions=sorted(matcher.hits[i][0]),
                system_organ_classes=sorted(matcher.hits[i][1]),
            )
            for i in ids[: constants.REPORTS_MAX]
        ]
        scanned_mb = round(outcome.scanned_bytes / 1e6, 1)
        filters = " and ".join(
            part
            for part in (
                f"reaction term contains '{reaction}'" if reaction else "",
                f"system organ class contains '{soc}'" if soc else "",
                f"report id >= {min_report_id}" if min_report_id else "",
            )
            if part
        )
        filters_fr = " et ".join(
            part
            for part in (
                f"le terme de réaction contient '{reaction}'" if reaction else "",
                f"la classe de systèmes d'organes contient '{soc}'" if soc else "",
                f"identifiant de déclaration >= {min_report_id}" if min_report_id else "",
            )
            if part
        )
        if outcome.complete:
            coverage = f"every reaction row of the extract where {filters}"
            coverage_fr = f"toutes les lignes de réaction de l'extrait où {filters_fr}"
        else:
            coverage = (
                f"PARTIAL: reading stopped at {outcome.stop_reason} after {scanned_mb} MB, at "
                f"report id {matcher.newest_report_id}; newer reports were not searched. Raise "
                "max_scan_mb (up to 150) for the whole file."
            )
            coverage_fr = (
                f"PARTIEL : lecture arrêtée ({_stop_reason_fr(outcome.stop_reason)}) après "
                f"{scanned_mb} Mo, à l'identifiant de déclaration {matcher.newest_report_id} ; "
                "les déclarations plus récentes n'ont pas été cherchées. Augmentez max_scan_mb "
                "(jusqu'à 150) pour lire tout le fichier."
            )
        return ReactionSearchResult(
            reports=reports,
            returned_count=len(reports),
            reports_matched=len(ids),
            reaction_rows_matched=matcher.rows,
            top_reactions=dict(matcher.terms.most_common(constants.TOP_TERMS)),
            by_system_organ_class=dict(matcher.socs.most_common()),
            complete=outcome.complete,
            newest_report_id_scanned=matcher.newest_report_id or None,
            scanned_mb=scanned_mb,
            extract_folder=outcome.folder,
            provenance=api.provenance(
                constants.EXTRACT_URL,
                cached=False,
                schema="ReactionSearchResult",
                freshness=constants.EXTRACT_FRESHNESS,
                as_of=_as_of(outcome.last_modified),
                coverage=coverage,
                limits=(
                    f"reads the extract's reactions file only, up to {max_scan_mb} MB "
                    "compressed; dates, products and patients per report come from "
                    "hc_vigilance_get_report. A report records a suspected association, not a "
                    "confirmed cause; counts of reports are not incidence rates."
                ),
                lang=lang,
                freshness_fr=constants.EXTRACT_FRESHNESS_FR,
                coverage_fr=coverage_fr,
                limits_fr=(
                    f"ne lit que le fichier des réactions de l'extrait, jusqu'à {max_scan_mb} Mo "
                    "compressés ; les dates, les produits et les patients de chaque "
                    "déclaration viennent de hc_vigilance_get_report. " + constants.CAUTION_FR
                ),
            ),
        )

    key = f"hc_vigilance:scan:{reaction.casefold()}:{soc.casefold()}:{min_report_id}:{lang}:{max_scan_mb}"
    result, cached = await cached_fetch(key, constants.SCAN_TTL_SECONDS, fetch)
    coverage_text = result.provenance.coverage or ""
    if not result.complete and (
        "time limit" in coverage_text or "limite de temps" in coverage_text
    ):
        # A slow read is not a property of the query; let the next call retry.
        forget(key)
    if cached:
        result = result.model_copy(
            update={"provenance": result.provenance.model_copy(update={"cached": True})}
        )
    full = result.model_copy(update={"reports": result.reports[:limit]})
    return full.model_copy(update={"returned_count": len(full.reports)})
