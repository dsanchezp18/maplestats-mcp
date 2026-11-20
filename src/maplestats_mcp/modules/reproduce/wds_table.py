"""Rebuild a whole StatCan table from the Web Data Service, as StatCan's CSV lays it out.

StatCan's full-table zips (/n1/tbl/csv/) still answer scripts from most networks
(from cloud hosts and from the hosted MapleStats server, statcan_check_access,
checked 2026-11-20), but some networks get StatCan's captcha, a Cloudflare check
only a person in a browser can pass (StatCan announced the block on 2026-11-16).
WDS (/t1/wds/rest/) answers scripts everywhere. This module writes:

- `rebuild_script`: a Python script that asks WDS for the table's structure
  (getCubeMetadata), its code sets (getCodeSets) and then every series, in batches
  (getDataFromCubePidCoordAndLatestNPeriods), and writes the same columns, in the
  same order and format, as StatCan's CSV (wds_get_full_table_download returns it);
- `zip_first_python` and `zip_first_r`: the read step of reproduce_code's scripts
  for a full table (Python, R, and Stata through its built-in Python). They download
  StatCan's zip and, only when StatCan answers it with the captcha, rebuild the same
  rows through WDS with the same code.

The idea of rebuilding a table series by series through WDS comes from
vrraiv/sixfigures (PR #105, 2026-11-18). That repository has no licence file, so
nothing is copied from it; this is MapleStats' own implementation. Checked live
against StatCan's own CSV on 2026-11-18, byte for byte: 36-10-0104 whole (69,266
rows), 18-10-0004 from 2024-01 (68,125 rows) and 14-10-0287 from 2025-06 (152,847
rows). What it had to get right, each found by that comparison: WDS answers a batch
out of order (match on the echoed coordinate); WDS pads a series with ".." points
that have no release time, which the CSV leaves out; rows follow each member's place
in its dimension's list, not its id; a confidential cell ("x") is a WDS security
level but a CSV status. The French edition (LANG = "fr": French names and headers,
";" between fields, "." in numbers) and the R version were checked the same way on
2026-11-20 against 17-10-0009 whole and 18-10-0004 and 14-10-0287 slices, in both
languages.

The scripts name themselves in their User-Agent and use HTTP/2, which StatCan's
network needs. On StatCan's captcha the rebuild stops and says so; nothing tries to
get past it.
"""

from __future__ import annotations

import math
from typing import Any

_USER_AGENT = "MapleStats MCP reproduction script (https://github.com/dsanchezp18/maplestats-mcp)"

