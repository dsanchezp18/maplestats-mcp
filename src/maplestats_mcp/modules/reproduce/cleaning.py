"""Cleaning appended to every reproduction script, per language.

Each script loads the data into `data` and applies the tool's filters on
the source's own column names. Then: R cleans names (janitor) before the
source-specific step; Python, Stata and Julia run the source-specific
step on the loaded names and clean names in the standard step. The
standard step gives consistent snake_case names, trimmed text, empty
strings as missing and numbers stored as text converted.

Each entry is a spec.Code: imports go to the script's setup section, so
no script loads a package midway (house convention).
"""

from __future__ import annotations

from maplestats_mcp.modules.reproduce.spec import Code

# Columns that hold codes, by their cleaned name: StatCan coordinates
# ("2.1" and "2.10" are different members), vector and product ids, DGUIDs,
# postal codes and FSAs, NAICS, NOC and SGC codes. They stay text, as do
# columns with a leading zero ("01", "000000001"). Checked live 2026-10-03:
# read as numbers, 18-10-0004's 2,139 coordinates collapsed to 2,011.
# Written for every engine (R's ICU, Python re, Julia PCRE, Stata regexm).
CODE_COLUMNS = (
    r"^(coordinate|vector|vector_?id|product_?id|pid|dguid|[a-z0-9_]*_dguid|postal_?code|"
    r"[a-z0-9_]*_postal_code|fsa|[a-z0-9_]*naics[a-z0-9_]*|noc|noc_[a-z0-9_]*|[a-z0-9_]*_noc|"
    r"sgc|sgc_[a-z0-9_]*|[a-z0-9_]*_sgc)$"
)
LEADING_ZERO = r"^-?0[0-9]"
# A "$" in a do-file string could start a global macro, so Stata matches the
# name followed by "|" instead of anchoring with "$".
_STATA_CODE_COLUMNS = CODE_COLUMNS.removesuffix("$") + "[|]"

