"""Basic cleaning appended to every reproduction script, per language.

Each script loads the data into `data`, then runs the source's own
cleaning (source-specific, in the column names the loader leaves), then
the standard block: consistent snake_case names, trimmed text, empty
strings as missing, numbers stored as text converted. The steps follow
the house conventions: janitor/dplyr in R, polars in Python,
TidierData in Julia, no cd in Stata.
"""

from __future__ import annotations

Source = str  # "statcan_table", "statcan_vectors", "valet", or "" for generic

GENERIC: dict[str, str] = {
    "r": (
        "library(dplyr)\nlibrary(readr)\nlibrary(stringr)\n\n"
        "# Standard cleaning: trimmed text, empty strings as missing, and numbers\n"
        "# stored as text converted to numbers.\n\n"
        "data <- data |>\n"
        '  mutate(across(where(is.character), \\(x) na_if(str_trim(x), ""))) |>\n'
        "  type_convert()\n"
    ),
    "python": (
        "import re\nimport unicodedata\n\n"
        "# Standard cleaning: snake_case names without accents (PÉRIODE -> periode),\n"
        "# trimmed text, empty strings as missing.\n\n"
        "def snake_case(name: str) -> str:\n"
        '    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()\n'
        '    return re.sub(r"[^0-9a-z]+", "_", plain.lower()).strip("_")\n\n\n'
        "data = data.rename({c: snake_case(c) for c in data.columns})\n"
        "data = data.with_columns(\n"
        '    pl.col(pl.Utf8).str.strip_chars().replace("", None)\n'
        ")\n"
    ),
    "stata": (
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
    "julia": (
        "using TidierData\n\n"
        "# Standard cleaning: snake_case names, trimmed text, empty strings as missing.\n\n"
        "data = @chain data begin\n    @clean_names\nend\n"
        "data = mapcols(\n"
        "    col -> eltype(col) <: Union{Missing, AbstractString} ?\n"
        "        [ismissing(x) || isempty(strip(x)) ? missing : strip(x) for x in col] : col,\n"
        "    data,\n"
        ")\n"
    ),
}

# Runs before the standard block, so names are as the loader leaves them:
# R already snake_case (clean_names at load), Stata lower case (import
# delimited's default), Python and Julia as in the source file.
SPECIFIC: dict[Source, dict[str, str]] = {
    "statcan_table": {
        # cansim in R already returns val_norm (scaled value) and Date.
        "r": (
            "# cansim adds val_norm (VALUE times its scalar factor) and a Date column;\n"
            "# keep STATUS and SYMBOL, which flag estimates to use with caution.\n\n"
            "data <- data |>\n  filter(!is.na(val_norm))\n"
        ),
        "python": (
            "# VALUE is in the unit named by SCALAR_FACTOR; SCALAR_ID is its power of ten.\n\n"
            "data = data.with_columns(\n"
            '    (pl.col("VALUE") * 10 ** pl.col("SCALAR_ID").cast(pl.Int64)).alias("VALUE_NORMALIZED")\n'
            ")\n"
        ),
        "stata": (
            "* value is in the unit named by scalar_factor; scalar_id is its power of ten.\n\n"
            "generate double value_normalized = value * 10^scalar_id\n"
        ),
        "julia": (
            "# VALUE is in the unit named by SCALAR_FACTOR; SCALAR_ID is its power of ten.\n\n"
            "data.VALUE_NORMALIZED = data.VALUE .* 10.0 .^ data.SCALAR_ID\n"
        ),
    },
    "statcan_vectors": {
        "r": (
            "# cansim adds val_norm (the value times its scalar factor) and a Date column.\n\n"
            "data <- data |>\n  filter(!is.na(val_norm))\n"
        ),
        "python": (
            "# scalarFactorCode is the value's power of ten; refPer is the reference date.\n\n"
            "data = data.with_columns(\n"
            '    (pl.col("value") * 10 ** pl.col("scalarFactorCode")).alias("value_normalized"),\n'
            '    pl.col("refPer").str.to_date(strict=False).alias("ref_date"),\n'
            ")\n"
        ),
        "stata": (
            "* scalarfactorcode is the value's power of ten.\n\n"
            "generate double value_normalized = value * 10^scalarfactorcode\n"
            'generate ref_date = date(refper, "YMD")\n'
            "format ref_date %td\n"
        ),
        "julia": (
            "# scalarFactorCode is the value's power of ten.\n\n"
            "data.value_normalized = data.value .* 10.0 .^ data.scalarFactorCode\n"
        ),
    },
    "valet": {
        "r": (
            "library(dplyr)\nlibrary(lubridate)\nlibrary(stringr)\nlibrary(tidyr)\n\n"
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
        "python": (
            "# Valet nests each series as <series>.v; make one row per date and series.\n\n"
            'data = data.unpivot(index="d", variable_name="series", value_name="value")\n'
            "data = data.with_columns(\n"
            '    pl.col("d").str.to_date().alias("date"),\n'
            '    pl.col("series").str.replace(r"\\.v$", ""),\n'
            '    pl.col("value").cast(pl.Float64, strict=False),\n'
            ').select("date", "series", "value")\n'
        ),
        "stata": (
            "* One column per series (<series>_v), one row per date.\n\n"
            'generate date = date(d, "YMD")\n'
            "format date %td\n"
            "drop d\n"
        ),
    },
}


# French full tables (checked 2026-09-24 on 18100004-fra): same columns in
# French, e.g. VALEUR and IDENTIFICATEUR SCALAIRE. cansim returns val_norm
# in both languages. Stata turns these accented, spaced headers into
# generic names, so its French version skips the scaling step.
SPECIFIC["statcan_table_fr"] = {
    "r": SPECIFIC["statcan_table"]["r"],
    "python": (
        "# VALEUR est dans l'unité de FACTEUR SCALAIRE; IDENTIFICATEUR SCALAIRE en est\n"
        "# la puissance de dix.\n\n"
        "data = data.with_columns(\n"
        '    (pl.col("VALEUR") * 10 ** pl.col("IDENTIFICATEUR SCALAIRE").cast(pl.Int64)).alias(\n'
        '        "VALEUR_NORMALISEE"\n'
        "    )\n"
        ")\n"
    ),
    "julia": (
        "# VALEUR est dans l'unité de FACTEUR SCALAIRE; IDENTIFICATEUR SCALAIRE en est\n"
        "# la puissance de dix.\n\n"
        'data.VALEUR_NORMALISEE = data.VALEUR .* 10.0 .^ data[!, "IDENTIFICATEUR SCALAIRE"]\n'
    ),
}

PACKAGES: dict[str, list[str]] = {
    "r": ["dplyr", "readr", "stringr"],
    "python": ["polars"],
    "stata": [],
    "julia": ["TidierData"],
}


def cleaning(language: str, source: Source) -> str:
    specific = SPECIFIC.get(source, {}).get(language, "")
    return (specific + "\n" if specific else "") + GENERIC[language]