# The rebuild's functions, shared by the standalone script and reproduce_code's
# Python scripts. They read the settings PRODUCT_ID, MEMBERS, START_PERIOD,
# END_PERIOD, LANG and MAX_CALLS as globals. Names start with wds_ (or WDS_) so they
# cannot clash with a reproduce script's own (data, client, response, raw_path).
_PY_FUNCTIONS = r'''WDS = "https://www150.statcan.gc.ca/t1/wds/rest/"
WDS_USER_AGENT = "__USER_AGENT__"
WDS_POINTS_PER_CALL = 50_000  # data points asked for in one WDS call
WDS_MAX_COORDINATES = 300  # WDS refuses longer lists (HTTP 416)
# WDS frequencyCode -> periods per year (getCodeSets "frequency").
WDS_PER_YEAR = {4: 26, 6: 12, 7: 6, 9: 4, 10: 3, 11: 2, 12: 1, 13: 0.5, 14: 1 / 3, 15: 0.25, 16: 0.2}
# StatCan's CSV in each edition: the period, geography and DGUID columns, the
# columns after the dimensions, and the field separator.
WDS_CSV = {
    "en": ("REF_DATE", "GEO", "DGUID", ["UOM", "UOM_ID", "SCALAR_FACTOR", "SCALAR_ID", "VECTOR", "COORDINATE", "VALUE", "STATUS", "SYMBOL", "TERMINATED", "DECIMALS"], ","),
    "fr": ("PÉRIODE DE RÉFÉRENCE", "GÉO", "DGUID", ["UNITÉ DE MESURE", "IDENTIFICATEUR D'UNITÉ DE MESURE", "FACTEUR SCALAIRE", "IDENTIFICATEUR SCALAIRE", "VECTEUR", "COORDONNÉES", "VALEUR", "STATUS", "SYMBOLE", "TERMINÉ", "DÉCIMALES"], ";"),
}


def wds_post(client, method, body):
    """POST to WDS, waiting and retrying on a rate limit or a server error."""
    for attempt in range(5):
        response = client.post(WDS + method, json=body)
        if response.headers.get("cf-mitigated", "").lower() == "challenge":
            sys.exit(
                "Statistics Canada answered WDS with its captcha (a Cloudflare check that "
                "scripts cannot pass), so the table cannot be rebuilt now. Try again later."
            )
        if response.status_code == 409:
            sys.exit("WDS is locked during StatCan's daily update (midnight to 8:30 ET).")
        if response.status_code in (429, 500, 502, 503, 504):
            time.sleep(float(response.headers.get("Retry-After", 2 ** attempt)))
            continue
        response.raise_for_status()
        return response.json()
    sys.exit(f"WDS kept failing on {method}; try again later.")


def wds_periods(metadata):
    """How many periods back from the table's last one cover START_PERIOD (all, without it)."""
    since = START_PERIOD or metadata["cubeStartDate"]
    first = date.fromisoformat((since[:7] if len(since) >= 7 else since[:4] + "-01") + "-01")
    last = date.fromisoformat(metadata["cubeEndDate"][:10])
    code = int(metadata["frequencyCode"])
    if code in (1, 21):  # daily, occasional daily
        return (last - first).days + 2
    if code == 2:  # weekly
        return (last - first).days // 7 + 2
    months = (last.year - first.year) * 12 + last.month - first.month + 1
    return math.ceil(months * WDS_PER_YEAR.get(code, 12) / 12) + 1


def wds_ref_date(point, code):
    """REF_DATE as StatCan's CSV writes it: a year (annual and longer, occasional), a
    full date (daily, weekly, occasional daily) or a year and month (the rest), and
    "start/end" for a period with two ends (a fiscal year, 1994/1998)."""
    size = 4 if 12 <= code <= 18 else 10 if code in (1, 2, 4, 21) else 7
    if point.get("refPer2"):
        return point["refPer"][:size] + "/" + point["refPer2"][:size]
    return point["refPer"][:size]


def wds_dguid(member):
    """The DGUID of a geography member: vintage, A (administrative) or S (statistical),
    the four-digit geographic level, then the member's code."""
    if not member.get("vintage") or member.get("geoLevel") is None:
        return ""
    level = int(member["geoLevel"])
    kind = "S" if level >= 500 else "A"
    return f"{member['vintage']}{kind}{level:04d}{member.get('classificationCode') or ''}"


def wds_keep(dimension):
    """The members of a dimension that MEMBERS keeps (all when it names none). A
    dimension or member may be named in English or French, or a member by its id."""
    names = {str(dimension.get(k) or "").strip().lower() for k in ("dimensionNameEn", "dimensionNameFr")}
    wanted = next((v for k, v in MEMBERS.items() if k.strip().lower() in names), None)
    members = dimension["member"]
    if not wanted:
        return members
    asked = {str(w).strip().lower() for w in wanted}
    kept = [
        m for m in members
        if {str(m.get(k) or "").strip().lower() for k in ("memberNameEn", "memberNameFr")} & asked
        or str(m["memberId"]) in asked
    ]
    if not kept:
        sys.exit(f"No member of {dimension['dimensionNameEn']!r} matches {wanted}.")
    return kept


def wds_rebuild(output):
    """Ask WDS for the series MEMBERS keeps and write StatCan's CSV to `output`."""
    with httpx.Client(http2=True, timeout=300, headers={"User-Agent": WDS_USER_AGENT}) as client:
        metadata = wds_post(client, "getCubeMetadata", [{"productId": PRODUCT_ID}])[0]["object"]
        codes = client.get(WDS + "getCodeSets").json()["object"]
        dimensions = sorted(metadata["dimension"], key=lambda d: d["dimensionPositionId"])
        kept = [wds_keep(d) for d in dimensions]
        combinations = math.prod(len(k) for k in kept)
        latest_n = wds_periods(metadata)
        per_call = max(1, min(WDS_MAX_COORDINATES, WDS_POINTS_PER_CALL // max(latest_n, 1)))
        calls = math.ceil(combinations / per_call)
        print(
            f"Table {PRODUCT_ID}: {combinations:,} member combinations to ask for "
            f"({metadata['nbSeriesCube']:,} series in the whole table), up to {latest_n:,} "
            f"periods each, in {calls:,} WDS calls."
        )
        if calls > MAX_CALLS:
            sys.exit(
                f"That is more than MAX_CALLS ({MAX_CALLS:,}). Keep fewer members in MEMBERS, "
                "a later START_PERIOD, or raise MAX_CALLS if you mean it."
            )
        answers = []
        combos = itertools.product(*kept)
        while batch := list(itertools.islice(combos, per_call)):
            # WDS answers a batch out of order, so each answer is matched by the
            # coordinate it echoes (ten positions, zero-padded), not by position.
            asked = {
                ".".join([str(m["memberId"]) for m in combo] + ["0"] * (10 - len(combo))): combo
                for combo in batch
            }
            body = [
                {"productId": PRODUCT_ID, "coordinate": c, "latestN": latest_n} for c in asked
            ]
            for answer in wds_post(client, "getDataFromCubePidCoordAndLatestNPeriods", body):
                # FAILED: StatCan publishes no series for this combination of members.
                if answer.get("status") == "SUCCESS":
                    series = answer["object"]
                    answers.append((asked[series["coordinate"]], series))
            time.sleep(0.1)
    wds_write(output, metadata, codes, dimensions, answers)


def wds_write(output, metadata, codes, dimensions, answers):
    lang = "Fr" if LANG == "fr" else "En"
    uom = {str(c["memberUomCode"]): c["memberUom" + lang] for c in codes["uom"]}
    scalar = {str(c["scalarFactorCode"]): c["scalarFactorDesc" + lang] for c in codes["scalar"]}
    status = {str(c["statusCode"]): c["statusRepresentation" + lang] or "" for c in codes["status"]}
    symbol = {str(c["symbolCode"]): c["symbolRepresentation" + lang] or "" for c in codes["symbol"]}
    secret = {
        str(c["securityLevelCode"]): c["securityLevelRepresentation" + lang] or ""
        for c in codes["securityLevel"]
    }
    period_name, geo_name, dguid_name, after, separator = WDS_CSV["fr" if LANG == "fr" else "en"]
    code = int(metadata["frequencyCode"])
    geography = [d["dimensionNameEn"] == "Geography" for d in dimensions]
    header = [period_name]
    for dimension, is_geo in zip(dimensions, geography):
        header += [geo_name, dguid_name] if is_geo else [dimension["dimensionName" + lang]]
    header += after
    place = [{m["memberId"]: i for i, m in enumerate(d["member"])} for d in dimensions]
    rows = []
    for combo, series in answers:
        unit = next(
            (m["memberUomCode"] for m, d in zip(combo, dimensions) if d["hasUom"] and m["memberUomCode"]),
            None,
        )
        members = []
        for member, is_geo in zip(combo, geography):
            name = member["memberName" + lang]
            members += [name, wds_dguid(member)] if is_geo else [name]
        coordinate = ".".join(series["coordinate"].split(".")[: len(dimensions)])
        terminated = "t" if any(m["terminated"] for m in combo) else ""
        # Rows follow each member's place in its dimension's list, as in StatCan's CSV.
        order = tuple(place[i][m["memberId"]] for i, m in enumerate(combo))
        for point in series["vectorDataPoint"]:
            # WDS pads a series with ".." points up to the table's last period; they
            # have no release time, and StatCan's CSV leaves them out (36-10-0104).
            if not point.get("releaseTime"):
                continue
            period = wds_ref_date(point, code)
            if (START_PERIOD and period < START_PERIOD[: len(period)]) or (
                END_PERIOD and period > END_PERIOD[: len(period)]
            ):
                continue
            value = point["value"]
            rows.append((period, order, [
                period, *members,
                uom.get(str(unit), "") if unit is not None else "", "" if unit is None else str(unit),
                scalar.get(str(point["scalarFactorCode"]), ""), str(point["scalarFactorCode"]),
                f"v{series['vectorId']}", coordinate,
                "" if value is None else f"{value:.{point['decimals']}f}",
                # A confidential cell ("x") is a security level in WDS, a status in the CSV.
                status.get(str(point["statusCode"]), "")
                or secret.get(str(point.get("securityLevelCode", 0)), ""),
                symbol.get(str(point["symbolCode"]), ""),
                terminated, str(point["decimals"]),
            ]))
    rows.sort(key=lambda r: (r[0], r[1]))
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, delimiter=separator, quoting=csv.QUOTE_ALL, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(r[2] for r in rows)
    print(f"{len(rows):,} rows from {len(answers):,} series written to {output}")
'''.replace("__USER_AGENT__", _USER_AGENT)