GENERIC: dict[str, Code] = {
    "r": Code(
        ["dplyr", "purrr", "readr", "stringr"],
        (
            "# Standard cleaning: trimmed text, empty strings as missing, and numbers\n"
            "# stored as text converted to numbers. Codes stay text as the source\n"
            "# wrote them: columns named like one (coordinate, vector_id, dguid, NAICS,\n"
            "# postal code) and columns with a leading zero (01, 000000001).\n\n"
            f'code_columns <- "{CODE_COLUMNS}"\n'
            "data <- data |>\n"
            '  mutate(across(where(is.character), \\(x) na_if(str_trim(x), "")))\n'
            "keep_text <- names(data)[\n"
            "  str_detect(names(data), code_columns) |\n"
            "    map_lgl(\n"
            "      data,\n"
            f'      \\(column) is.character(column) && any(str_detect(column, "{LEADING_ZERO}"), na.rm = TRUE)\n'
            "    )\n"
            "]\n"
            "data <- data |>\n"
            "  mutate(\n"
            "    across(any_of(keep_text), \\(x) if (is.list(x)) x else as.character(x)),\n"
            "    across(where(is.character) & !any_of(keep_text), parse_guess)\n"
            "  )\n"
        ),
    ),
    "python": Code(
        ["import re", "import unicodedata"],
        (
            "# Standard cleaning: snake_case names as janitor's clean_names() gives them\n"
            "# in R (PÉRIODE -> periode, referenceNumber -> reference_number, # -> number,\n"
            "# % -> percent, apostrophes dropped, a leading digit prefixed with x),\n"
            "# trimmed text, empty strings as missing. Names that clean alike are\n"
            "# numbered as janitor numbers them (Indicator, indicator -> indicator,\n"
            "# indicator_2).\n\n"
            "clean_names = [\n"
            "    re.sub(\n"
            '        r"[^0-9a-z]+",\n'
            '        "_",\n'
            "        re.sub(\n"
            '            r"([a-z0-9])([A-Z])",\n'
            '            r"\\1_\\2",\n'
            '            "".join(\n'
            '                " " if unicodedata.category(ch)[0] in "PS" and not ch.isascii() else ch\n'
            '                for ch in unicodedata.normalize("NFKD", column.replace("\'", ""))\n'
            "            )\n"
            '            .replace("#", " number ")\n'
            '            .replace("%", " percent ")\n'
            '            .encode("ascii", "ignore")\n'
            "            .decode(),\n"
            "        ).lower(),\n"
            '    ).strip("_")\n'
            '    or "x"\n'
            "    for column in data.columns\n"
            "]\n"
            'clean_names = [f"x{name}" if name[0].isdigit() else name for name in clean_names]\n'
            "while len(set(clean_names)) < len(clean_names):\n"
            "    name_counts = {}\n"
            "    numbered = []\n"
            "    for name in clean_names:\n"
            "        name_counts[name] = name_counts.get(name, 0) + 1\n"
            "        count = name_counts[name]\n"
            '        numbered.append(name if count == 1 else f"{name}_{count}")\n'
            "    clean_names = numbered\n"
            "data = data.rename(dict(zip(data.columns, clean_names)))\n"
            'data = data.with_columns(pl.col(pl.Utf8).str.strip_chars().replace("", None))\n\n'
            "# Numbers stored as text become numbers. Codes stay text as the source\n"
            "# wrote them: columns named like one (coordinate, vector_id, dguid, NAICS,\n"
            "# postal code) and columns with a leading zero (01, 000000001).\n\n"
            f'code_columns = re.compile(r"{CODE_COLUMNS}")\n'
            "for column in data.columns:\n"
            "    dtype = data.schema[column]\n"
            "    if code_columns.search(column) and not dtype.is_nested():\n"
            "        data = data.with_columns(pl.col(column).cast(pl.Utf8))\n"
            "        continue\n"
            "    if dtype != pl.Utf8 or data[column].null_count() == data.height:\n"
            "        continue\n"
            "    numbers = data[column].cast(pl.Float64, strict=False)\n"
            f'    leading_zero = data[column].str.contains(r"{LEADING_ZERO}").any()\n'
            "    if numbers.null_count() > data[column].null_count() or leading_zero:\n"
            "        continue\n"
            "    whole = data[column].cast(pl.Int64, strict=False)\n"
            "    data = data.with_columns(whole if whole.null_count() == numbers.null_count() else numbers)\n"
        ),
    ),
    "stata": Code(
        [],
        (
            "* Standard cleaning: lower-case names, trimmed text, and numbers stored as\n"
            "* text converted (destring leaves genuinely non-numeric text alone). Codes\n"
            "* stay text as the source wrote them: variables named like one (coordinate,\n"
            "* vectorid, dguid, NAICS, postal code) and ones with a leading zero (01).\n"
            "* rename *, lower stops at a clash (Indicator next to indicator), so names\n"
            "* that lower-case alike are numbered as janitor numbers them (indicator,\n"
            "* indicator_2), then renamed in one group rename, which allows swaps.\n\n"
            "local names\n"
            "foreach var of varlist _all {\n"
            "    local names `names' `=strlower(\"`var'\")'\n"
            "}\n"
            "local dups : list dups names\n"
            'while "`dups\'" != "" {\n'
            "    local numbered\n"
            "    local before\n"
            "    foreach name of local names {\n"
            "        local count 1\n"
            "        foreach earlier of local before {\n"
            '            if "`earlier\'" == "`name\'" local ++count\n'
            "        }\n"
            "        local before `before' `name'\n"
            "        if `count' > 1 {\n"
            '            local name = substr("`name\'", 1, 32 - strlen("_`count\'")) + "_`count\'"\n'
            "        }\n"
            "        local numbered `numbered' `name'\n"
            "    }\n"
            "    local names `numbered'\n"
            "    local dups : list dups names\n"
            "}\n"
            "local old_names\n"
            "local new_names\n"
            "local i 0\n"
            "foreach var of varlist _all {\n"
            "    local ++i\n"
            "    local name : word `i' of `names'\n"
            '    if "`name\'" != "`var\'" {\n'
            "        local old_names `old_names' `var'\n"
            "        local new_names `new_names' `name'\n"
            "    }\n"
            "}\n"
            'if "`old_names\'" != "" {\n'
            "    rename (`old_names') (`new_names')\n"
            "}\n"
            "quietly ds, has(type string)\n"
            "local text_vars `r(varlist)'\n"
            "foreach var of local text_vars {\n"
            "    replace `var' = strtrim(`var')\n"
            f'    if regexm("`var\'|", "{_STATA_CODE_COLUMNS}") continue\n'
            f'    quietly count if regexm(`var\', "{LEADING_ZERO}")\n'
            "    if r(N) > 0 continue\n"
            "    destring `var', replace\n"
            "}\n"
        ),
    ),
    "julia": Code(
        ["DataFrames", "TidierData"],
        (
            "# Standard cleaning: snake_case names, trimmed text, empty strings as missing.\n\n"
            "data = @chain data begin\n    @clean_names\nend\n"
            "data = mapcols(\n"
            "    col -> eltype(col) <: Union{Missing, AbstractString} ?\n"
            "        [ismissing(x) || isempty(strip(x)) ? missing : strip(x) for x in col] : col,\n"
            "    data,\n"
            ")\n\n"
            "# Numbers stored as text become numbers. Codes stay text as the source\n"
            "# wrote them: columns named like one (coordinate, vector_id, dguid, NAICS,\n"
            "# postal code) and columns with a leading zero (01, 000000001).\n\n"
            f'code_columns = r"{CODE_COLUMNS}"\n'
            "for name in names(data)\n"
            "    column = data[!, name]\n"
            "    if occursin(code_columns, name)\n"
            "        data[!, name] = [ismissing(x) ? missing : string(x) for x in column]\n"
            "        continue\n"
            "    end\n"
            "    eltype(column) <: Union{Missing, AbstractString} || continue\n"
            "    values = collect(skipmissing(column))\n"
            f'    (isempty(values) || any(v -> occursin(r"{LEADING_ZERO}", v), values)) && continue\n'
            "    any(v -> isnothing(tryparse(Float64, v)), values) && continue\n"
            "    whole = all(v -> !isnothing(tryparse(Int, v)), values)\n"
            "    data[!, name] = [\n"
            "        ismissing(x) ? missing : parse(whole ? Int : Float64, x) for x in column\n"
            "    ]\n"
            "end\n"
        ),
    ),
}

