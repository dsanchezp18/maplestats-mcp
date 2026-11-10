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
  adjusted member, so it gets no note. When the table title says "seasonally
  adjusted" (14-10-0287, "..., seasonally adjusted and trend-cycle") the note
  names the series' own member, since the title sits in every citation; a
  "Trend-cycle" member gets its own note.

Checked live on 2026-11-09 against 36-10-0104 and 36-10-0711:

- Percentage change at annual rates: "Chained (2017) dollars percentage change"
  under "Seasonally adjusted at annual rates" is the change from the previous
  quarter (2026-Q2 GDP 0.8 = 2,524,127 / 2,503,604 - 1), not an annualized
  rate, and so is "Contributions to percent change" (GDP 0.82); the table's
  "Contributions to percent change, annualized" member is the annualized one
  (GDP 3.316).
- "Less:" lines: WDS publishes contributions on "Less: imports of goods and
  services" with the sign of the imports' own change (2026-Q2 +0.09, annualized
  +0.364, while imports rose), and on its children too (goods +0.143, services
  -0.053). The components reach the GDP contribution (0.82) only when that line
  is subtracted: 0.662 + 0.287 - 1.215 + 1.17 - 0.09 + 0.006.
- Not available (status 1, ".."): 36-10-0711's current-dollar "All industries"
  series is ".." for 2024 and 2025 in every province and territory, while
  "Chained (2017) dollars" has both years. Only trailing ".." periods get a
  note, since rows before a series starts are ".." too.

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

STATUS_NOT_AVAILABLE = 1
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
_PERCENT_CHANGE = re.compile(r"\bper(?:cent|centage) change\b", re.IGNORECASE)
_CONTRIBUTIONS = re.compile(r"\bcontributions? to per(?:cent|centage) change", re.IGNORECASE)
_ANNUALIZED = re.compile(r"annuali[sz]ed", re.IGNORECASE)
_ANNUAL_RATES = re.compile(r"\bat annual rates?\b", re.IGNORECASE)
_LESS = re.compile(r"^\s*less\s*:\s*", re.IGNORECASE)
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


def trailing_unavailable(flags: Iterable[Flag]) -> list[date]:
    """The ".." (not available) periods after the last period with any other status.

    Rows before a series starts are ".." as well, so only the trailing ones say
    that StatCan has not published the latest periods (36-10-0711's current
    dollars for 2024 and 2025, checked live 2026-11-09).
    """
    flags = list(flags)
    published = [day for day, status, _ in flags if status != STATUS_NOT_AVAILABLE]
    last = max(published) if published else None
    return sorted(
        day
        for day, status, _ in flags
        if status == STATUS_NOT_AVAILABLE and (last is None or day > last)
    )