PY_IMPORTS = [
    "import csv",
    "import itertools",
    "import math",
    "import sys",
    "import time",
    "from datetime import date",
    "from pathlib import Path",
    "import httpx",
]

_SCRIPT = '''"""Rebuild Statistics Canada table __TABLE__ from the Web Data Service (WDS).

StatCan serves its full-table files to most scripts, but answers some networks with
a captcha (since November 2026), while WDS answers scripts everywhere. This script
asks WDS for the table's structure and every series, and writes the CSV StatCan
publishes, with the same columns, order and format, to OUTPUT. Written by MapleStats
MCP (wds_get_full_table_download).

Run: pip install "httpx[http2]", then python this_file.py
"""

__IMPORTS__

__SETTINGS__

__FUNCTIONS__

if __name__ == "__main__":
    wds_rebuild(OUTPUT)
'''


# WDS calls a rebuild may take before the tool says the table is too big. Each call
# asks for up to 300 series; at about one call a second this is half an hour.
MAX_CALLS = 2000
_POINTS_PER_CALL = 50_000
_MAX_COORDINATES_PER_CALL = 300
_PER_YEAR = {4: 26, 6: 12, 7: 6, 9: 4, 10: 3, 11: 2, 12: 1, 13: 0.5, 14: 1 / 3, 15: 0.25, 16: 0.2}


def periods_to_ask(metadata: dict[str, Any], start_period: str | None) -> int:
    """The script's latestN: periods back from the table's last one to `start_period`."""
    from datetime import date

    # REF_DATE's forms: 2020, 2020-01 or 2020-01-15. A bare year read as "2020-01"
    # (its first seven characters plus "-01" gave "2020-01", not a date) and raised
    # ValueError from wds_get_full_table_download until 2026-11-20.
    since = start_period or str(metadata["cubeStartDate"])
    first = date.fromisoformat((since[:7] if len(since) >= 7 else f"{since[:4]}-01") + "-01")
    last = date.fromisoformat(str(metadata["cubeEndDate"])[:10])
    code = int(metadata.get("frequencyCode") or 0)
    # Daily and occasional daily (17-10-0009's quarterly points): one per day at most.
    if code in (1, 21):
        return (last - first).days + 2
    if code == 2:
        return (last - first).days // 7 + 2
    months = (last.year - first.year) * 12 + last.month - first.month + 1
    return math.ceil(months * _PER_YEAR.get(code, 12) / 12) + 1