# Runs before the standard step, so names are as the loader leaves them:
# R already snake_case (clean_names ran first), Stata as import delimited
# names them, Python and Julia as in the source file.
SPECIFIC: dict[str, dict[str, Code]] = {
    "statcan_table": {
        # cansim in R already returns val_norm (scaled value) and Date.
        "r": Code(
            ["dplyr"],
            (
                "# cansim adds val_norm (VALUE times its scalar factor) and a Date column;\n"
                "# keep STATUS and SYMBOL, which flag estimates to use with caution.\n\n"
                "data <- data |>\n  filter(!is.na(val_norm))\n"
            ),
        ),
        "python": Code(
            [],
            (
                "# VALUE is in the unit named by SCALAR_FACTOR; SCALAR_ID is its power of ten.\n\n"
                "data = data.with_columns(\n"
                "    (\n"
                '        pl.col("VALUE").cast(pl.Float64, strict=False)\n'
                '        * 10.0 ** pl.col("SCALAR_ID").cast(pl.Int64, strict=False)\n'
                '    ).alias("VALUE_NORMALIZED")\n'
                ")\n"
            ),
        ),
        "stata": Code(
            [],
            (
                "* value is in the unit named by scalar_factor; scalar_id is its power of ten.\n\n"
                "* Variables come in as text (codes keep their form); real() reads numbers.\n\n"
                "generate double value_normalized = real(value) * 10^real(scalar_id)\n"
            ),
        ),
        "julia": Code(
            [],
            (
                "# VALUE is in the unit named by SCALAR_FACTOR; SCALAR_ID is its power of ten.\n\n"
                "# Columns are read as text (codes keep their form), so numbers are parsed.\n\n"
                "data.VALUE_NORMALIZED = [\n"
                "    ismissing(v) || ismissing(s) ? missing : parse(Float64, v) * 10.0^parse(Int, s)\n"
                "    for (v, s) in zip(data.VALUE, data.SCALAR_ID)\n"
                "]\n"
            ),
        ),
    },
    "statcan_vectors": {
        "r": Code(
            ["dplyr"],
            (
                "# cansim adds val_norm (the value times its scalar factor) and a Date column.\n\n"
                "data <- data |>\n  filter(!is.na(val_norm))\n"
            ),
        ),
        "python": Code(
            [],
            (
                "# scalarFactorCode is the value's power of ten; refPer is the reference date.\n\n"
                "data = data.with_columns(\n"
                '    (pl.col("value") * 10 ** pl.col("scalarFactorCode")).alias("value_normalized"),\n'
                '    pl.col("refPer").str.to_date(strict=False).alias("ref_date"),\n'
                ")\n"
            ),
        ),
        "stata": Code(
            [],
            (
                "* scalarfactorcode is the value's power of ten.\n\n"
                "generate double value_normalized = real(value) * 10^real(scalarfactorcode)\n"
                'generate ref_date = date(refper, "YMD")\n'
                "format ref_date %td\n"
            ),
        ),
        "julia": Code(
            [],
            (
                "# scalarFactorCode is the value's power of ten.\n\n"
                "data.value_normalized = data.value .* 10.0 .^ data.scalarFactorCode\n"
            ),
        ),
    },
    "valet": {
        "r": Code(
            ["dplyr", "lubridate", "stringr", "tidyr"],
            (
                "# Valet nests each series as <series>.v; make one row per date and series.\n\n"
                "data <- data |>\n"
                '  pivot_longer(-d, names_to = "series", values_to = "value") |>\n'
                "  mutate(\n"
                '    series = str_remove(series, "_v$") |> str_to_upper(),\n'
                "    value = as.numeric(value),\n"
                "    date = ymd(d)\n"
                "  ) |>\n"
                "  select(date, series, value)\n"
            ),
        ),
        "python": Code(
            [],
            (
                "# Valet nests each series as <series>.v; make one row per date and series.\n\n"
                'data = data.unpivot(index="d", variable_name="series", value_name="value")\n'
                "data = data.with_columns(\n"
                '    pl.col("d").str.to_date().alias("date"),\n'
                '    pl.col("series").str.replace(r"\\.v$", ""),\n'
                '    pl.col("value").cast(pl.Float64, strict=False),\n'
                ').select("date", "series", "value")\n'
            ),
        ),
        "stata": Code(
            [],
            (
                "* One column per series (<series>_v), one row per date.\n\n"
                'generate date = date(d, "YMD")\n'
                "format date %td\n"
                "drop d\n"
            ),
        ),
        "julia": Code(
            ["DataFrames", "Dates"],
            (
                "# Valet nests each series as {v: value}; make one row per date and series.\n\n"
                'data = stack(data, Not("d"); variable_name = "series", value_name = "cell")\n'
                "data.value = [\n"
                "    ismissing(cell) ? missing :\n"
                '        something(tryparse(Float64, string(get(cell, :v, ""))), missing)\n'
                "    for cell in data.cell\n"
                "]\n"
                "data.date = Date.(data.d)\n"
                'data = select(data, "date", "series", "value")\n'
            ),
        ),
    },
}

