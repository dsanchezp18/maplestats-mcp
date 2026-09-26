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

GENERIC: dict[str, Code] = {
    "r": Code(
        ["dplyr", "readr", "stringr"],
        (
            "# Standard cleaning: trimmed text, empty strings as missing, and numbers\n"
            "# stored as text converted to numbers.\n\n"
            "data <- data |>\n"
            '  mutate(across(where(is.character), \\(x) na_if(str_trim(x), ""))) |>\n'
            "  type_convert()\n"
        ),
    ),
    "python": Code(
        ["import re", "import unicodedata"],
        (
            "# Standard cleaning: snake_case names without accents (PÉRIODE -> periode,\n"
            "# referenceNumber -> reference_number, as janitor does in R), trimmed text,\n"
            "# empty strings as missing.\n\n"
            "data = data.rename(\n"
            "    {\n"
            "        column: re.sub(\n"
            '            r"[^0-9a-z]+",\n'
            '            "_",\n'
            "            re.sub(\n"
            '                r"([a-z0-9])([A-Z])",\n'
            '                r"\\1_\\2",\n'
            '                unicodedata.normalize("NFKD", column).encode("ascii", "ignore").decode(),\n'
            "            ).lower(),\n"
            '        ).strip("_")\n'
            "        for column in data.columns\n"
            "    }\n"
            ")\n"
            'data = data.with_columns(pl.col(pl.Utf8).str.strip_chars().replace("", None))\n'
        ),
    ),
    "stata": Code(
        [],
        (
            "* Standard cleaning: lower-case names, trimmed text, and numbers stored as\n"
            "* text converted (destring leaves genuinely non-numeric text alone).\n\n"
            "rename *, lower\n"
            "capture ds, has(type string)\n"
            "if _rc == 0 {\n"
            "    foreach var of varlist `r(varlist)' {\n"
            "        replace `var' = strtrim(`var')\n"
            "    }\n"
            "}\n"
            "destring, replace\n"
        ),
    ),
    "julia": Code(
        ["TidierData"],
        (
            "# Standard cleaning: snake_case names, trimmed text, empty strings as missing.\n\n"
            "data = @chain data begin\n    @clean_names\nend\n"
            "data = mapcols(\n"
            "    col -> eltype(col) <: Union{Missing, AbstractString} ?\n"
            "        [ismissing(x) || isempty(strip(x)) ? missing : strip(x) for x in col] : col,\n"
            "    data,\n"
            ")\n"
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
                '    (pl.col("VALUE") * 10 ** pl.col("SCALAR_ID").cast(pl.Int64)).alias(\n'
                '        "VALUE_NORMALIZED"\n'
                "    )\n"
                ")\n"
            ),
        ),
        "stata": Code(
            [],
            (
                "* value is in the unit named by scalar_factor; scalar_id is its power of ten.\n\n"
                "generate double value_normalized = value * 10^scalar_id\n"
            ),
        ),
        "julia": Code(
            [],
            (
                "# VALUE is in the unit named by SCALAR_FACTOR; SCALAR_ID is its power of ten.\n\n"
                "data.VALUE_NORMALIZED = data.VALUE .* 10.0 .^ data.SCALAR_ID\n"
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
                "generate double value_normalized = value * 10^scalarfactorcode\n"
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
            '    (pl.col("VALEUR") * 10 ** pl.col("IDENTIFICATEUR SCALAIRE").cast(pl.Int64)).alias(\n'
            '        "VALEUR_NORMALISEE"\n'
            "    )\n"
            ")\n"
        ),
    ),
    "julia": Code(
        [],
        (
            "# VALEUR est dans l'unité de FACTEUR SCALAIRE; IDENTIFICATEUR SCALAIRE en est\n"
            "# la puissance de dix.\n\n"
            'data.VALEUR_NORMALISEE = data.VALEUR .* 10.0 .^ data[!, "IDENTIFICATEUR SCALAIRE"]\n'
        ),
    ),
}


def specific(language: str, source: str) -> Code | None:
    return SPECIFIC.get(source, {}).get(language)
