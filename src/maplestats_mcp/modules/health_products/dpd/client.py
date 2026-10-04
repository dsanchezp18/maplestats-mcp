"""Client for the Drug Product Database (DPD) API.

Checked live 2026-10-03 (see also ../api.py):

1. `drugproduct` filters on `din` (exact, despite the guide's %...%
   wording: "0224270" finds nothing), `brandname` (substring), `status`
   (a code) and `id` (the drug code). It has no company or ingredient
   filter: `companyname=` is ignored and returns all 58,310 rows. So
   searches by company, schedule or ATC class run over the whole tables,
   cached for six hours; an ingredient search uses the API's own
   `activeingredient?ingredientname=` filter (substring, 1,378 rows for
   acetaminophen) and joins the product table by drug code.
2. With `lang=fr` the API translates the class ("Humain"), status
   ("Commercialisé"), schedule, route and form, and ingredient names
   ("Acétaminophène"); brand and company names are the same in both. The
   tables are cached in English and the labels mapped through constants.
3. The schedule table spells names in upper case ("NON-PRESCRIPTION
   DRUGS"), 330 rows have an empty schedule, and a product can have more
   than one (PRESCRIPTION and SCHEDULE D).
4. `status?id=` answers one object (the current status, with the original
   market date, and for a discontinued product the last lot number and
   expiry date); `packaging?id=` one object whose `product_information`
   holds every package ("Pharmachoice [100 Capsule Bottle]/Rexall [...]")
   since May 2025; `veterinaryspecies?id=` 404 for a non-veterinary
   product.
5. The company record is keyed by company code, which no product row
   carries, so a product's company is matched by name in the company table.
"""

from __future__ import annotations

import asyncio
import re
from collections import Counter
from typing import Any