# French full tables (checked 2026-09-24 on 18100004-fra): same columns in
# French, e.g. VALEUR and IDENTIFICATEUR SCALAIRE. cansim returns val_norm
# in both languages. Stata turns these accented, spaced headers into
# generic names, so its French version skips the scaling step.
SPECIFIC["statcan_table_fr"] = {
    "r": SPECIFIC["statcan_table"]["r"],
    "python": Code(
        [],
        (
            "# VALEUR est dans l'unité de FACTEUR SCALAIRE; IDENTIFICATEUR SCALAIRE en est\n"
            "# la puissance de dix.\n\n"
            "data = data.with_columns(\n"
            "    (\n"
            '        pl.col("VALEUR").cast(pl.Float64, strict=False)\n'
            '        * 10.0 ** pl.col("IDENTIFICATEUR SCALAIRE").cast(pl.Int64, strict=False)\n'
            '    ).alias("VALEUR_NORMALISEE")\n'
            ")\n"
        ),
    ),
    "julia": Code(
        [],
        (
            "# VALEUR est dans l'unité de FACTEUR SCALAIRE; IDENTIFICATEUR SCALAIRE en est\n"
            "# la puissance de dix.\n\n"
            "data.VALEUR_NORMALISEE = [\n"
            "    ismissing(v) || ismissing(s) ? missing : parse(Float64, v) * 10.0^parse(Int, s)\n"
            '    for (v, s) in zip(data.VALEUR, data[!, "IDENTIFICATEUR SCALAIRE"])\n'
            "]\n"
        ),
    ),
}


def specific(language: str, source: str) -> Code | None:
    return SPECIFIC.get(source, {}).get(language)