def flag_notes(flags: Iterable[Flag], frequency_code: int | None, lang: str) -> list[str]:
    """E, F and x periods among the observations returned, and trailing "..", named."""
    flags = list(flags)
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
    if missing := trailing_unavailable(flags):
        periods = _periods(missing, frequency_code, lang)
        notes.append(
            pick(
                lang,
                f"Not available (..) for {periods}: StatCan has not published a value for "
                "these latest periods in this series (status 'not available for a specific "
                "reference period'). Do not estimate one; say it is not published, and look "
                "for another series or table that has it.",
                f"Indisponible (..) pour {periods} : Statistique Canada n'a pas publié de "
                "valeur pour ces dernières périodes dans cette série (statut « indisponible "
                "pour une période de référence précise »). N'en estimez pas ; dites qu'elle "
                "n'est pas publiée et cherchez une autre série ou un autre tableau qui l'a.",
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


def trend_cycle_sibling(members: Sequence[tuple[dict, dict]]) -> tuple[dict, dict] | None:
    """(the series' Trend-cycle member, its Seasonally adjusted sibling), as in 14-10-0287."""
    for dim, member in members:
        if not str(member.get("memberNameEn") or "").strip().lower().startswith("trend-cycle"):
            continue
        for other in list_or_empty(dim, "member"):
            if str(other.get("memberNameEn") or "").strip().lower() == "seasonally adjusted":
                return member, other
    return None


def _period_word(frequency_code: int | None, lang: str) -> tuple[str, int | None]:
    """('quarter', 4) or ('month', 12): the period a change is measured over, and
    how many of them make a year (None when the frequency is neither)."""
    if frequency_code in (9, 19):
        return pick(lang, "quarter", "trimestre"), 4
    if frequency_code == 6:
        return pick(lang, "month", "mois"), 12
    return pick(lang, "period", "période"), None


def percent_change_note(
    members: Sequence[tuple[dict, dict]], frequency_code: int | None, lang: str
) -> str | None:
    """A percentage change (or contribution to it) in a table at annual rates.

    "Seasonally adjusted at annual rates" describes the levels: 36-10-0104's
    "Chained (2017) dollars percentage change" is the change from the previous
    quarter (2026-Q2 0.8 = 2,524,127 / 2,503,604 - 1, live 2026-11-09), easy to
    read as annualized. A member that says "annualized" is left alone.
    """
    if frequency_code not in _SUB_ANNUAL:
        return None
    if not any(_ANNUAL_RATES.search(str(m.get("memberNameEn") or "")) for _, m in members):
        return None
    for dim, member in members:
        name_en = str(member.get("memberNameEn") or "").strip()
        if not _PERCENT_CHANGE.search(name_en) or _ANNUALIZED.search(name_en):
            continue
        name = member_name(member, lang)
        period, per_year = _period_word(frequency_code, lang)
        annualized = next(
            (
                other
                for other in list_or_empty(dim, "member")
                if str(other.get("memberNameEn") or "").strip().lower().startswith(name_en.lower())
                and _ANNUALIZED.search(str(other.get("memberNameEn") or ""))
            ),
            None,
        )
        if annualized is not None:
            other = member_name(annualized, lang)
            tail_en = f" The table's '{other}' member is the annualized figure."
            tail_fr = f" Le membre « {other} » du tableau donne le chiffre annualisé."
        elif per_year:
            tail_en = (
                f" An annualized rate compounds it: ((1 + x/100)^{per_year} - 1) x 100; say "
                "which one you report."
            )
            tail_fr = (
                f" Un taux annualisé le compose : ((1 + x/100)^{per_year} - 1) x 100 ; "
                "précisez lequel vous donnez."
            )
        else:
            tail_en = tail_fr = ""
        return pick(
            lang,
            f"'{name}' is the change from the previous {period}, not an annualized rate: "
            f"'at annual rates' describes the levels only.{tail_en}",
            f"« {name} » est la variation par rapport au {period} précédent, pas un taux "
            f"annualisé : « aux taux annuels » ne s'applique qu'aux niveaux.{tail_fr}",
        )
    return None


def less_line_note(members: Sequence[tuple[dict, dict]], lang: str) -> str | None:
    """A contribution to percent change on a "Less:" line or one of its children.

    WDS publishes it with the sign of the line's own change: 36-10-0104's
    "Less: imports of goods and services" was +0.09 in 2026-Q2 (annualized
    +0.364) while imports rose, and the components reach GDP's 0.82 only with
    it subtracted (live 2026-11-09). Imports of goods (+0.143) and services
    (-0.053), its children, follow the same sign.
    """
    if not any(_CONTRIBUTIONS.search(str(m.get("memberNameEn") or "")) for _, m in members):
        return None
    for dim, member in members:
        by_id = {int(m["memberId"]): m for m in list_or_empty(dim, "member")}
        line: dict | None = member
        seen: set[int] = set()
        while line is not None and not _LESS.match(str(line.get("memberNameEn") or "")):
            parent = line.get("parentMemberId")
            if parent is None or int(parent) in seen:
                line = None
                break
            seen.add(int(parent))
            line = by_id.get(int(parent))
        if line is None:
            continue
        name = member_name(line, lang)
        what_en = _LESS.sub("", str(line.get("memberNameEn") or "")).strip()
        what_fr = re.sub(
            r"^\s*moins\s*:\s*", "", member_name(line, "fr"), flags=re.IGNORECASE
        ).strip()
        return pick(
            lang,
            f"Contribution on a 'Less:' line ('{name}'): StatCan publishes it with the sign of "
            f"the change in {what_en}, so a positive value means {what_en} rose, which lowered "
            "growth. Subtract it when adding the components up to the total.",
            f"Contribution d'une ligne « Moins : » (« {name} ») : Statistique Canada la publie "
            f"avec le signe de la variation de « {what_fr} » ; une valeur positive signifie une "
            "hausse, qui a réduit la croissance. Soustrayez-la pour retrouver le total à partir "
            "des composantes.",
        )
    return None


_UNADJUSTED = re.compile(r"\bnot seasonally adjusted|unadjusted", re.IGNORECASE)


def seasonally_adjusted(names: Sequence[str]) -> bool:
    """Whether the series is seasonally adjusted: `names` is the table title, then
    the series' member names, and a member's word wins over the title's (a table
    titled "seasonally adjusted" can still hold an "Unadjusted" member)."""
    for text in [*names[1:], names[0]] if names else []:
        if _UNADJUSTED.search(text):
            return False
        if "seasonally adjusted" in text.lower():
            return True
    return False


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
    if moving and seasonally_adjusted(names):
        # A seasonally adjusted average (14-10-0459) can be compared with the
        # month before; the same-months-a-year-earlier advice is for unadjusted
        # series only, as the lfs-subprovincial-moving-averages rule says.
        word = (moving.group(1) or "").lower() or "several"
        fr_word = _NUMBERS_FR.get(word, "plusieurs" if word == "several" else word)
        notes.append(
            pick(
                lang,
                f"{word.capitalize()}-month moving average, seasonally adjusted: each value "
                f"averages {word} months, so consecutive values share most of them; say so "
                "when you report a change.",
                f"Moyenne mobile de {fr_word} mois, désaisonnalisée : chaque valeur couvre "
                f"{fr_word} mois, et deux valeurs consécutives en partagent la plupart ; "
                "dites-le en rapportant une variation.",
            )
        )
    elif moving:
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

    if change := percent_change_note(members, frequency, lang):
        notes.append(change)
    if less := less_line_note(members, lang):
        notes.append(less)

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
        # The table title is in every citation, and 14-10-0287's says "seasonally
        # adjusted and trend-cycle" for its Unadjusted series too, so the note
        # names the series' own member when the title says otherwise.
        title_says_adjusted = "seasonally adjusted" in names[0].lower()
        sibling = adjusted_sibling(members)
        trend = trend_cycle_sibling(members)
        if sibling:
            dim, own, adjusted = sibling
            other = _name(adjusted, "memberName", lang)
            if title_says_adjusted:
                dim_name = _name(dim, "dimensionName", lang)
                own_name = _name(own, "memberName", lang)
                notes.append(
                    pick(
                        lang,
                        f"Unadjusted series ({dim_name}: '{own_name}'), although the table "
                        f"title says seasonally adjusted; the table also has '{other}', "
                        "usually the headline for change from one period to the next.",
                        f"Série non désaisonnalisée ({dim_name} : « {own_name} »), même si "
                        f"le titre du tableau dit désaisonnalisé ; le tableau a aussi "
                        f"« {other} », d'ordinaire celle qu'on compare d'une période à "
                        "l'autre.",
                    )
                )
            else:
                notes.append(
                    pick(
                        lang,
                        f"Unadjusted series; the table also has '{other}', usually the "
                        "headline for change from one period to the next.",
                        f"Série non désaisonnalisée ; le tableau a aussi « {other} », "
                        "d'ordinaire celle qu'on compare d'une période à l'autre.",
                    )
                )
        elif trend:
            other = _name(trend[1], "memberName", lang)
            notes.append(
                pick(
                    lang,
                    "Trend-cycle series: a smoothed version of the seasonally adjusted "
                    f"series, revised as new periods arrive; the headline is '{other}'.",
                    "Série tendance-cycle : version lissée de la série désaisonnalisée, "
                    f"révisée à chaque nouvelle période ; le chiffre principal est « {other} ».",
                )
            )
    return notes, basis is not None