from maplestats_mcp.modules.health_products import api
from maplestats_mcp.modules.health_products.dpd import constants
from maplestats_mcp.modules.health_products.dpd.schemas import (
    ActiveIngredient,
    DrugCompany,
    DrugProductDetail,
    DrugProductList,
    DrugProductSummary,
    IngredientList,
    IngredientMatch,
    TherapeuticClass,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.errors import InvalidInput, NotFound

# Product index row: drug code, DIN, brand, descriptor, company, class,
# number of active ingredients, AI group number, last update date.
Row = tuple[int, str, str, str, str, str, int | None, str, str]
_DIN = re.compile(r"^\d{1,8}$")
_PRODUCT_CLASSES = {
    "human": "Human",
    "veterinary": "Veterinary",
    "disinfectant": "Disinfectant",
    "radiopharmaceutical": "Radiopharmaceutical",
}


def _fold(value: str) -> str:
    return " ".join(value.casefold().split())


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _status_label(code: int | None, lang: str) -> str | None:
    if code is None:
        return None
    labels = constants.STATUSES.get(code)
    if labels is None:
        return f"Status {code}"
    return labels[1] if lang == "fr" else labels[0]


def _class_label(name: str, lang: str) -> str | None:
    if not name:
        return None
    return constants.CLASSES_FR.get(name, name) if lang == "fr" else name


# ------------------------------------------------------------------ tables


async def _fetch_table(path: str) -> list[dict[str, Any]]:
    """A whole English table, uncached: callers cache a compact form of it."""
    return api.as_list(await api.get_json(path, lang="en", timeout=120.0))


async def _product_index() -> tuple[list[Row], bool]:
    async def fetch() -> list[Row]:
        rows = await _fetch_table(constants.PATH_PRODUCT)
        return [
            (
                int(r["drug_code"]),
                api.text(r.get("drug_identification_number")) or "",
                api.text(r.get("brand_name")) or "",
                api.text(r.get("descriptor")) or "",
                api.text(r.get("company_name")) or "",
                api.text(r.get("class_name")) or "",
                _int(r.get("number_of_ais")),
                api.text(r.get("ai_group_no")) or "",
                api.text(r.get("last_update_date")) or "",
            )
            for r in rows
            if r.get("drug_code")
        ]

    return await cached_fetch("hc_dpd:index", constants.TABLE_TTL_SECONDS, fetch)


async def _status_map() -> dict[int, tuple[int | None, str]]:
    async def fetch() -> dict[int, tuple[int | None, str]]:
        rows = await _fetch_table(constants.PATH_STATUS)
        return {
            int(r["drug_code"]): (_int(r.get("external_status_code")), r.get("history_date") or "")
            for r in rows
            if r.get("drug_code")
        }

    data, _ = await cached_fetch("hc_dpd:status", constants.TABLE_TTL_SECONDS, fetch)
    return data


async def _schedule_map() -> dict[int, tuple[str, ...]]:
    async def fetch() -> dict[int, tuple[str, ...]]:
        rows = await _fetch_table(constants.PATH_SCHEDULE)
        out: dict[int, list[str]] = {}
        for r in rows:
            name = api.text(r.get("schedule_name"))
            if r.get("drug_code") and name:
                out.setdefault(int(r["drug_code"]), []).append(name.upper())
        return {code: tuple(names) for code, names in out.items()}

    data, _ = await cached_fetch("hc_dpd:schedule", constants.TABLE_TTL_SECONDS, fetch)
    return data


async def _atc_map() -> dict[int, tuple[tuple[str, str], ...]]:
    async def fetch() -> dict[int, tuple[tuple[str, str], ...]]:
        rows = await _fetch_table(constants.PATH_ATC)
        out: dict[int, list[tuple[str, str]]] = {}
        for r in rows:
            if r.get("drug_code"):
                out.setdefault(int(r["drug_code"]), []).append(
                    ((r.get("tc_atc_number") or "").upper(), r.get("tc_atc") or "")
                )
        return {code: tuple(v) for code, v in out.items()}

    data, _ = await cached_fetch("hc_dpd:atc", constants.TABLE_TTL_SECONDS, fetch)
    return data


def _summary(row: Row, status: tuple[int | None, str] | None, lang: str) -> DrugProductSummary:
    code, din, brand, descriptor, company, klass, n_ai, group, updated = row
    status_code = status[0] if status else None
    return DrugProductSummary(
        drug_code=code,
        din=din or None,
        brand_name=brand or None,
        descriptor=descriptor or None,
        company_name=company or None,
        product_class=_class_label(klass, lang),
        number_of_active_ingredients=n_ai,
        ai_group_no=group or None,
        status=_status_label(status_code, lang),
        status_code=status_code,
        status_date=(status[1] or None) if status else None,
        last_update_date=updated or None,
    )


def _normalise_din(din: str, lang: str = "en") -> str:
    cleaned = din.strip().replace(" ", "")
    if not _DIN.match(cleaned):
        api.fail(
            InvalidInput,
            f"'{din}' is not a DIN: a DIN is up to 8 digits, e.g. 02242705.",
            f"'{din}' n'est pas un DIN : un DIN compte au plus 8 chiffres, p. ex. 02242705.",
            lang,
        )
    return cleaned.zfill(8)


# ------------------------------------------------------------------ search


async def search_products(
    *,
    din: str = "",
    brand: str = "",
    ingredient: str = "",
    company: str = "",
    status: str | None = None,
    schedule: str = "",
    atc: str = "",
    product_class: str | None = None,
    limit: int = constants.LIMIT_DEFAULT,
    lang: str = "en",
) -> DrugProductList:
    if not any((din, brand.strip(), ingredient.strip(), company.strip(), schedule, atc, status)):
        api.fail(
            InvalidInput,
            "Give at least one of din, brand, ingredient, company, status, schedule or atc.",
            "donnez au moins l'un de din, brand, ingredient, company, status, schedule ou atc.",
            lang,
        )
    if not 1 <= limit <= constants.LIMIT_MAX:
        api.fail(
            InvalidInput,
            f"limit must be between 1 and {constants.LIMIT_MAX}.",
            f"limit doit être compris entre 1 et {constants.LIMIT_MAX}.",
            lang,
        )
    status_code = None
    if status is not None:
        status_code = constants.STATUS_KEYS.get(status)
        if status_code is None:
            keys = sorted(constants.STATUS_KEYS)
            api.fail(
                InvalidInput,
                f"Unknown status '{status}': use {keys}.",
                f"statut inconnu '{status}' : utilisez {keys}.",
                lang,
            )
    klass = None
    if product_class is not None:
        klass = _PRODUCT_CLASSES.get(product_class)
        if klass is None:
            classes = sorted(_PRODUCT_CLASSES)
            api.fail(
                InvalidInput,
                f"product_class must be one of {classes}.",
                f"product_class doit valoir l'une de {classes}.",
                lang,
            )

    index, cached = await api.in_lang(lang, _product_index())
    statuses = await api.in_lang(lang, _status_map())
    rows = index
    filters: list[str] = []

    contains = "contient" if lang == "fr" else "contains"
    if din:
        wanted = _normalise_din(din, lang)
        rows = [r for r in rows if r[1] == wanted]
        filters.append(f"din={wanted}")
    if brand.strip():
        needle = _fold(brand)
        rows = [r for r in rows if needle in _fold(f"{r[2]} {r[3]}")]
        filters.append(f"brand {contains} '{brand.strip()}'")
    if company.strip():
        needle = _fold(company)
        rows = [r for r in rows if needle in _fold(r[4])]
        filters.append(f"company {contains} '{company.strip()}'")
    if ingredient.strip():
        found = api.as_list(
            await api.in_lang(
                lang,
                api.get_json(
                    constants.PATH_INGREDIENT,
                    {"ingredientname": ingredient.strip()},
                    lang=lang,
                    timeout=90.0,
                ),
            )
        )
        codes = {int(r["drug_code"]) for r in found if r.get("drug_code")}
        rows = [r for r in rows if r[0] in codes]
        filters.append(f"ingredient {contains} '{ingredient.strip()}'")
    if status_code is not None:
        rows = [r for r in rows if statuses.get(r[0], (None, ""))[0] == status_code]
        filters.append(f"status={status}")
    if klass is not None:
        rows = [r for r in rows if r[5] == klass]
        filters.append(f"class={product_class}")
    if schedule.strip():
        needle = _fold(schedule)
        schedules = await api.in_lang(lang, _schedule_map())
        rows = [
            r
            for r in rows
            if any(
                needle in _fold(name) or needle in _fold(constants.SCHEDULES_FR.get(name, ""))
                for name in schedules.get(r[0], ())
            )
        ]
        filters.append(f"schedule {contains} '{schedule.strip()}'")
    if atc.strip():
        needle = atc.strip().upper()
        folded = _fold(atc)
        classes = await api.in_lang(lang, _atc_map())
        rows = [
            r
            for r in rows
            if any(
                code.startswith(needle) or folded in _fold(desc)
                for code, desc in classes.get(r[0], ())
            )
        ]
        filters.append(
            api.say(
                f"ATC starts with or names '{atc.strip()}'",
                f"ATC commence par ou nomme '{atc.strip()}'",
                lang,
            )
        )

    # Marketed and approved products first, then by brand name.
    order = {2: 0, 1: 1, 6: 2, 13: 3}
    rows = sorted(
        rows,
        key=lambda r: (order.get(statuses.get(r[0], (None, ""))[0] or 0, 9), r[2], r[1]),
    )
    by_status = Counter(
        _status_label(statuses.get(r[0], (None, ""))[0], lang) or "Unknown" for r in rows
    )
    products = [_summary(r, statuses.get(r[0]), lang) for r in rows[:limit]]
    coverage = f"{len(products)} of {len(rows)} products matching {', '.join(filters)}"
    return DrugProductList(
        products=products,
        returned_count=len(products),
        total_matched=len(rows),
        by_status=dict(by_status.most_common()),
        provenance=api.provenance(
            api.url_for(constants.PATH_PRODUCT),
            cached=cached,
            schema="DrugProductList",
            freshness=constants.FRESHNESS,
            coverage=coverage,
            limits=f"limit {limit}; whole DPD tables cached up to 6 h",
            lang=lang,
            freshness_fr=constants.FRESHNESS_FR,
            coverage_fr=f"{len(products)} produits sur {len(rows)} correspondant à "
            f"{', '.join(filters)}",
            limits_fr=f"limit {limit} ; tables complètes de la BDPP en cache jusqu'à 6 h",
        ),
    )


async def search_ingredients(name: str, *, limit: int = 50, lang: str = "en") -> IngredientList:
    term = name.strip()
    if len(term) < 3:
        api.fail(
            InvalidInput,
            "Give at least 3 letters of an ingredient name, e.g. 'metformin'.",
            "donnez au moins 3 lettres d'un nom d'ingrédient, p. ex. 'metformine'.",
            lang,
        )
    if not 1 <= limit <= constants.LIMIT_MAX:
        api.fail(
            InvalidInput,
            f"limit must be between 1 and {constants.LIMIT_MAX}.",
            f"limit doit être compris entre 1 et {constants.LIMIT_MAX}.",
            lang,
        )

    async def fetch() -> list[dict[str, Any]]:
        return api.as_list(
            await api.get_json(
                constants.PATH_INGREDIENT, {"ingredientname": term}, lang=lang, timeout=90.0
            )
        )

    rows, cached = await api.in_lang(
        lang,
        cached_fetch(
            f"hc_dpd:ingredient:{lang}:{term.casefold()}", constants.LOOKUP_TTL_SECONDS, fetch
        ),
    )
    products: dict[str, set[int]] = {}
    strengths: dict[str, Counter[str]] = {}
    for r in rows:
        ingredient = api.text(r.get("ingredient_name"))
        if not ingredient or not r.get("drug_code"):
            continue
        products.setdefault(ingredient, set()).add(int(r["drug_code"]))
        strength = " ".join(
            part for part in (api.text(r.get("strength")), api.text(r.get("strength_unit"))) if part
        )
        per = " ".join(
            part
            for part in (api.text(r.get("dosage_value")), api.text(r.get("dosage_unit")))
            if part
        )
        if strength:
            strengths.setdefault(ingredient, Counter())[
                f"{strength} / {per}" if per else strength
            ] += 1
    ranked = sorted(products, key=lambda k: (-len(products[k]), k))
    matches = [
        IngredientMatch(
            name=k,
            product_count=len(products[k]),
            strengths=[s for s, _ in strengths.get(k, Counter()).most_common(8)],
        )
        for k in ranked[:limit]
    ]
    return IngredientList(
        ingredients=matches,
        total_matched=len(ranked),
        provenance=api.provenance(
            api.url_for(constants.PATH_INGREDIENT),
            cached=cached,
            schema="IngredientList",
            freshness=constants.FRESHNESS,
            coverage=f"{len(matches)} of {len(ranked)} ingredient names containing '{term}'",
            lang=lang,
            freshness_fr=constants.FRESHNESS_FR,
            coverage_fr=f"{len(matches)} noms d'ingrédients sur {len(ranked)} contenant '{term}'",
        ),
    )


# ------------------------------------------------------------------ detail


async def _resolve_code(din: str, drug_code: int | None, lang: str = "en") -> int:
    if drug_code is not None:
        if drug_code <= 0:
            api.fail(
                InvalidInput,
                "drug_code must be a positive number.",
                "drug_code doit être un nombre positif.",
                lang,
            )
        return drug_code
    if not din:
        api.fail(
            InvalidInput,
            "Give a din (e.g. 02242705) or a drug_code.",
            "donnez un din (p. ex. 02242705) ou un drug_code.",
            lang,
        )
    wanted = _normalise_din(din, lang)
    answer = await api.in_lang(lang, api.get_json(constants.PATH_PRODUCT, {"din": wanted}))
    found = [r for r in api.as_list(answer) if r.get("drug_code")]
    if not found:
        api.fail(
            NotFound,
            f"No drug product in the DPD has DIN {wanted}.",
            f"aucun produit de la BDPP n'a le DIN {wanted}.",
            lang,
        )
    if len(found) > 1:
        codes = ", ".join(str(r["drug_code"]) for r in found)
        api.fail(
            InvalidInput,
            f"DIN {wanted} belongs to several DPD products (drug codes {codes}); pass drug_code.",
            f"le DIN {wanted} appartient à plusieurs produits de la BDPP (codes {codes}) ; "
            "passez drug_code.",
            lang,
        )
    return int(found[0]["drug_code"])


async def _company(name: str | None, lang: str) -> DrugCompany | None:
    if not name:
        return None
    rows, _ = await cached_fetch(
        "hc_dpd:companies",
        constants.TABLE_TTL_SECONDS,
        lambda: _fetch_table(constants.PATH_COMPANY),
    )
    wanted = _fold(name)
    match = next((r for r in rows if _fold(r.get("company_name") or "") == wanted), None)
    if match is None:
        return None
    street = " ".join(
        p for p in (api.text(match.get("suite_number")), api.text(match.get("street_name"))) if p
    )
    province = api.text(match.get("province_name"))
    del lang  # The company table has no translated fields.
    return DrugCompany(
        company_code=_int(match.get("company_code")),
        name=api.text(match.get("company_name")) or name,
        company_type=api.text(match.get("company_type")),
        street=street or None,
        city=api.text(match.get("city_name")),
        province=None if province == "--" else province,
        country=api.text(match.get("country_name")),
        postal_code=api.text(match.get("postal_code")),
    )


async def get_product(
    din: str = "", drug_code: int | None = None, *, lang: str = "en"
) -> DrugProductDetail:
    code = await _resolve_code(din, drug_code, lang)

    async def fetch() -> DrugProductDetail:
        by_id = {"id": code}
        (
            product,
            ingredients,
            status,
            schedules,
            forms,
            routes,
            classes,
            packaging,
            standard,
            species,
        ) = await asyncio.gather(
            api.get_json(constants.PATH_PRODUCT, by_id, lang=lang),
            api.get_json(constants.PATH_INGREDIENT, by_id, lang=lang, missing_ok=True),
            api.get_json(constants.PATH_STATUS, by_id, lang=lang, missing_ok=True),
            api.get_json(constants.PATH_SCHEDULE, by_id, lang=lang, missing_ok=True),
            api.get_json(constants.PATH_FORM, by_id, lang=lang, missing_ok=True),
            api.get_json(constants.PATH_ROUTE, by_id, lang=lang, missing_ok=True),
            api.get_json(constants.PATH_ATC, by_id, lang=lang, missing_ok=True),
            api.get_json(constants.PATH_PACKAGING, by_id, lang=None, missing_ok=True),
            api.get_json(constants.PATH_STANDARD, by_id, lang=None, missing_ok=True),
            api.get_json(constants.PATH_SPECIES, by_id, lang=lang, missing_ok=True),
        )
        products = [r for r in api.as_list(product) if not api.is_blank(r, "drug_code")]
        if not products:
            api.fail(
                NotFound,
                f"No drug product in the DPD has drug code {code}.",
                f"aucun produit de la BDPP n'a le code {code}.",
                lang,
            )
        p = products[0]
        statuses = [r for r in api.as_list(status) if not api.is_blank(r, "drug_code")]
        s = statuses[0] if statuses else {}
        status_code = _int(s.get("external_status_code"))
        summary = DrugProductSummary(
            drug_code=code,
            din=api.text(p.get("drug_identification_number")),
            brand_name=api.text(p.get("brand_name")),
            descriptor=api.text(p.get("descriptor")),
            company_name=api.text(p.get("company_name")),
            product_class=api.text(p.get("class_name")),
            number_of_active_ingredients=_int(p.get("number_of_ais")),
            ai_group_no=api.text(p.get("ai_group_no")),
            status=api.text(s.get("status")) or _status_label(status_code, lang),
            status_code=status_code,
            status_date=api.text(s.get("history_date")),
            last_update_date=api.text(p.get("last_update_date")),
        )
        packages: list[str] = []
        for r in api.as_list(packaging):
            if api.is_blank(r, "drug_code"):
                continue
            info = api.text(r.get("product_information"))
            older = " ".join(
                x
                for x in (
                    api.text(r.get("package_size")),
                    api.text(r.get("package_size_unit")),
                    api.text(r.get("package_type")),
                )
                if x
            )
            packages.extend(x for x in (info, older) if x)
        standards = [
            api.text(r.get("pharmaceutical_std"))
            for r in api.as_list(standard)
            if not api.is_blank(r, "drug_code")
        ]
        return DrugProductDetail(
            product=summary,
            original_market_date=api.text(s.get("original_market_date")),
            lot_number=api.text(s.get("lot_number")),
            expiration_date=api.text(s.get("expiration_date")),
            active_ingredients=[
                ActiveIngredient(
                    name=api.text(r.get("ingredient_name")) or "",
                    strength=api.text(r.get("strength")),
                    strength_unit=api.text(r.get("strength_unit")),
                    dosage_value=api.text(r.get("dosage_value")),
                    dosage_unit=api.text(r.get("dosage_unit")),
                )
                for r in api.as_list(ingredients)
                if api.text(r.get("ingredient_name"))
            ],
            schedules=[
                name for r in api.as_list(schedules) if (name := api.text(r.get("schedule_name")))
            ],
            dosage_forms=[
                name
                for r in api.as_list(forms)
                if (name := api.text(r.get("pharmaceutical_form_name")))
            ],
            routes=[
                name
                for r in api.as_list(routes)
                if (name := api.text(r.get("route_of_administration_name")))
            ],
            therapeutic_classes=[
                TherapeuticClass(
                    atc_code=api.text(r.get("tc_atc_number")),
                    atc_description=api.text(r.get("tc_atc")),
                )
                for r in api.as_list(classes)
                if api.text(r.get("tc_atc_number")) or api.text(r.get("tc_atc"))
            ],
            packaging=packages,
            pharmaceutical_standard=next((x for x in standards if x), None),
            veterinary_species=[
                name for r in api.as_list(species) if (name := api.text(r.get("vet_species_name")))
            ],
            company=await _company(api.text(p.get("company_name")), lang),
            dpd_page=constants.SEARCH_PAGE,
            provenance=api.provenance(
                f"{api.url_for(constants.PATH_PRODUCT)}?id={code}&lang={lang}&type=json",
                cached=False,
                schema="DrugProductDetail",
                freshness=constants.FRESHNESS,
                lang=lang,
                freshness_fr=constants.FRESHNESS_FR,
                limits_fr="Les noms de marque, de fabricant et d'ingrédient sont ceux "
                "déposés auprès de Santé Canada, souvent en anglais.",
            ),
        )

    detail, cached = await api.in_lang(
        lang, cached_fetch(f"hc_dpd:product:{code}:{lang}", constants.LOOKUP_TTL_SECONDS, fetch)
    )
    if cached:
        detail = detail.model_copy(
            update={"provenance": detail.provenance.model_copy(update={"cached": True})}
        )
    return detail
