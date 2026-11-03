"""Short reading notes derived from StatCan's own metadata, with no rule per table.

Each note is one sentence and is added only when WDS metadata shows the issue,
so a series without one gets no text at all. What each check reads, all
confirmed live on 2026-11-03:

- Moving averages: the table title or a member name. 14-10-0459 is "...,
  three-month moving average, seasonally adjusted".
- Price basis: a member name, because the unit does not say it. 36-10-0104's
  "Chained (2017) dollars" member and 34-10-0292's "Unadjusted, constant
  dollars" member both carry memberUomCode 81, "Dollars", which used to read as
  current dollars.
- Quality and confidentiality flags on the observations returned: status 7
  "use with caution" (E) and 8 "too unreliable to be published" (F), and
  security level 1, suppressed (x). 11-10-0135 has E and F for Prince Edward
  Island women 65+ (MBM, 2020 to 2024); 14-10-0023 has x for PEI utilities.
- Footnotes on sums: 12-10-0011 "Totals are not equal to the sum of their
  components.", 36-10-0434 "Aggregates are not always equal to the sum of
  their components.", 36-10-0402 "For the chained dollars, the aggregates are
  not equal to the sum of their components."
- Archived tables: archiveStatusCode "1" (14-10-0380, 20-10-0008; current
  tables are "2"), with the replacement named in a footnote: "This table has
  been archived and replaced by table 14-10-0459-01.", "On March 24, 2023, this
  table was archived and replaced by table 20-10-0056."
- Terminated series: getSeriesInfoFromVector's `terminated` is 1 (36-10-0104's
  Chained (2012) dollars, vector 1569928814), as is the member's own flag.
- Seasonal adjustment: an "Unadjusted" member whose dimension also has a
  "Seasonally adjusted" one (12-10-0011, 34-10-0292 "Unadjusted, current" with
  "Seasonally adjusted, current", 14-10-0459). 18-10-0004 (the CPI) has no
  adjusted member, so it gets no note.

Index bases ("2002=100") and constant-dollar units are read from the unit
itself, by context.unit_notes.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from datetime import date
from typing import Any

from maplestats_mcp.shared.i18n import pick
from maplestats_mcp.shared.json_utils import list_or_empty

# (reference period, status code, security level code) of one observation.
Flag = tuple[date, int | None, int | None]

STATUS_USE_WITH_CAUTION = 7
STATUS_TOO_UNRELIABLE = 8
SECURITY_SUPPRESSED = 1
ARCHIVED = "1"
# frequencyCode values whose periods read as a year (getCodeSets: 12 annual,
# 13-17 every 2 to 10 years), and as a day (1 daily, 2 weekly, 4 biweekly, 21).
_YEARLY = {12, 13, 14, 15, 16, 17}
# 9 quarterly, 19 occasional quarterly: written 2026-Q2.
_DAILY = {1, 2, 4, 21}
_SUB_ANNUAL = {1, 2, 4, 6, 7, 9, 11, 19, 20, 21}
_MAX_PERIODS = 6

# The fitness rule that already explains chained-dollar additivity for its
# tables (shared/fitness_rules.py); the auto note is cut to its first clause there.
CHAINED_RULE = "gdp-industry-vs-expenditure"

_MOVING = re.compile(r"(?:(\w+)-month )?moving average", re.IGNORECASE)
_CHAINED = re.compile(r"chained \((\d{4})\) dollars", re.IGNORECASE)
_CONSTANT = re.compile(r"(?:\d{4} )?constant (?:dollars|prices)", re.IGNORECASE)
_NOT_SUM = re.compile(
    r"not (?:always )?equal to the sum of (?:their|its|the) components", re.IGNORECASE
)
_REPLACED = re.compile(
    r"replaced by (?:the )?(?:new )?table (\d{2}-\d{2}-\d{4})(?:-\d{2})?", re.IGNORECASE
)
_NUMBERS_FR = {"three": "trois", "six": "six", "twelve": "douze", "two": "deux"}


def not_additive(text: str) -> bool:
    """True for a footnote saying totals are not equal to the sum of their components."""
    return _NOT_SUM.search(text) is not None


def series_members(cube: dict[str, Any], coordinate: str) -> list[tuple[dict, dict]]:
    """(dimension, member) raw WDS objects for each member of the coordinate."""
    ids = coordinate.split(".")
    found: list[tuple[dict, dict]] = []
    for dim in list_or_empty(cube, "dimension"):
        position = int(dim["dimensionPositionId"])
        if position > len(ids) or ids[position - 1] in ("", "0"):
            continue
        member_id = int(ids[position - 1])
        match = next(
            (m for m in list_or_empty(dim, "member") if int(m["memberId"]) == member_id), None
        )
        if match is not None:
            found.append((dim, match))
    return found


def member_name(obj: dict[str, Any], lang: str) -> str:
    return _name(obj, "memberName", lang)


def _name(obj: dict[str, Any], stem: str, lang: str) -> str:
    suffix = "Fr" if lang == "fr" else "En"
    return str(obj.get(f"{stem}{suffix}") or obj.get(f"{stem}En") or "")


def footnotes_for(cube: dict[str, Any], members: Sequence[tuple[dict, dict]]) -> list[str]:
    """English text of the footnotes that apply to the series: table-wide ones,
    dimension-wide ones, and those on one of its members."""
    mine = {(int(d["dimensionPositionId"]), int(m["memberId"])) for d, m in members}
    texts: list[str] = []
    for note in list_or_empty(cube, "footnote"):
        link = note.get("link") or {}
        position = int(link.get("dimensionPositionId") or 0)
        member = int(link.get("memberId") or 0)
        if position == 0 or member == 0 or (position, member) in mine:
            texts.append(str(note.get("footnotesEn") or ""))
    return texts


def format_period(day: date, frequency_code: int | None) -> str:
    if frequency_code in _YEARLY:
        return str(day.year)
    if frequency_code in _DAILY:
        return day.isoformat()
    if frequency_code in (9, 19):
        return f"{day.year}-Q{(day.month - 1) // 3 + 1}"
    return day.isoformat()[:7]


def _periods(days: list[date], frequency_code: int | None, lang: str) -> str:
    shown = [format_period(d, frequency_code) for d in sorted(days)]
    text = ", ".join(shown[:_MAX_PERIODS])
    if len(shown) > _MAX_PERIODS:
        more = len(shown) - _MAX_PERIODS
        text += pick(lang, f" and {more} more", f" et {more} autres")
    return text


def flag_notes(flags: Iterable[Flag], frequency_code: int | None, lang: str) -> list[str]:
    """E, F and x periods among the observations returned, named."""
    caution, unreliable, suppressed = [], [], []
    for day, status, security in flags:
        if security == SECURITY_SUPPRESSED:
            suppressed.append(day)
        elif status == STATUS_TOO_UNRELIABLE:
            unreliable.append(day)
        elif status == STATUS_USE_WITH_CAUTION:
            caution.append(day)
    notes: list[str] = []
    if caution:
        periods = _periods(caution, frequency_code, lang)
        notes.append(
            pick(
                lang,
                f"Use with caution (E) for {periods}: high sampling variability; say so "
                "when citing.",
                f"À utiliser avec prudence (E) pour {periods} : forte variabilité "
                "d'échantillonnage ; signalez-le en citant.",
            )
        )
    if unreliable or suppressed:
        parts_en, parts_fr = [], []
        if unreliable:
            periods = _periods(unreliable, frequency_code, lang)
            parts_en.append(f"too unreliable to be published (F) for {periods}")
            parts_fr.append(f"trop peu fiable pour être publié (F) pour {periods}")
        if suppressed:
            periods = _periods(suppressed, frequency_code, lang)
            parts_en.append(f"suppressed for confidentiality (x) for {periods}")
            parts_fr.append(f"confidentiel (x) pour {periods}")
        en = "; ".join(parts_en)
        fr = " ; ".join(parts_fr)
        notes.append(
            pick(
                lang,
                f"{en[0].upper()}{en[1:]}: do not report a figure for those periods.",
                f"{fr[0].upper()}{fr[1:]} : ne donnez aucun chiffre pour ces périodes.",
            )
        )
    return notes


def price_basis(members: Sequence[tuple[dict, dict]]) -> tuple[str, str] | None:
    """('chained', '2017') or ('constant', 'constant dollars') from a member name."""
    for _, member in members:
        name = str(member.get("memberNameEn") or "")
        if chained := _CHAINED.search(name):
            return "chained", chained.group(1)
        if constant := _CONSTANT.search(name):
            return "constant", constant.group(0)
    return None


def adjusted_sibling(members: Sequence[tuple[dict, dict]]) -> tuple[dict, dict, dict] | None:
    """(dimension, the series' unadjusted member, its seasonally adjusted sibling).

    The sibling keeps what follows the comma ("Unadjusted, current" pairs with
    "Seasonally adjusted, current", not with "..., constant dollars").
    """
    for dim, member in members:
        name = str(member.get("memberNameEn") or "").strip()
        low = name.lower()
        if not low.startswith(("unadjusted", "not seasonally adjusted")):
            continue
        tail = low.partition(",")[2].strip()
        for other in list_or_empty(dim, "member"):
            other_low = str(other.get("memberNameEn") or "").strip().lower()
            if other_low.startswith("seasonally adjusted") and (
                other_low.partition(",")[2].strip() == tail
            ):
                return dim, member, other
    return None


def replacement_table(cube: dict[str, Any]) -> str | None:
    for note in list_or_empty(cube, "footnote"):
        link = note.get("link") or {}
        if int(link.get("dimensionPositionId") or 0) != 0:
            continue
        found = _REPLACED.search(str(note.get("footnotesEn") or ""))
        if found:
            return found.group(1)
    return None


def metadata_notes(
    cube: dict[str, Any] | None,
    info: dict[str, Any] | None,
    coordinate: str,
    lang: str,
    rule_keys: frozenset[str] = frozenset(),
) -> tuple[list[str], bool]:
    """The notes the table and series metadata call for, and whether a price-basis
    member (chained or constant dollars) overrides what the unit says."""
    if cube is None:
        return [], False
    members = series_members(cube, coordinate)
    notes: list[str] = []
    frequency = cube.get("frequencyCode")

    names = [str(cube.get("cubeTitleEn") or "")] + [
        str(m.get("memberNameEn") or "") for _, m in members
    ]
    moving = next((found for text in names if (found := _MOVING.search(text))), None)
    if moving:
        word = (moving.group(1) or "").lower()
        if word:
            fr_word = _NUMBERS_FR.get(word, word)
            notes.append(
                pick(
                    lang,
                    f"{word.capitalize()}-month moving average: each value averages {word} "
                    "months, so compare it with the same months a year earlier, not with the "
                    "previous month.",
                    f"Moyenne mobile de {fr_word} mois : chaque valeur couvre {fr_word} mois ; "
                    "comparez-la aux mêmes mois un an plus tôt, pas au mois précédent.",
                )
            )
        else:
            notes.append(
                pick(
                    lang,
                    "Moving average: each value averages several periods, so compare it with "
                    "the same period a year earlier, not with the previous one.",
                    "Moyenne mobile : chaque valeur couvre plusieurs périodes ; comparez-la à "
                    "la même période un an plus tôt, pas à la précédente.",
                )
            )

    basis = price_basis(members)
    if basis and basis[0] == "chained":
        year = basis[1]
        if CHAINED_RULE in rule_keys:
            notes.append(
                pick(
                    lang,
                    f"Chained ({year}) dollars: real (inflation-adjusted) values.",
                    f"Dollars enchaînés ({year}) : valeurs réelles (corrigées de l'inflation).",
                )
            )
        else:
            notes.append(
                pick(
                    lang,
                    f"Chained ({year}) dollars: real values that are not additive, so "
                    "components do not sum to totals.",
                    f"Dollars enchaînés ({year}) : valeurs réelles non additives ; la somme "
                    "des composantes ne donne pas le total.",
                )
            )
    elif basis:
        label = basis[1]
        notes.append(
            pick(
                lang,
                f"{label[0].upper()}{label[1:]}: inflation-adjusted (real) values, not "
                "current dollars.",
                "Dollars constants : valeurs corrigées de l'inflation (réelles), pas des "
                "dollars courants.",
            )
        )

    chained = basis is not None and basis[0] == "chained"
    for text in footnotes_for(cube, members):
        if not _NOT_SUM.search(text) or chained:
            continue
        if "chained" in text.lower():
            continue
        notes.append(
            pick(
                lang,
                "StatCan footnote: totals are not equal to the sum of their components; "
                "do not add components to get a total.",
                "Note de StatCan : les totaux ne sont pas égaux à la somme de leurs "
                "composantes ; n'additionnez pas les composantes pour obtenir un total.",
            )
        )
        break

    if str(cube.get("archiveStatusCode")) == ARCHIVED:
        successor = replacement_table(cube)
        if successor:
            notes.append(
                pick(
                    lang,
                    f"Table archived, no longer updated: StatCan replaced it with table "
                    f"{successor}.",
                    f"Tableau archivé, plus mis à jour : Statistique Canada l'a remplacé par "
                    f"le tableau {successor}.",
                )
            )
        else:
            notes.append(
                pick(
                    lang,
                    "Table archived, no longer updated: look for its current replacement "
                    "before citing recent figures.",
                    "Tableau archivé, plus mis à jour : cherchez le tableau qui le remplace "
                    "avant de citer des chiffres récents.",
                )
            )
    elif (info and info.get("terminated") == 1) or any(
        m.get("terminated") == 1 for _, m in members
    ):
        notes.append(
            pick(
                lang,
                "Series terminated: StatCan no longer updates it.",
                "Série terminée : Statistique Canada ne la met plus à jour.",
            )
        )

    if frequency in _SUB_ANNUAL:
        sibling = adjusted_sibling(members)
        if sibling:
            other = _name(sibling[2], "memberName", lang)
            notes.append(
                pick(
                    lang,
                    f"Unadjusted series; the table also has '{other}', usually the "
                    "headline for change from one period to the next.",
                    f"Série non désaisonnalisée ; le tableau a aussi « {other} », "
                    "d'ordinaire le chiffre de référence d'une période à l'autre.",
                )
            )
    return notes, basis is not None