def wds_calls(combinations: int, latest_n: int) -> int:
    """How many WDS calls the script makes for `combinations` series of `latest_n` periods."""
    per_call = max(1, min(_MAX_COORDINATES_PER_CALL, _POINTS_PER_CALL // max(latest_n, 1)))
    return math.ceil(combinations / per_call)


def _table(product_id: int) -> tuple[str, str]:
    pid = f"{product_id:08d}"
    return pid, f"{pid[:2]}-{pid[2:4]}-{pid[4:8]}-01"


def py_settings(
    product_id: int,
    members: dict[str, list[str]] | None,
    start_period: str | None,
    end_period: str | None,
    lang: str = "en",
    max_calls: int = MAX_CALLS,
) -> str:
    """The rebuild's settings block, as Python."""
    return (
        "# --- Settings (written by MapleStats; edit to change what is kept) ---\n"
        f"PRODUCT_ID = {product_id}\n"
        "# Dimension name -> member names (or ids) to keep, in English or French; a\n"
        "# dimension left out keeps them all.\n"
        f"MEMBERS = {_literal(members or {})}\n"
        "# First and last REF_DATE to keep, as StatCan writes it (2020, 2020-01); None keeps all.\n"
        f"START_PERIOD = {start_period!r}\n"
        f"END_PERIOD = {end_period!r}\n"
        '# "en" writes the English edition of the CSV, "fr" the French one.\n'
        f"LANG = {('fr' if lang == 'fr' else 'en')!r}\n"
        "# Stop before more WDS calls than this (each asks for up to 300 series).\n"
        f"MAX_CALLS = {max_calls}\n"
        "# --- End of settings ---"
    )


def rebuild_script(
    product_id: int,
    members: dict[str, list[str]] | None = None,
    start_period: str | None = None,
    end_period: str | None = None,
    max_calls: int = MAX_CALLS,
    lang: str = "en",
) -> str:
    """The Python script that rebuilds table `product_id` (8 digits) from WDS."""
    pid, table = _table(product_id)
    suffix = "fra" if lang == "fr" else "eng"
    settings = py_settings(product_id, members, start_period, end_period, lang, max_calls)
    settings = settings.replace(
        "# Stop before",
        f'OUTPUT = Path("data/raw/{pid}-{suffix}-wds.csv")\n# Stop before',
    )
    return (
        _SCRIPT.replace("__TABLE__", table)
        .replace("__IMPORTS__", _py_imports())
        .replace("__SETTINGS__", settings)
        .replace("__FUNCTIONS__", _PY_FUNCTIONS.rstrip("\n"))
    )


def _py_imports() -> str:
    standard = [line for line in PY_IMPORTS if line != "import httpx"]
    return "\n".join(standard) + "\n\nimport httpx"


_FALLBACK_NOTE = (
    "# StatCan serves its full-table file to most scripts, but answers some networks\n"
    "# with a captcha (a Cloudflare check only a person in a browser can pass; since\n"
    "# November 2026). Then the script rebuilds the same rows, with the same columns,\n"
    "# through StatCan's Web Data Service (WDS), which still answers scripts: slower,\n"
    "# one call per 300 series. It never tries to get past the captcha.\n"
)


def zip_first_python(
    product_id: int,
    lang: str,
    members: dict[str, list[str]] | None,
    start_period: str | None,
    end_period: str | None,
) -> tuple[list[str], str]:
    """reproduce_code's Python read step for a full table: the zip, else WDS at the captcha.

    Returns the imports and the code; it leaves the table's CSV read as `data`.
    Expects RAW_DIR and raw_path from the script's setup, as every reproduce script has.
    """
    pid, _ = _table(product_id)
    suffix = "fra" if lang == "fr" else "eng"
    url = f"https://www150.statcan.gc.ca/n1/tbl/csv/{pid}-{suffix}.zip"
    separator = ";" if lang == "fr" else ","
    body = (
        f"{_FALLBACK_NOTE}\n"
        f"{py_settings(product_id, members, start_period, end_period, lang)}\n\n"
        f"{_PY_FUNCTIONS}\n\n"
        "def fetch_table():\n"
        '    """The table\'s CSV: from StatCan\'s file, or rebuilt through WDS at the captcha."""\n'
        "    with httpx.Client(\n"
        "        http2=True,\n"
        "        follow_redirects=True,\n"
        "        timeout=300,\n"
        '        headers={"User-Agent": WDS_USER_AGENT},\n'
        "    ) as client:\n"
        f"        response = client.get({url!r})\n"
        '    if response.headers.get("cf-mitigated", "").lower() == "challenge":\n'
        "        print(\n"
        '            "Statistics Canada answered the file with its captcha; rebuilding the "\n'
        '            "same rows through WDS instead."\n'
        "        )\n"
        f'        output = RAW_DIR / "{pid}-{suffix}-wds.csv"\n'
        "        wds_rebuild(output)\n"
        "        return output\n"
        "    response.raise_for_status()\n"
        "    raw_path.write_bytes(response.content)\n"
        "    # The ZIP also holds a metadata file; read the data file.\n"
        "    with zipfile.ZipFile(raw_path) as archive:\n"
        "        name = next(\n"
        '            n for n in archive.namelist() if n.lower().endswith(".csv") and "metadata" not in n.lower()\n'
        "        )\n"
        "        archive.extract(name, RAW_DIR)\n"
        "    return RAW_DIR / name\n\n\n"
        "csv_path = fetch_table()\n"
        f"data = pl.read_csv(csv_path, separator={separator!r}, infer_schema=False)\n"
    )
    return [*PY_IMPORTS, "import zipfile", "import polars as pl"], body


# The R version of the same rebuild, for reproduce_code's R script. It follows the
# Python functions above line for line (same calls, matching, filters, order and
# formatting), so the two write the same file.
_R_FUNCTIONS = r"""wds <- "https://www150.statcan.gc.ca/t1/wds/rest/"
wds_user_agent <- "__USER_AGENT__"
wds_points_per_call <- 50000 # data points asked for in one WDS call
wds_max_coordinates <- 300 # WDS refuses longer lists (HTTP 416)
# WDS frequencyCode -> periods per year (getCodeSets "frequency").
wds_per_year <- c(
  "4" = 26, "6" = 12, "7" = 6, "9" = 4, "10" = 3, "11" = 2, "12" = 1, "13" = 0.5, "14" = 1 / 3,
  "15" = 0.25, "16" = 0.2
)
wds_captcha <- function(response) {
  isTRUE(tolower(resp_header(response, "cf-mitigated")) == "challenge")
}

# POST to WDS, waiting and retrying on a rate limit or a server error.
wds_post <- function(method, body) {
  for (attempt in 0:4) {
    response <- request(paste0(wds, method)) |>
      req_user_agent(wds_user_agent) |>
      req_timeout(300) |>
      req_body_json(body, auto_unbox = TRUE) |>
      req_error(is_error = \(response) FALSE) |>
      req_perform()
    if (wds_captcha(response)) {
      stop(
        "Statistics Canada answered WDS with its captcha (a Cloudflare check that ",
        "scripts cannot pass), so the table cannot be rebuilt now. Try again later.",
        call. = FALSE
      )
    }
    status <- resp_status(response)
    if (status == 409) {
      stop("WDS is locked during StatCan's daily update (midnight to 8:30 ET).", call. = FALSE)
    }
    if (status %in% c(429, 500, 502, 503, 504)) {
      wait <- resp_header(response, "Retry-After")
      Sys.sleep(if (is.null(wait)) 2^attempt else as.numeric(wait))
      next
    }
    if (status >= 400) stop("WDS answered HTTP ", status, " to ", method, ".", call. = FALSE)
    return(resp_body_json(response, simplifyVector = FALSE))
  }
  stop("WDS kept failing on ", method, "; try again later.", call. = FALSE)
}

# How many periods back from the table's last one cover start_period (all, without it).
wds_periods <- function(metadata) {
  since <- if (is.null(start_period)) metadata$cubeStartDate else start_period
  month <- if (nchar(since) >= 7) substr(since, 1, 7) else paste0(substr(since, 1, 4), "-01")
  first <- as.Date(paste0(month, "-01"))
  last <- as.Date(substr(metadata$cubeEndDate, 1, 10))
  code <- as.integer(metadata$frequencyCode)
  if (code %in% c(1, 21)) return(as.integer(last - first) + 2) # daily, occasional daily
  if (code == 2) return(as.integer(last - first) %/% 7 + 2) # weekly
  months <- (as.integer(format(last, "%Y")) - as.integer(format(first, "%Y"))) * 12 +
    as.integer(format(last, "%m")) - as.integer(format(first, "%m")) + 1
  per_year <- if (is.na(wds_per_year[as.character(code)])) 12 else wds_per_year[[as.character(code)]]
  ceiling(months * per_year / 12) + 1
}

# REF_DATE as StatCan's CSV writes it: a year (annual and longer, occasional), a
# full date (daily, weekly, occasional daily) or a year and month (the rest), and
# "start/end" for a period with two ends (a fiscal year, 1994/1998).
wds_ref_date <- function(ref_per, ref_per2, code) {
  size <- if (code %in% 12:18) 4 else if (code %in% c(1, 2, 4, 21)) 10 else 7
  ifelse(is.na(ref_per2) | ref_per2 == "", substr(ref_per, 1, size),
    paste0(substr(ref_per, 1, size), "/", substr(ref_per2, 1, size)))
}

# The DGUID of a geography member: vintage, A (administrative) or S (statistical),
# the four-digit geographic level, then the member's code.
wds_dguid <- function(member) {
  if (is.null(member$vintage) || identical(member$vintage, "") || is.null(member$geoLevel)) {
    return("")
  }
  level <- as.integer(member$geoLevel)
  kind <- if (level >= 500) "S" else "A"
  code <- if (is.null(member$classificationCode)) "" else member$classificationCode
  sprintf("%s%s%04d%s", member$vintage, kind, level, code)
}

# The members of a dimension that members keeps (all when it names none). A
# dimension or member may be named in English or French, or a member by its id.
# stringr's str_to_lower, not base tolower: in a C locale tolower() drops the
# UTF-8 mark of accented names, which then match nothing (checked 2026-11-20).
wds_fold <- function(text) str_to_lower(str_trim(enc2utf8(as.character(text))))
wds_keep <- function(dimension) {
  names_here <- wds_fold(c(dimension$dimensionNameEn, dimension$dimensionNameFr))
  wanted <- NULL
  for (entry in members) {
    if (wds_fold(entry$dimension) %in% names_here) {
      wanted <- entry$keep
      break
    }
  }
  if (length(wanted) == 0) return(dimension$member)
  asked <- wds_fold(wanted)
  kept <- Filter(\(m) any(c(
    wds_fold(m$memberNameEn), wds_fold(m$memberNameFr), as.character(m$memberId)
  ) %in% asked), dimension$member)
  if (length(kept) == 0) {
    stop("No member of '", dimension$dimensionNameEn, "' matches ",
      paste(wanted, collapse = ", "), ".", call. = FALSE)
  }
  kept
}

# Ask WDS for the series members keeps and write StatCan's CSV to output.
wds_rebuild <- function(output) {
  metadata <- wds_post("getCubeMetadata", list(list(productId = product_id)))[[1]]$object
  codes <- request(paste0(wds, "getCodeSets")) |>
    req_user_agent(wds_user_agent) |>
    req_perform() |>
    resp_body_json(simplifyVector = FALSE)
  codes <- codes$object
  positions <- vapply(metadata$dimension, \(d) as.integer(d$dimensionPositionId), integer(1))
  dimensions <- metadata$dimension[order(positions)]
  kept <- lapply(dimensions, wds_keep)
  combinations <- prod(lengths(kept))
  latest_n <- wds_periods(metadata)
  per_call <- max(1, min(wds_max_coordinates, wds_points_per_call %/% max(latest_n, 1)))
  calls <- ceiling(combinations / per_call)
  message(sprintf(
    "Table %s: %s member combinations to ask for (%s series in the whole table), up to %s periods each, in %s WDS calls.",
    product_id, format(combinations, big.mark = ","), format(metadata$nbSeriesCube, big.mark = ","),
    format(latest_n, big.mark = ","), format(calls, big.mark = ",")
  ))
  if (calls > max_calls) {
    stop("That is more than max_calls (", max_calls, "). Keep fewer members in members, ",
      "a later start_period, or raise max_calls if you mean it.", call. = FALSE)
  }
  # Every combination of the kept members, the last dimension varying fastest.
  grid <- as.matrix(rev(expand.grid(lapply(rev(kept), seq_along), KEEP.OUT.ATTRS = FALSE)))
  answers <- list()
  for (start in seq(1, combinations, by = per_call)) {
    rows <- start:min(start + per_call - 1, combinations)
    combos <- lapply(rows, \(row) Map(\(k, i) k[[i]], kept, grid[row, ]))
    # WDS answers a batch out of order, so each answer is matched by the
    # coordinate it echoes (ten positions, zero-padded), not by position.
    coordinates <- vapply(combos, \(combo) paste(c(
      vapply(combo, \(m) as.character(m$memberId), character(1)),
      rep("0", 10 - length(combo))
    ), collapse = "."), character(1))
    names(combos) <- coordinates
    body <- lapply(coordinates, \(c) list(productId = product_id, coordinate = c, latestN = latest_n))
    for (answer in wds_post("getDataFromCubePidCoordAndLatestNPeriods", body)) {
      # FAILED: StatCan publishes no series for this combination of members.
      if (identical(answer$status, "SUCCESS")) {
        series <- answer$object
        answers[[length(answers) + 1]] <- list(combo = combos[[series$coordinate]], series = series)
      }
    }
    Sys.sleep(0.1)
  }
  wds_write(output, metadata, codes, dimensions, answers)
}

wds_write <- function(output, metadata, codes, dimensions, answers) {
  lang <- if (identical(table_language, "fr")) "Fr" else "En"
  lookup <- function(items, key, field) {
    values <- vapply(items, \(c) if (is.null(c[[field]])) "" else as.character(c[[field]]), character(1))
    setNames(values, vapply(items, \(c) as.character(c[[key]]), character(1)))
  }
  uom <- lookup(codes$uom, "memberUomCode", paste0("memberUom", lang))
  scalar <- lookup(codes$scalar, "scalarFactorCode", paste0("scalarFactorDesc", lang))
  status <- lookup(codes$status, "statusCode", paste0("statusRepresentation", lang))
  symbol <- lookup(codes$symbol, "symbolCode", paste0("symbolRepresentation", lang))
  secret <- lookup(codes$securityLevel, "securityLevelCode", paste0("securityLevelRepresentation", lang))
  pick <- function(map, code) {
    value <- unname(map[as.character(code)])
    ifelse(is.na(value), "", value)
  }
  if (lang == "Fr") {
    period_name <- "P\u00c9RIODE DE R\u00c9F\u00c9RENCE"
    geo_name <- "G\u00c9O"
    after <- c("UNIT\u00c9 DE MESURE", "IDENTIFICATEUR D'UNIT\u00c9 DE MESURE", "FACTEUR SCALAIRE",
      "IDENTIFICATEUR SCALAIRE", "VECTEUR", "COORDONN\u00c9ES", "VALEUR", "STATUS", "SYMBOLE",
      "TERMIN\u00c9", "D\u00c9CIMALES")
    separator <- ";"
  } else {
    period_name <- "REF_DATE"
    geo_name <- "GEO"
    after <- c("UOM", "UOM_ID", "SCALAR_FACTOR", "SCALAR_ID", "VECTOR", "COORDINATE", "VALUE",
      "STATUS", "SYMBOL", "TERMINATED", "DECIMALS")
    separator <- ","
  }
  code <- as.integer(metadata$frequencyCode)
  geography <- vapply(dimensions, \(d) identical(d$dimensionNameEn, "Geography"), logical(1))
  header <- period_name
  for (i in seq_along(dimensions)) {
    header <- c(header, if (geography[i]) c(geo_name, "DGUID") else dimensions[[i]][[paste0("dimensionName", lang)]])
  }
  header <- c(header, after)
  place <- lapply(dimensions, \(d) setNames(seq_along(d$member) - 1, vapply(d$member, \(m) as.character(m$memberId), character(1))))
  pieces <- list()
  for (answer in answers) {
    combo <- answer$combo
    series <- answer$series
    unit <- NULL
    for (i in seq_along(combo)) {
      uom_code <- combo[[i]]$memberUomCode
      if (isTRUE(dimensions[[i]]$hasUom) && length(uom_code) == 1 && !isTRUE(uom_code == 0) && !identical(uom_code, "")) {
        unit <- uom_code
        break
      }
    }
    labels <- character()
    for (i in seq_along(combo)) {
      name <- combo[[i]][[paste0("memberName", lang)]]
      labels <- c(labels, if (geography[i]) c(name, wds_dguid(combo[[i]])) else name)
    }
    coordinate <- paste(head(strsplit(series$coordinate, ".", fixed = TRUE)[[1]], length(dimensions)), collapse = ".")
    terminated <- if (any(vapply(combo, \(m) isTRUE(as.logical(m$terminated)), logical(1)))) "t" else ""
    # Rows follow each member's place in its dimension's list, as in StatCan's CSV.
    order_key <- vapply(seq_along(combo), \(i) place[[i]][[as.character(combo[[i]]$memberId)]], numeric(1))
    # WDS pads a series with ".." points up to the table's last period; they
    # have no release time, and StatCan's CSV leaves them out (36-10-0104).
    points <- Filter(\(p) !is.null(p$releaseTime) && !identical(p$releaseTime, ""), series$vectorDataPoint)
    if (length(points) == 0) next
    field <- function(name) vapply(points, \(p) if (is.null(p[[name]])) NA_character_ else as.character(p[[name]]), character(1))
    period <- wds_ref_date(field("refPer"), field("refPer2"), code)
    keep_rows <- rep(TRUE, length(period))
    if (!is.null(start_period)) keep_rows <- keep_rows & !(period < substring(start_period, 1, nchar(period)))
    if (!is.null(end_period)) keep_rows <- keep_rows & !(period > substring(end_period, 1, nchar(period)))
    if (!any(keep_rows)) next
    points <- points[keep_rows]
    period <- period[keep_rows]
    decimals <- vapply(points, \(p) as.integer(p$decimals), integer(1))
    value <- vapply(points, \(p) if (is.null(p$value)) NA_real_ else as.numeric(p$value), numeric(1))
    scalar_code <- vapply(points, \(p) as.character(p$scalarFactorCode), character(1))
    # A confidential cell ("x") is a security level in WDS, a status in the CSV.
    status_text <- pick(status, vapply(points, \(p) as.character(p$statusCode), character(1)))
    secret_text <- pick(secret, vapply(points, \(p) if (is.null(p$securityLevelCode)) "0" else as.character(p$securityLevelCode), character(1)))
    n <- length(points)
    cells <- cbind(
      period,
      matrix(rep(labels, each = n), nrow = n),
      if (is.null(unit)) "" else pick(uom, unit),
      if (is.null(unit)) "" else as.character(unit),
      pick(scalar, scalar_code),
      scalar_code,
      paste0("v", series$vectorId),
      coordinate,
      ifelse(is.na(value), "", sprintf("%.*f", decimals, value)),
      ifelse(status_text == "", secret_text, status_text),
      pick(symbol, vapply(points, \(p) as.character(p$symbolCode), character(1))),
      terminated,
      as.character(decimals)
    )
    keys <- matrix(rep(order_key, each = n), nrow = n)
    pieces[[length(pieces) + 1]] <- list(cells = cells, keys = keys, period = period)
  }
  cells <- matrix(character(), ncol = length(header))
  if (length(pieces) > 0) {
    cells <- do.call(rbind, lapply(pieces, \(p) p$cells))
    keys <- do.call(rbind, lapply(pieces, \(p) p$keys))
    period <- unlist(lapply(pieces, \(p) p$period))
    ordering <- do.call(order, c(list(period), lapply(seq_len(ncol(keys)), \(j) keys[, j]), list(method = "radix")))
    cells <- cells[ordering, , drop = FALSE]
  }
  quote_cells <- function(x) paste0('"', gsub('"', '""', x, fixed = TRUE), '"')
  lines <- c(
    paste(quote_cells(header), collapse = separator),
    apply(cells, 1, \(row) paste(quote_cells(row), collapse = separator))
  )
  dir.create(dirname(output), recursive = TRUE, showWarnings = FALSE)
  connection <- file(output, open = "wb")
  writeBin(as.raw(c(0xef, 0xbb, 0xbf)), connection)
  writeBin(charToRaw(enc2utf8(paste0(paste(lines, collapse = "\n"), "\n"))), connection)
  close(connection)
  message(sprintf("%s rows from %s series written to %s", format(nrow(cells), big.mark = ","),
    format(length(answers), big.mark = ","), output))
}
""".replace("__USER_AGENT__", _USER_AGENT)


def _r_string(value: str) -> str:
    """An R string literal, ASCII only: non-ASCII characters as \\u escapes, which
    R marks as UTF-8 whatever the session's locale (a literal "É" in a script read
    in a C locale came out as "<c3><89>", checked 2026-11-20)."""
    out = []
    for ch in value.replace("\x00", ""):
        if ch in '"\\':
            out.append("\\" + ch)
        elif 32 <= ord(ch) < 127:
            out.append(ch)
        elif ord(ch) <= 0xFFFF:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(f"\\U{{{ord(ch):08x}}}")
    return '"' + "".join(out) + '"'


def _r_settings(
    product_id: int,
    members: dict[str, list[str]] | None,
    start_period: str | None,
    end_period: str | None,
    lang: str,
) -> str:
    # A list of entries, not a named list: R turns list names into the session's
    # encoding, and in a C locale "Géographie" became "G<U+00E9>ographie".
    entries = ",\n".join(
        f"  list(dimension = {_r_string(str(k))}, keep = c({', '.join(_r_string(str(v)) for v in vs)}))"
        for k, vs in (members or {}).items()
    )
    members_r = f"list(\n{entries}\n)" if entries else "list()"

    def text_or_null(value: str | None) -> str:
        return "NULL" if value is None else _r_string(value)

    return (
        "# --- Settings (written by MapleStats; edit to change what is kept) ---\n"
        f"product_id <- {product_id}\n"
        "# Each entry: a dimension, and the member names (or ids) to keep, in English or\n"
        "# French; a dimension left out keeps them all.\n"
        f"members <- {members_r}\n"
        "# First and last REF_DATE to keep, as StatCan writes it (2020, 2020-01); NULL keeps all.\n"
        f"start_period <- {text_or_null(start_period)}\n"
        f"end_period <- {text_or_null(end_period)}\n"
        f'table_language <- "{"fr" if lang == "fr" else "en"}"\n'
        "# Stop before more WDS calls than this (each asks for up to 300 series).\n"
        f"max_calls <- {MAX_CALLS}\n"
        "# --- End of settings ---\n"
    )


def zip_first_r(
    product_id: int,
    lang: str,
    members: dict[str, list[str]] | None,
    start_period: str | None,
    end_period: str | None,
) -> tuple[list[str], str]:
    """reproduce_code's R read step for a full table: the zip, else WDS at the captcha.

    Returns the packages and the code; it leaves the table's CSV read as `data`.
    """
    pid, _ = _table(product_id)
    suffix = "fra" if lang == "fr" else "eng"
    url = f"https://www150.statcan.gc.ca/n1/tbl/csv/{pid}-{suffix}.zip"
    path = f"data/raw/{pid}-{suffix}.zip"
    folder = f"data/raw/{pid}-{suffix}"
    separator = ";" if lang == "fr" else ","
    body = (
        f"{_FALLBACK_NOTE}\n"
        f"{_r_settings(product_id, members, start_period, end_period, lang)}\n"
        f"{_R_FUNCTIONS}\n"
        f"response <- request({_r_string(url)}) |>\n"
        "  req_user_agent(wds_user_agent) |>\n"
        "  req_timeout(300) |>\n"
        "  req_error(is_error = \\(response) FALSE) |>\n"
        f'  req_perform(path = "{path}")\n'
        "if (wds_captcha(response)) {\n"
        '  message("Statistics Canada answered the file with its captcha; rebuilding the same rows through WDS instead.")\n'
        f'  file.remove("{path}")\n'
        f'  csv_path <- "data/raw/{pid}-{suffix}-wds.csv"\n'
        "  wds_rebuild(csv_path)\n"
        "} else {\n"
        f'  if (resp_is_error(response)) stop("StatCan answered HTTP ", resp_status(response), " for the file.", call. = FALSE)\n'
        "  # zip::unzip reads member names base R's unzip rejects; the ZIP also holds a\n"
        "  # metadata file, so read the data file.\n"
        f'  zip::unzip("{path}", exdir = "{folder}")\n'
        f'  file.remove("{path}")\n'
        f'  csv_path <- list.files("{folder}", pattern = "[.]csv$", full.names = TRUE)\n'
        '  csv_path <- csv_path[!str_detect(str_to_lower(csv_path), "metadata")][1]\n'
        "}\n"
        f'data <- read_delim(csv_path, delim = "{separator}", col_types = cols(.default = col_character()))\n'
    )
    return ["httr2", "readr", "stringr", "zip"], body


def _literal(value: Any) -> str:
    """A Python literal for a dict of lists of strings (repr is exact for these)."""
    return repr({str(k): [str(v) for v in vs] for k, vs in value.items()})
