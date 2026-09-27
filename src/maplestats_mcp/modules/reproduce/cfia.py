"""Scripts for the CFIA tools, which parse HTML tables on inspection.canada.ca.

The three cfia_ tools read HTML pages that have no data file behind them,
so a recorded request only reproduces the page, not the rows. These
scripts fetch the same pages, parse them the way cfia/client.py does and
repeat each tool's steps:

- cfia_reportable_diseases: every year table on the yearly counts page,
  then the year range, the disease filter (names folded for case, accents
  and apostrophes, with the aliases in constants.DISEASES), the tool's
  order and the optional totals by year or disease.
- cfia_disease_detections: each disease's "data by month" page (herd
  counts such as "Elk (3 herds)", day and month read with the row's year,
  provinces named in the location, BSE's age column), then the year,
  province and animal type filters and the optional counts.
- cfia_avian_influenza: the infected premises table (hidden padding digit,
  quarantine and released markers, premises type, WOAH class, control
  zone and order), then the status, province, date and premises type
  filters, the counts and the limit, plus the status-by-province table.

With lang="fr" the tools take dates, counts and statuses from the English
pages and only labels from the French ones, because the French pages hold
data errors; the scripts do the same, joining premises by id and
detection rows by position only when every year lines up. The yearly
counts page is the exception: the tool reads the page in the chosen
language, whose counts equal the English ones.

Every vocabulary, header check and pattern comes from cfia.constants and
cfia.client (DISEASES, PROVINCES, _MONTHS, the header tuples, the herd and
premises id patterns), so a change there reaches the scripts. Python is
the reference port (BeautifulSoup with the stdlib parser, as the tool);
R uses rvest/xml2 and Julia Gumbo/Cascadia. Stata runs the Python steps in
its built-in Python, as for every filtered file (render.py).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from maplestats_mcp.modules.cfia import client as cfia
from maplestats_mcp.modules.cfia import constants
from maplestats_mcp.modules.reproduce.phac_infobase import _jl_str, _r_str
from maplestats_mcp.modules.reproduce.spec import Code, Spec
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable

_METHOD = "exact: the CFIA pages, parsed and filtered as the tool does"
_AUTHOR = "Canadian Food Inspection Agency"
_USER_AGENT = "MapleStats MCP reproduction script (https://github.com/dsanchezp18/maplestats-mcp)"
_LANGUAGE_NOTE = (
    "The tool takes dates, counts and statuses from the English page and only labels "
    "from the French page, because the French pages hold data errors (a 2019 scrapie "
    'flock dated "21 huin", six premises with another detection date). This script '
    "does the same: it reads the data from the English page and the labels from the "
    "French page, "
)


def _full(pattern: str) -> str:
    """re.fullmatch as a search pattern for ICU (R) and PCRE (Julia)."""
    return f"\\A(?:{pattern})\\z"


# Literals ---------------------------------------------------------------------------------


def _py_dict(value: dict[Any, Any]) -> str:
    items = "".join(f"    {k!r}: {v!r},\n" for k, v in value.items())
    return "{\n" + items + "}" if items else "{}"


def _r_value(value: Any) -> str:
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return f"{value}L"
    if isinstance(value, str):
        return _r_str(value)
    if isinstance(value, list | tuple):
        return "c(" + ", ".join(_r_value(v) for v in value) + ")"
    raise TypeError(type(value))


def _r_named(value: dict[str, Any], *, as_list: bool = False) -> str:
    opener = "list(" if as_list else "c("
    items = "".join(f"  {_r_str(k)} = {_r_value(v)},\n" for k, v in value.items())
    return opener + "\n" + items.rstrip(",\n") + "\n)" if items else opener + ")"


def _jl_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return _jl_str(value)
    if isinstance(value, list | tuple):
        return "[" + ", ".join(_jl_value(v) for v in value) + "]"
    raise TypeError(type(value))


def _jl_dict(value: dict[str, Any]) -> str:
    items = "".join(f"    {_jl_str(k)} => {_jl_value(v)},\n" for k, v in value.items())
    return "Dict(\n" + items + ")" if items else "Dict{String, Any}()"


def _fill(template: str, **values: str) -> str:
    for name, value in values.items():
        template = template.replace(f"__{name}__", value)
    leftover = re.findall(r"__[A-Z][A-Z_]*__", template)
    if leftover:
        raise ValueError(f"unfilled placeholders {sorted(set(leftover))}")
    return template


# Plan -------------------------------------------------------------------------------------


@dataclass
class _Page:
    url: str
    file: str
    role: str
    title: str | None = None
    modified: date | None = None


@dataclass
class _Plan:
    tool: str
    lang: str
    arguments: dict[str, Any]
    pages: list[_Page] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _lang(args: dict[str, Any]) -> str:
    lang = str(args.get("lang", "en"))
    if lang not in ("en", "fr"):
        raise InvalidInput("cfia: lang must be 'en' or 'fr'.")
    return lang


def _int(args: dict[str, Any], name: str) -> int | None:
    value = args.get(name)
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise InvalidInput(f"cfia: {name} must be a whole number, got {value!r}.") from exc


def _text(args: dict[str, Any], name: str) -> str | None:
    value = args.get(name)
    return None if value is None or value == "" else str(value)


def _shown(args: dict[str, Any], names: tuple[str, ...], lang: str) -> dict[str, Any]:
    shown = {k: args[k] for k in names if args.get(k) not in (None, "")}
    shown["lang"] = lang
    return shown


async def _page(kind: str, url: str, ttl: int, parser: Any, file: str, role: str) -> _Page:
    """Title and "Date modified" from the tool's cached parse of the page."""
    try:
        parsed, _ = await cfia._parsed(kind, url, ttl, parser)
    except (UpstreamError, UpstreamUnavailable, NotFound):
        return _Page(url, file, role)
    return _Page(url, file, role, parsed.title, parsed.modified)


def _details(plan: _Plan) -> list[str]:
    lines = [f"Query:   {plan.tool}({json.dumps(plan.arguments, ensure_ascii=False)})"]
    for page in plan.pages:
        lines.append(f"Page:    {page.url}")
        lines.append(
            f"         {page.role}; Date modified {page.modified or 'unknown'} when this "
            "script was made"
        )
    lines.append(
        "Terms:   Canada.ca terms allow non-commercial reproduction that credits the title,"
    )
    lines.append("         the author and the source URL. Credit:")
    for page in plan.pages:
        lines.append(f"         {page.title or page.url}, {_AUTHOR}, {page.url}")
    return lines


# Shared helpers ---------------------------------------------------------------------------

_PY_BASE = r"""
USER_AGENT = __USER_AGENT__
MAX_PAGE_BYTES = __MAX_PAGE_BYTES__
ISO_DATE = re.compile(__ISO_DATE__)


def clean(text):
    return " ".join(text.replace("\xa0", " ").split())


def fold(text):
    text = text.replace("\u0153", "oe").replace("\u0152", "oe").replace("\u00e6", "ae")
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(stripped.casefold().split())


def changed(url, detail):
    raise SystemExit(f"cfia: the page layout changed at {url} ({detail}); stopping rather than risk wrong figures.")


def date_modified(soup):
    node = soup.find("time", attrs={"property": "dateModified"})
    match = ISO_DATE.search(node.get_text()) if node is not None else None
    return match.group(0) if match else None


def fetch_page(url, name):
    time.sleep(1)
    with httpx.Client(http2=True, follow_redirects=True, timeout=60, headers={"User-Agent": USER_AGENT}) as client:
        response = client.get(url)
    if response.status_code in (404, 410):
        changed(url, f"HTTP {response.status_code}, the page moved")
    response.raise_for_status()
    if len(response.content) > MAX_PAGE_BYTES:
        changed(url, "the page is much larger than expected")
    (RAW_DIR / name).write_bytes(response.content)
    soup = BeautifulSoup(response.text, "html.parser")
    heading = soup.find("h1")
    title = clean(heading.get_text(" ")) if heading is not None else url
    print(f"{title}, Canadian Food Inspection Agency, {url} (date modified {date_modified(soup)})")
    return soup


def main_element(soup, url):
    main = soup.find("main")
    if main is None:
        changed(url, "no <main> element")
    return main


def header_cells(table):
    head = table.find("thead")
    row = head.find("tr") if head is not None else table.find("tr")
    if row is None:
        return []
    cells = []
    for cell in row.find_all(["th", "td"]):
        for hidden in cell.select(".wb-inv, .glyphicon"):
            hidden.decompose()
        cells.append(fold(cell.get_text(" ")))
    return cells


def body_rows(table):
    body = table.find("tbody")
    rows = (body if body is not None else table).find_all("tr")
    return [row for row in rows if row.find("td")]


def table_notes(main):
    notes = {}
    for dd in main.find_all("dd", id=True):
        for back in dd.select(".fn-rtn"):
            back.decompose()
        notes[dd["id"]] = clean(dd.get_text(" "))
    return notes


def strip_notes(cell, notes):
    found = []
    for link in cell.find_all("a", class_="fn-lnk"):
        target = str(link.get("href", "")).lstrip("#")
        if target in notes and notes[target] not in found:
            found.append(notes[target])
        link.decompose()
    return clean(cell.get_text(" ")), "; ".join(found) or None
"""

_PY_PROVINCES = r"""
PROVINCES = __PROVINCES__
PROVINCE_ALIASES = __PROVINCE_ALIASES__
PROVINCE_LABELS = __PROVINCE_LABELS__
LOCATION_SEPARATORS = re.compile(__LOCATION_SEPARATORS__)


def province_code(text):
    value = fold(text)
    if value.upper() in PROVINCES:
        return value.upper()
    for code, names in PROVINCES.items():
        if value in {fold(name) for name in names}:
            return code
    return PROVINCE_ALIASES.get(value)


def province_codes_in(location):
    codes = []
    for part in LOCATION_SEPARATORS.split(fold(location)):
        code = province_code(part.strip())
        if code and code not in codes:
            codes.append(code)
    return codes
"""

_PY_DATES = r"""
MONTHS = __MONTHS__


def parse_day_month(text, year):
    day = month = None
    for word in re.findall(r"[^\W\d_]+|\d+", fold(text)):
        if word.isdigit() and day is None:
            day = int(word)
        elif word in MONTHS and month is None:
            month = MONTHS[word]
    if day is None or month is None:
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_long_date(text):
    match = re.search(r"(\d{4})\s*$", fold(text))
    return parse_day_month(text, int(match.group(1))) if match else None
"""

_PY_INT = r"""
def parse_int(text):
    value = text.replace("\xa0", " ").replace("\u202f", " ").strip().strip("`'")
    if re.fullmatch(r"\d{1,3}([ ,]\d{3})+|\d+", value):
        return int(re.sub(r"[ ,]", "", value))
    return None
"""

_PY_IMPORTS = [
    "from pathlib import Path",
    "import re",
    "import time",
    "import unicodedata",
    "from datetime import date",
    "import httpx",
    "import polars as pl",
    "from bs4 import BeautifulSoup",
]

_R_BASE = r"""
user_agent <- __USER_AGENT__
max_page_bytes <- __MAX_PAGE_BYTES__

# Patterns name non-ASCII characters as ICU escapes (\\u00a0): R reads a script
# in the session's locale, and under LANG=C a literal character, or one in a
# vector name, no longer matches (checked with R 4.3).
clean <- function(x) str_squish(str_replace_all(x, "\\u00a0", " "))

fold <- function(x) {
  x <- str_replace_all(x, "\\u0153|\\u0152", "oe")
  x <- str_replace_all(x, "\\u00e6", "ae")
  x <- str_replace_all(x, "[\\u2018\\u2019]", "'")
  x <- str_remove_all(stri_trans_nfkd(x), "\\p{Mn}")
  str_squish(stri_trans_casefold(x))
}

changed <- function(url, detail) {
  stop(str_c("cfia: the page layout changed at ", url, " (", detail, "); stopping rather than risk wrong figures."), call. = FALSE)
}

# All text in a node, as BeautifulSoup's get_text(" ") joins it.
text_of <- function(node, separator = " ") {
  str_c(xml_text(xml_find_all(node, ".//text()")), collapse = separator)
}

date_modified <- function(page) {
  node <- html_element(page, "time[property='dateModified']")
  if (inherits(node, "xml_missing")) NA_character_ else str_extract(xml_text(node), __ISO_DATE__)
}

fetch_page <- function(url, file) {
  Sys.sleep(1)
  path <- file.path("data/raw", file)
  response <- request(url) |>
    req_user_agent(user_agent) |>
    req_error(is_error = \(resp) FALSE) |>
    req_perform(path = path)
  status <- resp_status(response)
  if (status %in% c(404, 410)) changed(url, str_c("HTTP ", status, ", the page moved"))
  if (status >= 400) stop(str_c("cfia: ", url, " returned HTTP ", status), call. = FALSE)
  if (file.size(path) > max_page_bytes) changed(url, "the page is much larger than expected")
  page <- read_html(path, encoding = "UTF-8")
  heading <- html_element(page, "h1")
  title <- if (inherits(heading, "xml_missing")) url else clean(text_of(heading))
  message(title, ", Canadian Food Inspection Agency, ", url, " (date modified ", date_modified(page), ")")
  page
}

main_element <- function(page, url) {
  main <- html_element(page, "main")
  if (inherits(main, "xml_missing")) changed(url, "no <main> element")
  main
}

header_cells <- function(table) {
  head <- html_element(table, "thead")
  row <- html_element(if (inherits(head, "xml_missing")) table else head, "tr")
  if (inherits(row, "xml_missing")) return(character())
  cells <- html_elements(row, "th, td")
  xml_remove(html_elements(cells, ".wb-inv, .glyphicon"))
  vapply(cells, \(cell) fold(text_of(cell)), character(1))
}

body_rows <- function(table) {
  body <- html_element(table, "tbody")
  rows <- html_elements(if (inherits(body, "xml_missing")) table else body, "tr")
  rows[vapply(rows, \(tr) length(html_elements(tr, "td")) > 0, logical(1))]
}

table_notes <- function(main) {
  notes <- list()
  for (dd in html_elements(main, "dd[id]")) {
    xml_remove(html_elements(dd, ".fn-rtn"))
    notes[[xml_attr(dd, "id")]] <- clean(text_of(dd))
  }
  notes
}

strip_notes <- function(cell, notes) {
  found <- character()
  for (link in html_elements(cell, "a.fn-lnk")) {
    target <- str_remove(coalesce(xml_attr(link, "href"), ""), "^#+")
    note <- if (nzchar(target)) notes[[target]] else NULL
    if (!is.null(note) && !(note %in% found)) found <- c(found, note)
    xml_remove(link)
  }
  list(text = clean(text_of(cell)), note = if (length(found)) str_c(found, collapse = "; ") else NA_character_)
}
"""

_R_PROVINCES = r"""
provinces <- __PROVINCES__
province_aliases <- __PROVINCE_ALIASES__
province_labels <- __PROVINCE_LABELS__

province_code <- function(text) {
  value <- fold(text)
  if (toupper(value) %in% names(provinces)) return(toupper(value))
  for (code in names(provinces)) {
    if (value %in% fold(provinces[[code]])) return(code)
  }
  if (value %in% names(province_aliases)) province_aliases[[value]] else NA_character_
}

province_codes_in <- function(location) {
  codes <- character()
  for (part in str_split(fold(location), __LOCATION_SEPARATORS__)[[1]]) {
    code <- province_code(str_trim(part))
    if (!is.na(code) && !(code %in% codes)) codes <- c(codes, code)
  }
  codes
}
"""

_R_DATES = r"""
months <- __MONTHS__

parse_day_month <- function(text, year) {
  day <- NA_real_
  month <- NA_real_
  for (word in str_extract_all(fold(text), "[^\\W\\d_]+|\\d+")[[1]]) {
    if (str_detect(word, "^\\d+$") && is.na(day)) {
      day <- as.numeric(word)
    } else if (word %in% names(months) && is.na(month)) {
      month <- months[[word]]
    }
  }
  if (is.na(day) || is.na(month)) return(as.Date(NA))
  as.Date(sprintf("%.0f-%.0f-%.0f", year, month, day), format = "%Y-%m-%d")
}

parse_long_date <- function(text) {
  year <- str_match(fold(text), "(\\d{4})\\s*$")[1, 2]
  if (is.na(year)) as.Date(NA) else parse_day_month(text, as.numeric(year))
}
"""

_R_INT = r"""
parse_int <- function(text) {
  value <- str_trim(str_replace_all(text, "[\\u00a0\\u202f]", " "), side = "both")
  value <- str_remove_all(value, "^[`']+|[`']+$")
  if (str_detect(value, "^(?:\\d{1,3}(?:[ ,]\\d{3})+|\\d+)$")) as.integer(str_remove_all(value, "[ ,]")) else NA_integer_
}
"""

_R_PACKAGES = ["dplyr", "httr2", "rvest", "stringi", "stringr", "xml2"]

_JL_BASE = r"""
const USER_AGENT = __USER_AGENT__
const MAX_PAGE_BYTES = __MAX_PAGE_BYTES__
const ISO_DATE = Regex(__ISO_DATE__)

clean(text) = join(split(replace(text, '\u00a0' => ' ')), " ")

function fold(text)
    text = replace(text, "\u0153" => "oe", "\u0152" => "oe", "\u00e6" => "ae", "\u2019" => "'", "\u2018" => "'")
    text = Unicode.normalize(text; compat = true, stripmark = true)
    return join(split(Unicode.normalize(text; casefold = true)), " ")
end

changed(url, detail) = error("cfia: the page layout changed at $(url) ($(detail)); stopping rather than risk wrong figures.")

has_class(node, name) = node isa HTMLElement && name in split(get(attrs(node), "class", ""))
first_match(node, selector) = (found = eachmatch(Selector(selector), node); isempty(found) ? nothing : first(found))
child_cells(tr) = [c for c in children(tr) if c isa HTMLElement && tag(c) in (:th, :td)]

# All text in a node, as BeautifulSoup's get_text(" ") joins it, leaving out
# the nodes the tool removes first (skip).
function texts!(out, node, skip)
    if node isa HTMLText
        push!(out, node.text)
    elseif node isa HTMLElement && !skip(node)
        foreach(child -> texts!(out, child, skip), children(node))
    end
    return out
end
text_of(node, skip = _ -> false; separator = " ") = join(texts!(String[], node, skip), separator)

function date_modified(root)
    node = first_match(root, "time[property=dateModified]")
    found = node === nothing ? nothing : match(ISO_DATE, text_of(node))
    return found === nothing ? missing : found.match
end

function fetch_page(url, file)
    sleep(1)
    path = joinpath("data", "raw", file)
    response = Downloads.request(url; output = path, headers = ["User-Agent" => USER_AGENT])
    response.status in (404, 410) && changed(url, "HTTP $(response.status), the page moved")
    response.status >= 400 && error("cfia: $(url) returned HTTP $(response.status)")
    filesize(path) > MAX_PAGE_BYTES && changed(url, "the page is much larger than expected")
    root = parsehtml(read(path, String)).root
    heading = first_match(root, "h1")
    title = heading === nothing ? url : clean(text_of(heading))
    println("$(title), Canadian Food Inspection Agency, $(url) (date modified $(date_modified(root)))")
    return root
end

function main_element(root, url)
    main = first_match(root, "main")
    main === nothing && changed(url, "no <main> element")
    return main
end

function header_cells(table)
    head = first_match(table, "thead")
    row = first_match(head === nothing ? table : head, "tr")
    row === nothing && return String[]
    hidden = node -> has_class(node, "wb-inv") || has_class(node, "glyphicon")
    return String[fold(clean(text_of(cell, hidden))) for cell in eachmatch(Selector("th, td"), row)]
end

function body_rows(table)
    body = first_match(table, "tbody")
    rows = eachmatch(Selector("tr"), body === nothing ? table : body)
    return filter(tr -> first_match(tr, "td") !== nothing, rows)
end

function table_notes(main)
    notes = Dict{String, String}()
    for dd in eachmatch(Selector("dd[id]"), main)
        notes[attrs(dd)["id"]] = clean(text_of(dd, node -> has_class(node, "fn-rtn")))
    end
    return notes
end

is_note_link(node) = node isa HTMLElement && tag(node) == :a && has_class(node, "fn-lnk")

function strip_notes(cell, notes)
    found = String[]
    for link in eachmatch(Selector("a.fn-lnk"), cell)
        target = lstrip(get(attrs(link), "href", ""), '#')
        if haskey(notes, target) && !(notes[target] in found)
            push!(found, notes[target])
        end
    end
    return clean(text_of(cell, is_note_link)), isempty(found) ? missing : join(found, "; ")
end

# One column per field, from rows held as NamedTuples.
frame(rows, columns) = DataFrame([name => [getfield(row, name) for row in rows] for name in columns])
# combine() calls its functions on an empty vector when nothing matched.
first_or_missing(values) = isempty(values) ? missing : first(values)
"""

_JL_PROVINCES = r"""
# Codes with their English and French names, in the tool's order.
const PROVINCES = __PROVINCES__
const PROVINCE_CODES = first.(PROVINCES)
const PROVINCE_ALIASES = __PROVINCE_ALIASES__
const PROVINCE_LABELS = __PROVINCE_LABELS__
const LOCATION_SEPARATORS = Regex(__LOCATION_SEPARATORS__)

function province_code(text)
    value = fold(text)
    uppercase(value) in PROVINCE_CODES && return uppercase(value)
    for (code, names) in PROVINCES
        value in fold.(names) && return code
    end
    return get(PROVINCE_ALIASES, value, missing)
end

function province_codes_in(location)
    codes = String[]
    for part in split(fold(location), LOCATION_SEPARATORS)
        code = province_code(strip(part))
        !ismissing(code) && !(code in codes) && push!(codes, code)
    end
    return codes
end
"""

_JL_DATES = r"""
const MONTHS = __MONTHS__

function parse_day_month(text, year)
    day = nothing
    month = nothing
    for found in eachmatch(r"[^\W\d_]+|\d+", fold(text))
        word = found.match
        if all(isdigit, word) && day === nothing
            day = parse(BigInt, word)
        elseif haskey(MONTHS, word) && month === nothing
            month = MONTHS[word]
        end
    end
    (day === nothing || month === nothing) && return missing
    day > 31 && return missing
    return Dates.validargs(Date, year, month, Int(day)) === nothing ? Date(year, month, Int(day)) : missing
end

function parse_long_date(text)
    found = match(r"(\d{4})\s*$", fold(text))
    return found === nothing ? missing : parse_day_month(text, parse(Int, found[1]))
end
"""

_JL_INT = r"""
function parse_int(text)
    value = strip(strip(replace(text, '\u00a0' => ' ', '\u202f' => ' ')), ['`', '\''])
    occursin(r"^(?:\d{1,3}(?:[ ,]\d{3})+|\d+)$", value) || return missing
    return parse(Int, replace(value, r"[ ,]" => ""))
end
"""


_JL_PACKAGES = ["Cascadia", "DataFrames", "Dates", "Downloads", "Gumbo", "Unicode"]


def _jl_pairs(value: dict[str, Any]) -> str:
    """An ordered Julia vector of pairs (a Dict would lose the tool's order)."""
    items = "".join(f"    {_jl_str(k)} => {_jl_value(v)},\n" for k, v in value.items())
    return "[\n" + items + "]"


def _helpers(language: str, label_lang: str, *, dates: bool, ints: bool) -> str:
    """Shared helper code for one language, with the module's own tables filled in."""
    labels = {code: cfia.province_label(code, label_lang) for code in constants.PROVINCES}
    names = {code: list(pair) for code, pair in constants.PROVINCES.items()}
    months = dict(cfia._MONTHS)
    iso = cfia._ISO_DATE.pattern
    separators = cfia.LOCATION_SEPARATORS.pattern
    if language == "python":
        values = {
            "USER_AGENT": repr(_USER_AGENT),
            "ISO_DATE": repr(iso),
            "PROVINCES": _py_dict({k: tuple(v) for k, v in names.items()}),
            "PROVINCE_ALIASES": _py_dict(constants.PROVINCE_ALIASES),
            "PROVINCE_LABELS": _py_dict(labels),
            "LOCATION_SEPARATORS": repr(separators),
            "MONTHS": _py_dict(months),
        }
        parts = [_PY_BASE, _PY_PROVINCES, _PY_DATES if dates else "", _PY_INT if ints else ""]
    elif language == "r":
        values = {
            "USER_AGENT": _r_str(_USER_AGENT),
            "ISO_DATE": _r_str(iso.replace("(", "").replace(")", "")),
            "PROVINCES": _r_named(names, as_list=True),
            "PROVINCE_ALIASES": _r_named(constants.PROVINCE_ALIASES),
            "PROVINCE_LABELS": _r_named(labels),
            "LOCATION_SEPARATORS": _r_str(separators),
            "MONTHS": _r_named(months),
        }
        parts = [_R_BASE, _R_PROVINCES, _R_DATES if dates else "", _R_INT if ints else ""]
    else:
        values = {
            "USER_AGENT": _jl_str(_USER_AGENT),
            "ISO_DATE": _jl_str(iso),
            "PROVINCES": _jl_pairs(names),
            "PROVINCE_ALIASES": _jl_dict(constants.PROVINCE_ALIASES),
            "PROVINCE_LABELS": _jl_dict(labels),
            "LOCATION_SEPARATORS": _jl_str(separators),
            "MONTHS": _jl_dict(months),
        }
        parts = [_JL_BASE, _JL_PROVINCES, _JL_DATES if dates else "", _JL_INT if ints else ""]
    values["MAX_PAGE_BYTES"] = str(constants.MAX_PAGE_BYTES)
    return _fill("".join(parts), **values).strip("\n") + "\n"


def _comment(lines: list[str], prefix: str = "#") -> str:
    """Comment lines wrapped at 80 characters; list items keep their indent."""
    out = ""
    for line in lines:
        indent = "  " if line.startswith("- ") else ""
        for index, part in enumerate(_wrap(line, 76 - len(indent))):
            out += f"{prefix} {indent if index else ''}{part}".rstrip() + "\n"
    return out


def _wrap(text: str, width: int = 76) -> list[str]:
    words, lines, line = text.split(), [], ""
    for word in words:
        if line and len(line) + 1 + len(word) > width:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    return [*lines, line] if line else lines


# cfia_reportable_diseases ----------------------------------------------------------------

_PY_REPORTABLE = r"""
URL = __URL__
PAGE_FILE = __FILE__
# Every spelling of each disease the tool knows (constants.DISEASES), folded.
DISEASE_KEYS = __DISEASE_KEYS__
DETECTION_KEYS = __DETECTION_KEYS__
AS_OF = re.compile(__AS_OF__, re.IGNORECASE)
YEAR_HEADING = re.compile(__YEAR_HEADING__)
REPORTABLE_COLUMNS = __REPORTABLE_COLUMNS__


def disease_key(name):
    folded = fold(name)
    if folded in DISEASE_KEYS:
        return DISEASE_KEYS[folded]
    return re.sub(r"[^a-z0-9]+", "_", folded).strip("_") or "unknown"


def detections_tool(key, year):
    if key == "avian_influenza" and year >= 2021:
        return "cfia_avian_influenza"
    return "cfia_disease_detections" if key in DETECTION_KEYS else None


def parse_reportable(soup, url):
    main = main_element(soup, url)
    notes = table_notes(main)
    as_of = AS_OF.search(clean(main.get_text(" ")))
    tables = main.find_all("table")
    if not tables:
        changed(url, "no yearly tables")
    rows = []
    for table in tables:
        heading = table.find_previous("h2")
        year_text = clean(heading.get_text(" ")) if heading is not None else ""
        if not YEAR_HEADING.fullmatch(year_text):
            changed(url, f"a table is not under a year heading ({year_text[:40]!r})")
        header = header_cells(table)
        if header[:2] not in REPORTABLE_COLUMNS:
            changed(url, f"unexpected columns {header}")
        for tr in body_rows(table):
            cells = tr.find_all("td")
            if len(cells) < 2:
                continue
            name, note = strip_notes(cells[0], notes)
            count_text = clean(cells[1].get_text(" "))
            match = re.match(r"\d[\d ,]*", count_text)
            if not name and not count_text:
                continue
            count = parse_int(match.group(0).strip()) if match else None
            if not name or count is None:
                changed(url, f"unreadable row {name!r} / {count_text!r}")
            key = disease_key(name)
            year = int(year_text)
            rows.append({"year": year, "disease_key": key, "disease": name, "count": count, "note": note, "detections_tool": detections_tool(key, year)})
    return rows, (as_of.group(1) if as_of else None)


SCHEMA = {"year": pl.Int64, "disease_key": pl.Utf8, "disease": pl.Utf8, "count": pl.Int64, "note": pl.Utf8, "detections_tool": pl.Utf8}
rows, current_as_of = parse_reportable(fetch_page(URL, PAGE_FILE), URL)
print(f"Current as of {current_as_of}: counts run to the end of that month.")
data = pl.DataFrame(rows, schema=SCHEMA)
"""

_R_REPORTABLE = r"""
url <- __URL__
page_file <- __FILE__
# Every spelling of each disease the tool knows (constants.DISEASES), folded.
disease_keys <- __DISEASE_KEYS__
detection_keys <- __DETECTION_KEYS__
as_of_pattern <- regex(__AS_OF__, ignore_case = TRUE)
year_heading <- __YEAR_HEADING__
reportable_columns <- __REPORTABLE_COLUMNS__

disease_key <- function(name) {
  folded <- fold(name)
  if (folded %in% names(disease_keys)) return(disease_keys[[folded]])
  key <- str_remove_all(str_replace_all(folded, "[^a-z0-9]+", "_"), "^_+|_+$")
  if (nzchar(key)) key else "unknown"
}

detections_tool <- function(key, year) {
  if (key == "avian_influenza" && year >= 2021) return("cfia_avian_influenza")
  if (key %in% detection_keys) "cfia_disease_detections" else NA_character_
}

parse_reportable <- function(page, url) {
  main <- main_element(page, url)
  notes <- table_notes(main)
  as_of <- str_match(clean(text_of(main)), as_of_pattern)[1, 2]
  tables <- html_elements(main, "table")
  if (length(tables) == 0) changed(url, "no yearly tables")
  rows <- list()
  for (table in tables) {
    # The nearest <h2> before the table, as BeautifulSoup's find_previous("h2").
    heading <- xml_find_first(table, "preceding::h2[1]")
    year_text <- if (inherits(heading, "xml_missing")) "" else clean(text_of(heading))
    if (!str_detect(year_text, year_heading)) changed(url, str_c("a table is not under a year heading (", str_sub(year_text, 1, 40), ")"))
    header <- header_cells(table)
    if (!any(vapply(reportable_columns, \(columns) identical(head(header, 2), columns), logical(1)))) {
      changed(url, str_c("unexpected columns ", str_c(header, collapse = " | ")))
    }
    for (tr in body_rows(table)) {
      cells <- html_elements(tr, "td")
      if (length(cells) < 2) next
      name <- strip_notes(cells[[1]], notes)
      count_text <- clean(text_of(cells[[2]]))
      count_match <- str_extract(count_text, "^\\d[\\d ,]*")
      if (!nzchar(name$text) && !nzchar(count_text)) next
      count <- if (is.na(count_match)) NA_integer_ else parse_int(str_trim(count_match))
      if (!nzchar(name$text) || is.na(count)) changed(url, str_c("unreadable row ", name$text, " / ", count_text))
      key <- disease_key(name$text)
      year <- as.integer(year_text)
      rows[[length(rows) + 1]] <- list(
        year = year, disease_key = key, disease = name$text, count = count,
        note = name$note, detections_tool = detections_tool(key, year)
      )
    }
  }
  list(rows = bind_rows(rows), current_as_of = as_of)
}

parsed <- parse_reportable(fetch_page(url, page_file), url)
message("Current as of ", parsed$current_as_of, ": counts run to the end of that month.")
data <- parsed$rows
"""

_JL_REPORTABLE = r"""
const URL = __URL__
const PAGE_FILE = __FILE__
# Every spelling of each disease the tool knows (constants.DISEASES), folded.
const DISEASE_KEYS = __DISEASE_KEYS__
const DETECTION_KEYS = __DETECTION_KEYS__
const AS_OF = Regex(__AS_OF__, "i")
const YEAR_HEADING = Regex(__YEAR_HEADING__)
const REPORTABLE_COLUMNS = __REPORTABLE_COLUMNS__

function disease_key(name)
    folded = fold(name)
    haskey(DISEASE_KEYS, folded) && return DISEASE_KEYS[folded]
    key = strip(replace(folded, r"[^a-z0-9]+" => "_"), '_')
    return isempty(key) ? "unknown" : String(key)
end

function detections_tool(key, year)
    key == "avian_influenza" && year >= 2021 && return "cfia_avian_influenza"
    return key in DETECTION_KEYS ? "cfia_disease_detections" : missing
end

# Every node in document order, to find the <h2> before each table as
# BeautifulSoup's find_previous("h2") does.
function preorder!(out, node)
    push!(out, node)
    node isa HTMLElement && foreach(child -> preorder!(out, child), children(node))
    return out
end

function parse_reportable(root, url)
    main = main_element(root, url)
    notes = table_notes(main)
    as_of = match(AS_OF, clean(text_of(main, node -> has_class(node, "fn-rtn"))))
    tables = eachmatch(Selector("table"), main)
    isempty(tables) && changed(url, "no yearly tables")
    order = preorder!(Any[], root)
    rows = NamedTuple[]
    for table in tables
        at = findfirst(node -> node === table, order)
        before = findlast(node -> node isa HTMLElement && tag(node) == :h2, order[1:at-1])
        year_text = before === nothing ? "" : clean(text_of(order[before]))
        occursin(YEAR_HEADING, year_text) || changed(url, "a table is not under a year heading ($(first(year_text, 40)))")
        header = header_cells(table)
        first(header, 2) in REPORTABLE_COLUMNS || changed(url, "unexpected columns $(join(header, " | "))")
        for tr in body_rows(table)
            cells = eachmatch(Selector("td"), tr)
            length(cells) < 2 && continue
            name, note = strip_notes(cells[1], notes)
            count_text = clean(text_of(cells[2]))
            count_match = match(r"^\d[\d ,]*", count_text)
            isempty(name) && isempty(count_text) && continue
            count = count_match === nothing ? missing : parse_int(strip(count_match.match))
            (isempty(name) || ismissing(count)) && changed(url, "unreadable row $(name) / $(count_text)")
            key = disease_key(name)
            year = parse(Int, year_text)
            push!(rows, (year = year, disease_key = key, disease = name, count = count, note = note, detections_tool = detections_tool(key, year)))
        end
    end
    return rows, as_of === nothing ? missing : as_of[1]
end

rows, current_as_of = parse_reportable(fetch_page(URL, PAGE_FILE), URL)
println("Current as of $(current_as_of): counts run to the end of that month.")
data = frame(rows, [:year, :disease_key, :disease, :count, :note, :detections_tool])
"""


@dataclass
class _Reportable:
    lang: str
    year_from: int | None
    year_to: int | None
    keys: list[str] | None  # None: no disease filter
    name_query: str | None  # folded query matched inside names (3+ characters)
    totals_by: str | None


def _reportable_values(language: str, url: str, file: str) -> dict[str, str]:
    candidates: dict[str, str] = {}
    for key in constants.DISEASES:
        for spelling in sorted(cfia._disease_candidates(key)):
            candidates.setdefault(spelling, key)
    detection_keys = list(constants.DETECTION_PAGES)
    columns = [list(c) for c in cfia.REPORTABLE_COLUMNS]
    if language == "python":
        return {
            "URL": repr(url),
            "FILE": repr(file),
            "DISEASE_KEYS": _py_dict(candidates),
            "DETECTION_KEYS": repr(tuple(detection_keys)),
            "AS_OF": repr(cfia.AS_OF.pattern),
            "YEAR_HEADING": repr(cfia.YEAR_HEADING.pattern),
            "REPORTABLE_COLUMNS": repr(tuple(columns)),
        }
    if language == "r":
        return {
            "URL": _r_str(url),
            "FILE": _r_str(file),
            "DISEASE_KEYS": _r_named(candidates),
            "DETECTION_KEYS": _r_value(detection_keys),
            "AS_OF": _r_str(cfia.AS_OF.pattern),
            "YEAR_HEADING": _r_str(_full(cfia.YEAR_HEADING.pattern)),
            "REPORTABLE_COLUMNS": "list(" + ", ".join(_r_value(c) for c in columns) + ")",
        }
    return {
        "URL": _jl_str(url),
        "FILE": _jl_str(file),
        "DISEASE_KEYS": _jl_dict(candidates),
        "DETECTION_KEYS": _jl_value(detection_keys),
        "AS_OF": _jl_str(cfia.AS_OF.pattern),
        "YEAR_HEADING": _jl_str(_full(cfia.YEAR_HEADING.pattern)),
        "REPORTABLE_COLUMNS": "[" + ", ".join(_jl_value(c) for c in columns) + "]",
    }


def _reportable_steps(q: _Reportable) -> list[str]:
    steps = ["Keep the rows cfia_reportable_diseases kept, in its order:"]
    if q.year_from is not None or q.year_to is not None:
        steps.append(f"- years {q.year_from or 'first'} to {q.year_to or 'last'};")
    if q.keys is not None:
        known = ", ".join(q.keys) or "none by exact name"
        extra = (
            " or a disease name that holds the query (NAME_QUERY), compared as fold() does"
            if q.name_query
            else ""
        )
        steps.append(f"- diseases {known}{extra};")
    steps.append("- newest year first, then by disease name as fold() writes it.")
    if q.totals_by:
        steps.append(
            f"Then the totals by {q.totals_by}: the counts added up and the rows in each "
            + ("(newest year first)." if q.totals_by == "year" else "(largest total first).")
        )
    return steps


def _reportable_py(q: _Reportable, totals_file: str) -> str:
    out = _comment(_reportable_steps(q)) + "\n"
    if q.year_from is not None:
        out += f'data = data.filter(pl.col("year") >= {q.year_from})\n'
    if q.year_to is not None:
        out += f'data = data.filter(pl.col("year") <= {q.year_to})\n'
    if q.keys is not None:
        out += f"DISEASES = {q.keys!r}\n"
        condition = 'pl.col("disease_key").is_in(DISEASES)'
        if q.name_query:
            out += f"NAME_QUERY = {q.name_query!r}\n"
            condition += (
                ' | pl.col("disease").map_elements(lambda name: NAME_QUERY in fold(name), '
                "return_dtype=pl.Boolean)"
            )
        out += f"data = data.filter({condition})\n"
    out += (
        'data = data.sort([pl.col("year"), pl.col("disease").map_elements(fold, '
        "return_dtype=pl.Utf8)], descending=[True, False], maintain_order=True)\n"
    )
    if q.totals_by == "year":
        out += (
            "\ntotals = (\n"
            '    data.group_by("year", maintain_order=True)\n'
            '    .agg(pl.col("count").sum().alias("total"), pl.len().alias("rows"))\n'
            '    .sort("year", descending=True)\n'
            '    .select(pl.col("year").cast(pl.Utf8).alias("key"), '
            'pl.col("year").cast(pl.Utf8).alias("label"), "total", "rows")\n'
            ")\n"
        )
    elif q.totals_by == "disease":
        labels = {k: cfia.disease_label(k, q.lang) for k in constants.DISEASES}
        out += (
            f"DISEASE_LABELS = {_py_dict(labels)}\n"
            "totals = (\n"
            '    data.group_by("disease_key", maintain_order=True)\n'
            '    .agg(pl.col("disease").first(), pl.col("count").sum().alias("total"), '
            'pl.len().alias("rows"))\n'
            '    .with_columns(pl.col("disease_key").replace_strict(DISEASE_LABELS, '
            'default=pl.col("disease")).alias("label"))\n'
            '    .sort(["total", "disease_key"], descending=[True, False])\n'
            '    .select(pl.col("disease_key").alias("key"), "label", "total", "rows")\n'
            ")\n"
        )
    if q.totals_by:
        out += f'print(totals)\ntotals.write_csv(RAW_DIR / "{totals_file}.csv")\n'
    return out


def _reportable_r(q: _Reportable) -> str:
    steps: list[str] = []
    if q.year_from is not None:
        steps.append(f"filter(year >= {q.year_from}L)")
    if q.year_to is not None:
        steps.append(f"filter(year <= {q.year_to}L)")
    if q.keys is not None:
        condition = f"disease_key %in% {_r_value(q.keys)}"
        if q.name_query:
            condition += f" | str_detect(fold(disease), fixed({_r_str(q.name_query)}))"
        steps.append(f"filter({condition})")
    steps.append("arrange(desc(year), fold(disease))")
    out = _comment(_reportable_steps(q)) + "\ndata <- data |>\n  " + " |>\n  ".join(steps) + "\n"
    if q.totals_by == "year":
        out += (
            "\ntotals <- data |>\n"
            "  group_by(key = as.character(year)) |>\n"
            '  summarise(label = first(key), total = sum(count), rows = n(), .groups = "drop") |>\n'
            "  arrange(desc(as.integer(key)))\n"
            "print(totals)\n"
        )
    elif q.totals_by == "disease":
        labels = {k: cfia.disease_label(k, q.lang) for k in constants.DISEASES}
        out += (
            f"\ndisease_labels <- {_r_named(labels)}\n"
            "totals <- data |>\n"
            "  mutate(key = disease_key, label = coalesce(unname(disease_labels[disease_key]), disease)) |>\n"
            "  group_by(key) |>\n"
            '  summarise(label = first(label), total = sum(count), rows = n(), .groups = "drop") |>\n'
            "  arrange(desc(total), key)\n"
            "print(totals)\n"
        )
    return out


def _reportable_jl(q: _Reportable) -> str:
    out = _comment(_reportable_steps(q)) + "\n"
    if q.year_from is not None:
        out += f"data = filter(row -> row.year >= {q.year_from}, data)\n"
    if q.year_to is not None:
        out += f"data = filter(row -> row.year <= {q.year_to}, data)\n"
    if q.keys is not None:
        out += f"const DISEASES = {_jl_value(q.keys)}\n"
        condition = "row.disease_key in DISEASES"
        if q.name_query:
            out += f"const NAME_QUERY = {_jl_str(q.name_query)}\n"
            condition += " || occursin(NAME_QUERY, fold(row.disease))"
        out += f"data = filter(row -> {condition}, data)\n"
    out += (
        "data = sort(data, [order(:year, rev = true), order(:disease, by = fold)]; "
        "alg = MergeSort)\n"
    )
    if q.totals_by == "year":
        out += (
            "\ntotals = combine(\n"
            "    groupby(transform(data, :year => ByRow(string) => :key), :key; sort = false),\n"
            "    :key => first_or_missing => :label, :count => sum => :total, nrow => :rows,\n"
            ")\n"
            "totals = sort(totals, :key; by = key -> -parse(Int, key))\n"
            "println(totals)\n"
        )
    elif q.totals_by == "disease":
        labels = {k: cfia.disease_label(k, q.lang) for k in constants.DISEASES}
        out += (
            f"\nconst DISEASE_LABELS = {_jl_dict(labels)}\n"
            "labeled = transform(\n"
            "    data,\n"
            "    :disease_key => :key,\n"
            "    [:disease_key, :disease] => ByRow((key, name) -> get(DISEASE_LABELS, key, name)) => :label,\n"
            ")\n"
            "totals = combine(\n"
            "    groupby(labeled, :key; sort = false),\n"
            "    :label => first_or_missing => :label, :count => sum => :total, nrow => :rows,\n"
            ")\n"
            "totals = sort(totals, [order(:total, rev = true), :key])\n"
            "println(totals)\n"
        )
    return out


# cfia_disease_detections -----------------------------------------------------------------

_PY_DETECTIONS = r"""
# (disease key, English page, French page, and the files they are saved as)
PAGES = __PAGES__
LANG = __LANG__
READ_FRENCH = __READ_FRENCH__
DISEASE_LABELS = __DISEASE_LABELS__
HERDS = re.compile(__HERDS__, re.IGNORECASE)
YEAR_HEADING = re.compile(__YEAR_HEADING__)
YEAR_COLUMN = __YEAR_COLUMN__
DATE_COLUMN = __DATE_COLUMN__
LOCATION_COLUMN = __LOCATION_COLUMN__


def parse_detections(soup, url):
    main = main_element(soup, url)
    notes = table_notes(main)
    table = None
    for candidate in main.find_all("table"):
        header = header_cells(candidate)
        if len(header) >= 4 and header[0] in YEAR_COLUMN and header[1].startswith(DATE_COLUMN) and header[2] in LOCATION_COLUMN:
            table = candidate
            break
    if table is None:
        changed(url, "no Year / Date confirmed / Location / Animal type table")
    has_age = len(header_cells(table)) >= 5
    rows = []
    for tr in body_rows(table):
        cells = tr.find_all(["td", "th"], recursive=False)
        texts = [clean(cell.get_text(" ")) for cell in cells]
        if not any(texts):
            continue
        if len(cells) < 4 or not YEAR_HEADING.fullmatch(texts[0]):
            changed(url, f"unreadable row {texts}")
        date_text, date_note = strip_notes(cells[1], notes)
        animal, animal_note = strip_notes(cells[3], notes)
        location, location_note = strip_notes(cells[2], notes)
        herds = 1
        match = HERDS.search(animal)
        if match:
            herds = int(match.group(1))
            animal = clean(HERDS.sub(" ", animal))
        note = "; ".join(n for n in (date_note, location_note, animal_note) if n) or None
        age = texts[4] if has_age and len(texts) > 4 and texts[4] else None
        rows.append({"year": int(texts[0]), "date_text": date_text, "location": location, "animal_type": animal, "herds": herds, "age": age, "note": note})
    if not rows:
        changed(url, "the detection table is empty")
    return rows


def french_rows(url, name, english):
    try:
        french = parse_detections(fetch_page(url, name), url)
    except (SystemExit, httpx.HTTPError) as error:
        print(f"{url} could not be read ({error}); labels stay in English, as the tool keeps them.")
        return None
    if [row["year"] for row in french] != [row["year"] for row in english]:
        print(f"{url} does not have the same rows as the English page; labels stay in English, as the tool keeps them.")
        return None
    return french


def detections_for(key, url_en, url_fr, file_en, file_fr):
    english = parse_detections(fetch_page(url_en, file_en), url_en)
    french = french_rows(url_fr, file_fr, english) if READ_FRENCH else None
    labels = french if LANG == "fr" and french is not None else english
    others = french if french is not None else [None] * len(english)
    rows = []
    for row, label, other in zip(english, labels, others):
        rows.append({
            "disease_key": key,
            "disease": DISEASE_LABELS[key],
            "year": row["year"],
            "date_confirmed": parse_day_month(row["date_text"], row["year"]),
            "date_text": label["date_text"],
            "location": label["location"],
            "province_codes": ",".join(province_codes_in(row["location"])),
            "animal_type": label["animal_type"],
            "herds": row["herds"],
            "age": label["age"],
            "note": label["note"],
            "animal_type_en": row["animal_type"],
            "animal_type_fr": other["animal_type"] if other is not None else None,
        })
    return rows


SCHEMA = {"disease_key": pl.Utf8, "disease": pl.Utf8, "year": pl.Int64, "date_confirmed": pl.Date, "date_text": pl.Utf8, "location": pl.Utf8, "province_codes": pl.Utf8, "animal_type": pl.Utf8, "herds": pl.Int64, "age": pl.Utf8, "note": pl.Utf8, "animal_type_en": pl.Utf8, "animal_type_fr": pl.Utf8}
rows = []
for page in PAGES:
    rows.extend(detections_for(*page))
data = pl.DataFrame(rows, schema=SCHEMA)
"""

_R_DETECTIONS = r"""
# (disease key, English page, French page, and the files they are saved as)
pages <- __PAGES__
lang <- __LANG__
read_french <- __READ_FRENCH__
disease_labels <- __DISEASE_LABELS__
herds_pattern <- regex(__HERDS__, ignore_case = TRUE)
year_heading <- __YEAR_HEADING__
year_column <- __YEAR_COLUMN__
date_column <- __DATE_COLUMN__
location_column <- __LOCATION_COLUMN__

parse_detections <- function(page, url) {
  main <- main_element(page, url)
  notes <- table_notes(main)
  table <- NULL
  for (candidate in html_elements(main, "table")) {
    header <- header_cells(candidate)
    if (length(header) >= 4 && header[1] %in% year_column && str_starts(header[2], fixed(date_column)) && header[3] %in% location_column) {
      table <- candidate
      break
    }
  }
  if (is.null(table)) changed(url, "no Year / Date confirmed / Location / Animal type table")
  has_age <- length(header_cells(table)) >= 5
  rows <- list()
  for (tr in body_rows(table)) {
    cells <- xml_find_all(tr, "./td | ./th")
    texts <- vapply(cells, \(cell) clean(text_of(cell)), character(1))
    if (!any(nzchar(texts))) next
    if (length(cells) < 4 || !str_detect(texts[1], year_heading)) changed(url, str_c("unreadable row ", str_c(texts, collapse = " | ")))
    date_cell <- strip_notes(cells[[2]], notes)
    animal_cell <- strip_notes(cells[[4]], notes)
    location_cell <- strip_notes(cells[[3]], notes)
    animal <- animal_cell$text
    herds <- 1L
    herd_match <- str_match(animal, herds_pattern)
    if (!is.na(herd_match[1, 1])) {
      herds <- as.integer(herd_match[1, 2])
      animal <- clean(str_replace_all(animal, herds_pattern, " "))
    }
    row_notes <- c(date_cell$note, location_cell$note, animal_cell$note)
    row_notes <- row_notes[!is.na(row_notes) & nzchar(row_notes)]
    rows[[length(rows) + 1]] <- list(
      year = as.integer(texts[1]), date_text = date_cell$text, location = location_cell$text,
      animal_type = animal, herds = herds,
      age = if (has_age && length(texts) > 4 && nzchar(texts[5])) texts[5] else NA_character_,
      note = if (length(row_notes)) str_c(row_notes, collapse = "; ") else NA_character_
    )
  }
  if (length(rows) == 0) changed(url, "the detection table is empty")
  rows
}

french_rows <- function(url, file, english) {
  french <- tryCatch(
    parse_detections(fetch_page(url, file), url),
    error = \(error) {
      message(url, " could not be read (", conditionMessage(error), "); labels stay in English, as the tool keeps them.")
      NULL
    }
  )
  if (is.null(french)) return(NULL)
  years <- \(rows) vapply(rows, \(row) row$year, integer(1))
  if (!identical(years(french), years(english))) {
    message(url, " does not have the same rows as the English page; labels stay in English, as the tool keeps them.")
    return(NULL)
  }
  french
}

detections_for <- function(page) {
  english <- parse_detections(fetch_page(page$url_en, page$file_en), page$url_en)
  french <- if (read_french) french_rows(page$url_fr, page$file_fr, english) else NULL
  labels <- if (lang == "fr" && !is.null(french)) french else english
  lapply(seq_along(english), \(i) {
    row <- english[[i]]
    label <- labels[[i]]
    list(
      disease_key = page$key, disease = disease_labels[[page$key]], year = row$year,
      date_confirmed = parse_day_month(row$date_text, row$year),
      date_text = label$date_text, location = label$location,
      province_codes = str_c(province_codes_in(row$location), collapse = ","),
      animal_type = label$animal_type, herds = row$herds, age = label$age, note = label$note,
      animal_type_en = row$animal_type,
      animal_type_fr = if (is.null(french)) NA_character_ else french[[i]]$animal_type
    )
  })
}

rows <- list()
for (page in pages) rows <- c(rows, detections_for(page))
data <- bind_rows(rows)
"""

_JL_DETECTIONS = r"""
# (disease key, English page, French page, and the files they are saved as)
const PAGES = __PAGES__
const LANG = __LANG__
const READ_FRENCH = __READ_FRENCH__
const DISEASE_LABELS = __DISEASE_LABELS__
const HERDS = Regex(__HERDS__, "i")
const YEAR_HEADING = Regex(__YEAR_HEADING__)
const YEAR_COLUMN = __YEAR_COLUMN__
const DATE_COLUMN = __DATE_COLUMN__
const LOCATION_COLUMN = __LOCATION_COLUMN__

function parse_detections(root, url)
    main = main_element(root, url)
    notes = table_notes(main)
    at = findfirst(eachmatch(Selector("table"), main)) do candidate
        header = header_cells(candidate)
        length(header) >= 4 && header[1] in YEAR_COLUMN && startswith(header[2], DATE_COLUMN) && header[3] in LOCATION_COLUMN
    end
    at === nothing && changed(url, "no Year / Date confirmed / Location / Animal type table")
    table = eachmatch(Selector("table"), main)[at]
    has_age = length(header_cells(table)) >= 5
    rows = NamedTuple[]
    for tr in body_rows(table)
        cells = child_cells(tr)
        texts = [clean(text_of(cell)) for cell in cells]
        all(isempty, texts) && continue
        (length(cells) < 4 || !occursin(YEAR_HEADING, texts[1])) && changed(url, "unreadable row $(join(texts, " | "))")
        date_text, date_note = strip_notes(cells[2], notes)
        animal, animal_note = strip_notes(cells[4], notes)
        location, location_note = strip_notes(cells[3], notes)
        herds = 1
        found = match(HERDS, animal)
        if found !== nothing
            herds = parse(Int, found[1])
            animal = clean(replace(animal, HERDS => " "))
        end
        row_notes = [n for n in (date_note, location_note, animal_note) if !ismissing(n) && !isempty(n)]
        age = has_age && length(texts) > 4 && !isempty(texts[5]) ? texts[5] : missing
        push!(rows, (year = parse(Int, texts[1]), date_text = date_text, location = location, animal_type = animal, herds = herds, age = age, note = isempty(row_notes) ? missing : join(row_notes, "; ")))
    end
    isempty(rows) && changed(url, "the detection table is empty")
    return rows
end

function french_rows(url, file, english)
    french = try
        parse_detections(fetch_page(url, file), url)
    catch error
        println("$(url) could not be read ($(sprint(showerror, error))); labels stay in English, as the tool keeps them.")
        return nothing
    end
    if [row.year for row in french] != [row.year for row in english]
        println("$(url) does not have the same rows as the English page; labels stay in English, as the tool keeps them.")
        return nothing
    end
    return french
end

function detections_for(key, url_en, url_fr, file_en, file_fr)
    english = parse_detections(fetch_page(url_en, file_en), url_en)
    french = READ_FRENCH ? french_rows(url_fr, file_fr, english) : nothing
    labels = LANG == "fr" && french !== nothing ? french : english
    return [
        (
            disease_key = key,
            disease = DISEASE_LABELS[key],
            year = row.year,
            date_confirmed = parse_day_month(row.date_text, row.year),
            date_text = label.date_text,
            location = label.location,
            province_codes = join(province_codes_in(row.location), ","),
            animal_type = label.animal_type,
            herds = row.herds,
            age = label.age,
            note = label.note,
            animal_type_en = row.animal_type,
            animal_type_fr = french === nothing ? missing : french[i].animal_type,
        )
        for (i, (row, label)) in enumerate(zip(english, labels))
    ]
end

rows = reduce(vcat, [detections_for(page...) for page in PAGES])
data = frame(rows, [:disease_key, :disease, :year, :date_confirmed, :date_text, :location, :province_codes, :animal_type, :herds, :age, :note, :animal_type_en, :animal_type_fr])
"""


@dataclass
class _Detections:
    lang: str
    keys: list[str]
    read_french: bool
    year_from: int | None
    year_to: int | None
    province: str | None  # code
    animal: str | None  # folded
    counts_by: str | None


def _detection_file(key: str, lang: str) -> str:
    return f"cfia_{key}_{lang}.html"


def _detections_values(language: str, q: _Detections) -> dict[str, str]:
    years, dates, locations = cfia.DETECTION_COLUMNS
    labels = {k: cfia.disease_label(k, q.lang) for k in q.keys}
    pages = [
        (
            k,
            constants.DETECTION_PAGES[k]["en"],
            constants.DETECTION_PAGES[k]["fr"],
            _detection_file(k, "en"),
            _detection_file(k, "fr"),
        )
        for k in q.keys
    ]
    herds = cfia._HERDS.pattern
    if language == "python":
        return {
            "PAGES": "[\n" + "".join(f"    {p!r},\n" for p in pages) + "]",
            "LANG": repr(q.lang),
            "READ_FRENCH": repr(q.read_french),
            "DISEASE_LABELS": _py_dict(labels),
            "HERDS": repr(herds),
            "YEAR_HEADING": repr(cfia.YEAR_HEADING.pattern),
            "YEAR_COLUMN": repr(tuple(years)),
            "DATE_COLUMN": repr(dates),
            "LOCATION_COLUMN": repr(tuple(locations)),
        }
    if language == "r":
        fields = ("key", "url_en", "url_fr", "file_en", "file_fr")
        r_pages = ",\n".join(
            "  list("
            + ", ".join(f"{n} = {_r_str(v)}" for n, v in zip(fields, p, strict=True))
            + ")"
            for p in pages
        )
        return {
            "PAGES": f"list(\n{r_pages}\n)",
            "LANG": _r_str(q.lang),
            "READ_FRENCH": _r_value(q.read_french),
            "DISEASE_LABELS": _r_named(labels),
            "HERDS": _r_str(herds),
            "YEAR_HEADING": _r_str(_full(cfia.YEAR_HEADING.pattern)),
            "YEAR_COLUMN": _r_value(list(years)),
            "DATE_COLUMN": _r_str(dates),
            "LOCATION_COLUMN": _r_value(list(locations)),
        }
    jl_pages = "".join("    (" + ", ".join(_jl_str(v) for v in p) + "),\n" for p in pages)
    return {
        "PAGES": f"[\n{jl_pages}]",
        "LANG": _jl_str(q.lang),
        "READ_FRENCH": _jl_value(q.read_french),
        "DISEASE_LABELS": _jl_dict(labels),
        "HERDS": _jl_str(herds),
        "YEAR_HEADING": _jl_str(_full(cfia.YEAR_HEADING.pattern)),
        "YEAR_COLUMN": _jl_value(list(years)),
        "DATE_COLUMN": _jl_str(dates),
        "LOCATION_COLUMN": _jl_value(list(locations)),
    }


def _detections_steps(q: _Detections) -> list[str]:
    steps = ["Keep the rows cfia_disease_detections kept, in its order:"]
    if q.year_from is not None or q.year_to is not None:
        steps.append(f"- years {q.year_from or 'first'} to {q.year_to or 'last'};")
    if q.province:
        steps.append(f"- rows whose location names {q.province};")
    if q.animal:
        steps.append(
            "- an English or French animal type that holds ANIMAL, compared as fold() does;"
        )
    steps.append(
        "- newest confirmation first (a row without a readable day and month counts as "
        "January 1 of its year), ties by disease key, then page order."
    )
    if q.counts_by:
        order = "newest first" if q.counts_by in ("year", "month") else "most herds first"
        steps.append(
            f"Then the counts by {q.counts_by.replace('_', ' ')}: rows (detections) and herds "
            f"in each, {order}."
        )
    return steps


def _detections_py(q: _Detections, counts_file: str) -> str:
    out = _comment(_detections_steps(q)) + "\n"
    if q.year_from is not None:
        out += f'data = data.filter(pl.col("year") >= {q.year_from})\n'
    if q.year_to is not None:
        out += f'data = data.filter(pl.col("year") <= {q.year_to})\n'
    if q.province:
        out += (
            f'data = data.filter(pl.col("province_codes").str.split(",").list.contains'
            f"({q.province!r}))\n"
        )
    if q.animal:
        match = "map_elements(lambda text: ANIMAL in fold(text), return_dtype=pl.Boolean)"
        out += (
            f"ANIMAL = {q.animal!r}\n"
            f'data = data.filter(pl.col("animal_type_en").{match} | '
            f'pl.col("animal_type_fr").{match}.fill_null(False))\n'
        )
    out += (
        'data = data.sort([pl.coalesce("date_confirmed", pl.date(pl.col("year"), 1, 1)), '
        'pl.col("disease_key")], descending=True, maintain_order=True)\n'
    )
    if q.counts_by:
        key, label = {
            "year": ('pl.col("year").cast(pl.Utf8)', 'pl.col("year").cast(pl.Utf8)'),
            "month": (
                'pl.col("date_confirmed").dt.strftime("%Y-%m").fill_null(pl.col("year").cast(pl.Utf8))',
                'pl.col("date_confirmed").dt.strftime("%Y-%m").fill_null(pl.col("year").cast(pl.Utf8))',
            ),
            "province": (
                'pl.when(pl.col("key") == "").then(pl.lit("?")).otherwise(pl.col("key"))',
                (
                    'pl.when(pl.col("key") == "").then(pl.col("location")).otherwise(pl.col("key")'
                    '.replace_strict(PROVINCE_LABELS, default=pl.col("key")))'
                ),
            ),
            "animal_type": (
                'pl.col("animal_type").map_elements(fold, return_dtype=pl.Utf8)',
                'pl.col("animal_type")',
            ),
        }[q.counts_by]
        explode = (
            '    .with_columns(pl.col("province_codes").str.split(",").alias("key"))\n'
            '    .explode("key")\n'
            if q.counts_by == "province"
            else ""
        )
        sort = (
            '.sort("key", descending=True)'
            if q.counts_by in ("year", "month")
            else '.sort(["herds", "key"], descending=[True, False])'
        )
        out += (
            "\ncounts = (\n"
            "    data\n"
            f"{explode}"
            f'    .with_columns({key}.alias("key"), {label}.alias("label"))\n'
            '    .group_by("key", maintain_order=True)\n'
            '    .agg(pl.col("label").first(), pl.len().alias("detections"), pl.col("herds").sum())\n'
            f"    {sort}\n"
            ")\n"
            f'print(counts)\ncounts.write_csv(RAW_DIR / "{counts_file}.csv")\n'
        )
    out += 'data = data.drop("animal_type_en", "animal_type_fr")\n'
    return out


def _detections_r(q: _Detections) -> str:
    steps: list[str] = []
    if q.year_from is not None:
        steps.append(f"filter(year >= {q.year_from}L)")
    if q.year_to is not None:
        steps.append(f"filter(year <= {q.year_to}L)")
    if q.province:
        steps.append(
            'filter(vapply(str_split(province_codes, ","), \\(codes) '
            f"{_r_str(q.province)} %in% codes, logical(1)))"
        )
    if q.animal:
        needle = _r_str(q.animal)
        steps.append(
            f"filter(str_detect(fold(animal_type_en), fixed({needle})) | "
            f"coalesce(str_detect(fold(animal_type_fr), fixed({needle})), FALSE))"
        )
    steps.append(
        'arrange(desc(coalesce(date_confirmed, as.Date(str_c(year, "-01-01")))), desc(disease_key))'
    )
    out = _comment(_detections_steps(q)) + "\ndata <- data |>\n  " + " |>\n  ".join(steps) + "\n"
    if q.counts_by:
        key, label = {
            "year": ("as.character(year)", "key"),
            "month": (
                'if_else(is.na(date_confirmed), as.character(year), format(date_confirmed, "%Y-%m"))',
                "key",
            ),
            "province": (
                'if_else(key == "", "?", key)',
                'if_else(key == "", location, coalesce(unname(province_labels[key]), key))',
            ),
            "animal_type": ("fold(animal_type)", "animal_type"),
        }[q.counts_by]
        explode = (
            (
                '  mutate(key = str_split(province_codes, ",")) |>\n'
                "  unnest_longer(key) |>\n"
                "  mutate(key = as.character(key)) |>\n"
            )
            if q.counts_by == "province"
            else ""
        )
        # label is computed before key is replaced, as the tool labels "?" by location.
        mutate = f"  mutate(label = {label}, key = {key}) |>\n"
        if q.counts_by != "province":
            mutate = f"  mutate(key = {key}, label = {label}) |>\n"
        order = "desc(key)" if q.counts_by in ("year", "month") else "desc(herds), key"
        out += (
            "\ncounts <- data |>\n"
            f"{explode}{mutate}"
            "  group_by(key) |>\n"
            '  summarise(label = first(label), detections = n(), herds = sum(herds), .groups = "drop") |>\n'
            f"  arrange({order})\n"
            "print(counts)\n"
        )
    out += "data <- data |>\n  select(-animal_type_en, -animal_type_fr)\n"
    return out


def _detections_jl(q: _Detections) -> str:
    out = _comment(_detections_steps(q)) + "\n"
    if q.year_from is not None:
        out += f"data = filter(row -> row.year >= {q.year_from}, data)\n"
    if q.year_to is not None:
        out += f"data = filter(row -> row.year <= {q.year_to}, data)\n"
    if q.province:
        out += (
            f'data = filter(row -> {_jl_str(q.province)} in split(row.province_codes, ","), data)\n'
        )
    if q.animal:
        out += (
            f"const ANIMAL = {_jl_str(q.animal)}\n"
            "data = filter(row -> occursin(ANIMAL, fold(row.animal_type_en)) ||\n"
            "    (!ismissing(row.animal_type_fr) && occursin(ANIMAL, fold(row.animal_type_fr))), data)\n"
        )
    out += (
        "data.sort_date = coalesce.(data.date_confirmed, Date.(data.year, 1, 1))\n"
        "data = sort(data, [:sort_date, :disease_key]; rev = true, alg = MergeSort)\n"
        "select!(data, Not(:sort_date))\n"
    )
    if q.counts_by:
        key, label = {
            "year": ("string(row.year)", "string(row.year)"),
            "month": (
                'ismissing(row.date_confirmed) ? string(row.year) : Dates.format(row.date_confirmed, "yyyy-mm")',
                'ismissing(row.date_confirmed) ? string(row.year) : Dates.format(row.date_confirmed, "yyyy-mm")',
            ),
            "province": (
                'code == "" ? "?" : code',
                'code == "" ? row.location : get(PROVINCE_LABELS, code, code)',
            ),
            "animal_type": ("fold(row.animal_type)", "row.animal_type"),
        }[q.counts_by]
        source = (
            'row in eachrow(data), code in String.(split(row.province_codes, ","))'
            if q.counts_by == "province"
            else "row in eachrow(data)"
        )
        order = (
            "sort(counts, :key; rev = true)"
            if q.counts_by in ("year", "month")
            else "sort(counts, [order(:herds, rev = true), :key])"
        )
        out += (
            # Typed columns, so an empty result still has them.
            "\ngroups = DataFrame(key = String[], label = Union{Missing, String}[], herds = Int[])\n"
            f"for {source}\n"
            f"    push!(groups, (key = {key}, label = {label}, herds = row.herds))\n"
            "end\n"
            "counts = combine(\n"
            "    groupby(groups, :key; sort = false),\n"
            "    :label => first_or_missing => :label,\n"
            "    nrow => :detections,\n"
            "    :herds => sum => :herds,\n"
            ")\n"
            f"counts = {order}\n"
            "println(counts)\n"
        )
    out += "select!(data, Not([:animal_type_en, :animal_type_fr]))\n"
    return out


# cfia_avian_influenza --------------------------------------------------------------------

_PY_PREMISES = r"""
URL_EN = __URL_EN__
URL_FR = __URL_FR__
STATUS_URL = __STATUS_URL__
FILE_EN = __FILE_EN__
FILE_FR = __FILE_FR__
STATUS_FILE = __STATUS_FILE__
LANG = __LANG__
PREMISES_TABLE_ID = __TABLE_ID__
DATE_COLUMN = __DATE_COLUMN__
PROVINCE_COLUMN = __PROVINCE_COLUMN__
TYPE_COLUMN = __TYPE_COLUMN__
STATUS_FIRST_COLUMN = __STATUS_FIRST_COLUMN__
PREMISES_ID = re.compile(__PREMISES_ID__, re.IGNORECASE)
NOT_APPLICABLE = __NOT_APPLICABLE__
PREMISES_TYPES = __PREMISES_TYPES__
WOAH_CLASSES = __WOAH_CLASSES__
LOW_PATHOGENIC = __LOW_PATHOGENIC__
ORDER_PREFIXES = __ORDER_PREFIXES__
QUARANTINE_MARKER = __QUARANTINE_MARKER__
# Labels the tool writes for the known premises types and WOAH classes.
TYPE_LABELS = __TYPE_LABELS__
WOAH_LABELS = __WOAH_LABELS__


def not_applicable(text):
    return fold(text) in NOT_APPLICABLE


def premises_type(text):
    label = re.sub(r"\s*-\s*", "-", clean(text)).lower()
    if not label or not_applicable(label):
        return None, None
    compact = re.sub(r"[^a-z]", "", fold(label))
    for key, spellings in PREMISES_TYPES.items():
        if compact in spellings:
            return key, label
    return re.sub(r"[^a-z0-9]+", "_", fold(label)).strip("_"), label


def woah_class(text):
    label = clean(text)
    folded = fold(label)
    low = any(marker in folded for marker in LOW_PATHOGENIC)
    compact = re.sub(r"[^a-z]", "", folded)
    for key, spellings in WOAH_CLASSES.items():
        if compact in spellings:
            return key, label, low
    return None, label or None, low


def order_status(text):
    first = fold(text.split(";")[0])
    for key, prefixes in ORDER_PREFIXES.items():
        if first.startswith(prefixes):
            return key
    return None


def parse_premises(soup, url):
    main = main_element(soup, url)
    table = main.find("table", id=PREMISES_TABLE_ID)
    if table is None:
        table = next((t for t in main.find_all("table") if (header_cells(t) or [""])[0].startswith(DATE_COLUMN)), None)
    if table is None:
        changed(url, "no infected premises table")
    header = header_cells(table)
    if len(header) != 7 or not header[0].startswith(DATE_COLUMN) or header[2] != PROVINCE_COLUMN or not header[3].startswith(TYPE_COLUMN):
        changed(url, f"unexpected columns {header}")
    rows = []
    skipped = 0
    for tr in body_rows(table):
        cells = tr.find_all(["th", "td"], recursive=False)
        if len(cells) != 7:
            skipped += 1
            continue
        date_cell, id_cell = cells[0], cells[1]
        sort_key = str(date_cell.get("data-order", ""))
        detected = None
        sort_key_valid = False
        if re.fullmatch(r"\d{8}", sort_key):
            try:
                detected = date(int(sort_key[:4]), int(sort_key[4:6]), int(sort_key[6:]))
                sort_key_valid = True
            except ValueError:
                detected = None
        if detected is None:
            detected = parse_long_date(clean(date_cell.get_text(" ")))
        # Status markers first, then the hidden padding digit (BC-IP<span>0</span>99).
        current = any(QUARANTINE_MARKER in fold(span.get_text()) for span in id_cell.find_all(class_="invisible"))
        released = id_cell.find("a", class_="fn-lnk") is not None
        for node in id_cell.select(".invisible, a.fn-lnk"):
            node.decompose()
        for node in id_cell.select(".wb-inv"):
            node.decompose()
        text = clean(id_cell.get_text(" "))
        match = PREMISES_ID.match(text)
        if not match:
            skipped += 1
            continue
        prefix, digits = match.group(1).upper(), match.group(2)
        code = prefix if prefix in PROVINCES else (province_code(clean(cells[2].get_text(" "))) or prefix)
        type_key, type_label = premises_type(cells[3].get_text(" "))
        woah, woah_label, low = woah_class(cells[4].get_text(" "))
        zone = clean(cells[5].get_text(" "))
        order_lines = [clean(line) for line in cells[6].get_text("\n").split("\n") if clean(line)]
        order_text = "; ".join(order_lines)
        rows.append({
            "premises_id": f"{prefix}-IP{digits}",
            "province_code": code,
            "number": int(digits),
            "location": clean(text[match.end():]) or None,
            "date_detected": detected,
            "sort_key_valid": sort_key_valid,
            "status": "current" if current else ("released" if released else None),
            "premises_type": type_key,
            "premises_type_label": type_label,
            "woah_classification": woah,
            "woah_classification_label": woah_label,
            "low_pathogenic": low,
            "control_zone": None if not_applicable(zone) else zone,
            "control_zone_order": order_status(order_text),
            "control_zone_order_text": None if not_applicable(order_text) else order_text,
        })
    if not rows:
        changed(url, "the infected premises table is empty")
    # A few odd rows are left out with a message; many mean the layout moved.
    if skipped > max(5, int(len(rows) / 20)):
        changed(url, f"{skipped} rows could not be read")
    if skipped:
        print(f"{skipped} row(s) of {url} could not be read and are left out, as the tool leaves them out.")
    return rows


def french_premises():
    try:
        rows = parse_premises(fetch_page(URL_FR, FILE_FR), URL_FR)
    except (SystemExit, httpx.HTTPError) as error:
        print(f"{URL_FR} could not be read ({error}); labels stay in English, as the tool keeps them.")
        return {}
    return {(row["province_code"], row["number"]): row for row in rows}


def with_labels(english, french):
    out = []
    unmatched = differing = 0
    for row in english:
        labels = french.get((row["province_code"], row["number"]))
        type_label = TYPE_LABELS.get(row["premises_type"], row["premises_type_label"])
        woah_label = WOAH_LABELS.get(row["woah_classification"], row["woah_classification_label"])
        if labels is None:
            unmatched += 1 if french else 0
            labels = row
        else:
            differing += 1 if labels["date_detected"] != row["date_detected"] or not labels["sort_key_valid"] else 0
            type_label = type_label if row["premises_type"] in TYPE_LABELS else labels["premises_type_label"]
            woah_label = woah_label if row["woah_classification"] in WOAH_LABELS else labels["woah_classification_label"]
        out.append(dict(row, province=PROVINCE_LABELS.get(row["province_code"], row["province_code"]), location=labels["location"], control_zone=labels["control_zone"], control_zone_order_text=labels["control_zone_order_text"], premises_type_label=type_label, woah_classification_label=woah_label))
    if unmatched:
        print(f"{unmatched} premises are missing from the French page: English labels.")
    if differing:
        print(f"The French page gives another or a malformed date for {differing} premises; dates follow the English page.")
    return out


def parse_status(soup, url):
    main = main_element(soup, url)
    table = next((t for t in main.find_all("table") if (header_cells(t) or [""])[0] == STATUS_FIRST_COLUMN), None)
    if table is None:
        changed(url, "no status-by-province table")
    header = header_cells(table)
    if len(header) != 4:
        changed(url, f"unexpected columns {header}")
    as_of = ISO_DATE.search(header[3])
    print(f"Birds impacted as of {as_of.group(0) if as_of else None}.")
    rows = []
    for tr in table.find_all("tr"):
        cells = tr.find_all(["th", "td"])
        if len(cells) != 4 or not tr.find("td"):
            continue
        texts = [clean(cell.get_text(" ")) for cell in cells]
        code = "total" if fold(texts[0]) == "total" else province_code(texts[0])
        if code is None:
            changed(url, f"unknown province {texts[0]!r}")
        rows.append({"province_code": code, "province": texts[0], "current_premises": parse_int(texts[1]), "released_premises": parse_int(texts[2]), "birds_impacted": parse_int(texts[3]), "birds_impacted_text": texts[3]})
    if not any(row["province_code"] != "total" for row in rows):
        changed(url, "the status table is empty")
    return rows


def status_rows():
    try:
        return parse_status(fetch_page(STATUS_URL, STATUS_FILE), STATUS_URL)
    except (SystemExit, httpx.HTTPError) as error:
        print(f"The status-by-province table could not be read ({error}); the tool returns no summary then.")
        return []


SCHEMA = {"premises_id": pl.Utf8, "province_code": pl.Utf8, "number": pl.Int64, "location": pl.Utf8, "date_detected": pl.Date, "sort_key_valid": pl.Boolean, "status": pl.Utf8, "premises_type": pl.Utf8, "premises_type_label": pl.Utf8, "woah_classification": pl.Utf8, "woah_classification_label": pl.Utf8, "low_pathogenic": pl.Boolean, "control_zone": pl.Utf8, "control_zone_order": pl.Utf8, "control_zone_order_text": pl.Utf8, "province": pl.Utf8}
STATUS_SCHEMA = {"province_code": pl.Utf8, "province": pl.Utf8, "current_premises": pl.Int64, "released_premises": pl.Int64, "birds_impacted": pl.Int64, "birds_impacted_text": pl.Utf8}
english = parse_premises(fetch_page(URL_EN, FILE_EN), URL_EN)
french = french_premises() if LANG == "fr" else {}
data = pl.DataFrame(with_labels(english, french), schema=SCHEMA)
province_summary = pl.DataFrame(status_rows(), schema=STATUS_SCHEMA)
"""

_R_PREMISES = r"""
url_en <- __URL_EN__
url_fr <- __URL_FR__
status_url <- __STATUS_URL__
file_en <- __FILE_EN__
file_fr <- __FILE_FR__
status_file <- __STATUS_FILE__
lang <- __LANG__
premises_table_id <- __TABLE_ID__
date_column <- __DATE_COLUMN__
province_column <- __PROVINCE_COLUMN__
type_column <- __TYPE_COLUMN__
status_first_column <- __STATUS_FIRST_COLUMN__
premises_id_pattern <- regex(__PREMISES_ID__, ignore_case = TRUE)
not_applicable <- __NOT_APPLICABLE__
premises_types <- __PREMISES_TYPES__
woah_classes <- __WOAH_CLASSES__
low_pathogenic <- __LOW_PATHOGENIC__
order_prefixes <- __ORDER_PREFIXES__
quarantine_marker <- __QUARANTINE_MARKER__
# Labels the tool writes for the known premises types and WOAH classes.
type_labels <- __TYPE_LABELS__
woah_labels <- __WOAH_LABELS__

premises_type <- function(text) {
  label <- str_to_lower(str_replace_all(clean(text), "\\s*-\\s*", "-"))
  if (!nzchar(label) || fold(label) %in% not_applicable) return(c(NA_character_, NA_character_))
  compact <- str_remove_all(fold(label), "[^a-z]")
  for (key in names(premises_types)) {
    if (compact %in% premises_types[[key]]) return(c(key, label))
  }
  c(str_remove_all(str_replace_all(fold(label), "[^a-z0-9]+", "_"), "^_+|_+$"), label)
}

woah_class <- function(text) {
  label <- clean(text)
  folded <- fold(label)
  low <- any(str_detect(folded, fixed(low_pathogenic)))
  compact <- str_remove_all(folded, "[^a-z]")
  for (key in names(woah_classes)) {
    if (compact %in% woah_classes[[key]]) return(list(key = key, label = label, low = low))
  }
  list(key = NA_character_, label = na_if(label, ""), low = low)
}

order_status <- function(text) {
  first_line <- fold(str_split(text, ";")[[1]][1])
  for (key in names(order_prefixes)) {
    if (any(str_starts(first_line, fixed(order_prefixes[[key]])))) return(key)
  }
  NA_character_
}

parse_premises <- function(page, url) {
  main <- main_element(page, url)
  table <- xml_find_first(main, str_c(".//table[@id='", premises_table_id, "']"))
  if (inherits(table, "xml_missing")) {
    starts_with_date <- \(t) any(str_starts(c(header_cells(t), "")[1], fixed(date_column)))
    candidates <- Filter(starts_with_date, as.list(html_elements(main, "table")))
    if (length(candidates) == 0) changed(url, "no infected premises table")
    table <- candidates[[1]]
  }
  header <- header_cells(table)
  if (length(header) != 7 || !any(str_starts(header[1], fixed(date_column))) || header[3] != province_column || !any(str_starts(header[4], fixed(type_column)))) {
    changed(url, str_c("unexpected columns ", str_c(header, collapse = " | ")))
  }
  rows <- list()
  skipped <- 0
  for (tr in body_rows(table)) {
    cells <- xml_find_all(tr, "./th | ./td")
    if (length(cells) != 7) {
      skipped <- skipped + 1
      next
    }
    date_cell <- cells[[1]]
    id_cell <- cells[[2]]
    sort_key <- coalesce(xml_attr(date_cell, "data-order"), "")
    detected <- as.Date(NA)
    sort_key_valid <- FALSE
    if (str_detect(sort_key, "^\\d{8}$")) {
      detected <- as.Date(sort_key, format = "%Y%m%d")
      sort_key_valid <- !is.na(detected)
    }
    if (is.na(detected)) detected <- parse_long_date(clean(text_of(date_cell)))
    # Status markers first, then the hidden padding digit (BC-IP<span>0</span>99).
    current <- any(str_detect(fold(xml_text(html_elements(id_cell, ".invisible"))), fixed(quarantine_marker)))
    released <- length(html_elements(id_cell, "a.fn-lnk")) > 0
    xml_remove(html_elements(id_cell, ".invisible, a.fn-lnk"))
    xml_remove(html_elements(id_cell, ".wb-inv"))
    text <- clean(text_of(id_cell))
    id_match <- str_match(text, premises_id_pattern)
    if (is.na(id_match[1, 1])) {
      skipped <- skipped + 1
      next
    }
    prefix <- toupper(id_match[1, 2])
    digits <- id_match[1, 3]
    code <- if (prefix %in% names(provinces)) prefix else coalesce(province_code(clean(text_of(cells[[3]]))), prefix)
    type <- premises_type(text_of(cells[[4]]))
    woah <- woah_class(text_of(cells[[5]]))
    zone <- clean(text_of(cells[[6]]))
    order_lines <- clean(str_split(text_of(cells[[7]], separator = "\n"), "\n")[[1]])
    order_text <- str_c(order_lines[nzchar(order_lines)], collapse = "; ")
    rows[[length(rows) + 1]] <- list(
      premises_id = str_c(prefix, "-IP", digits),
      province_code = code,
      number = as.integer(digits),
      location = na_if(clean(str_sub(text, str_length(id_match[1, 1]) + 1)), ""),
      date_detected = detected,
      sort_key_valid = sort_key_valid,
      status = if (current) "current" else if (released) "released" else NA_character_,
      premises_type = type[1],
      premises_type_label = type[2],
      woah_classification = woah$key,
      woah_classification_label = woah$label,
      low_pathogenic = woah$low,
      control_zone = if (fold(zone) %in% not_applicable) NA_character_ else zone,
      control_zone_order = order_status(order_text),
      control_zone_order_text = if (fold(order_text) %in% not_applicable) NA_character_ else order_text
    )
  }
  if (length(rows) == 0) changed(url, "the infected premises table is empty")
  # A few odd rows are left out with a message; many mean the layout moved.
  if (skipped > max(5, length(rows) %/% 20)) changed(url, str_c(skipped, " rows could not be read"))
  if (skipped > 0) message(skipped, " row(s) of ", url, " could not be read and are left out, as the tool leaves them out.")
  bind_rows(rows)
}

french_premises <- function() {
  tryCatch(
    parse_premises(fetch_page(url_fr, file_fr), url_fr),
    error = \(error) {
      message(url_fr, " could not be read (", conditionMessage(error), "); labels stay in English, as the tool keeps them.")
      NULL
    }
  )
}

with_labels <- function(english, french) {
  known_type <- english$premises_type %in% names(type_labels)
  known_woah <- english$woah_classification %in% names(woah_labels)
  data <- english |>
    mutate(
      province = coalesce(unname(province_labels[province_code]), province_code),
      premises_type_label = if_else(known_type, unname(type_labels[premises_type]), premises_type_label),
      woah_classification_label = if_else(known_woah, unname(woah_labels[woah_classification]), woah_classification_label)
    )
  if (is.null(french)) return(data)
  labels <- french |>
    select(province_code, number, fr_location = location, fr_zone = control_zone,
           fr_order = control_zone_order_text, fr_type = premises_type_label,
           fr_woah = woah_classification_label, fr_date = date_detected, fr_valid = sort_key_valid)
  # A premises listed twice takes its last row, as the tool's dict does.
  labels <- labels[!duplicated(labels[c("province_code", "number")], fromLast = TRUE), ]
  joined <- left_join(data, labels, by = c("province_code", "number"))
  matched <- !is.na(joined$fr_valid)
  unmatched <- sum(!matched)
  differing <- sum(matched & (joined$fr_date != joined$date_detected | is.na(joined$fr_date) != is.na(joined$date_detected) | !joined$fr_valid), na.rm = TRUE)
  if (unmatched > 0) message(unmatched, " premises are missing from the French page: English labels.")
  if (differing > 0) message("The French page gives another or a malformed date for ", differing, " premises; dates follow the English page.")
  joined |>
    mutate(
      location = if_else(matched, fr_location, location),
      control_zone = if_else(matched, fr_zone, control_zone),
      control_zone_order_text = if_else(matched, fr_order, control_zone_order_text),
      premises_type_label = if_else(matched & !known_type, fr_type, premises_type_label),
      woah_classification_label = if_else(matched & !known_woah, fr_woah, woah_classification_label)
    ) |>
    select(-starts_with("fr_"))
}

parse_status <- function(page, url) {
  main <- main_element(page, url)
  table <- NULL
  for (candidate in html_elements(main, "table")) {
    if (identical(c(header_cells(candidate), "")[1], status_first_column)) {
      table <- candidate
      break
    }
  }
  if (is.null(table)) changed(url, "no status-by-province table")
  header <- header_cells(table)
  if (length(header) != 4) changed(url, str_c("unexpected columns ", str_c(header, collapse = " | ")))
  message("Birds impacted as of ", str_extract(header[4], "\\d{4}-\\d{2}-\\d{2}"), ".")
  rows <- list()
  for (tr in html_elements(table, "tr")) {
    cells <- html_elements(tr, "th, td")
    if (length(cells) != 4 || length(html_elements(tr, "td")) == 0) next
    texts <- vapply(cells, \(cell) clean(text_of(cell)), character(1))
    code <- if (fold(texts[1]) == "total") "total" else province_code(texts[1])
    if (is.na(code)) changed(url, str_c("unknown province ", texts[1]))
    rows[[length(rows) + 1]] <- list(
      province_code = code, province = texts[1], current_premises = parse_int(texts[2]),
      released_premises = parse_int(texts[3]), birds_impacted = parse_int(texts[4]),
      birds_impacted_text = texts[4]
    )
  }
  if (!any(vapply(rows, \(row) row$province_code != "total", logical(1)))) changed(url, "the status table is empty")
  bind_rows(rows)
}

english <- parse_premises(fetch_page(url_en, file_en), url_en)
french <- if (lang == "fr") french_premises() else NULL
data <- with_labels(english, french)
province_summary <- tryCatch(
  parse_status(fetch_page(status_url, status_file), status_url),
  error = \(error) {
    message("The status-by-province table could not be read (", conditionMessage(error), "); the tool returns no summary then.")
    tibble()
  }
)
"""

_JL_PREMISES = r"""
const URL_EN = __URL_EN__
const URL_FR = __URL_FR__
const STATUS_URL = __STATUS_URL__
const FILE_EN = __FILE_EN__
const FILE_FR = __FILE_FR__
const STATUS_FILE = __STATUS_FILE__
const LANG = __LANG__
const PREMISES_TABLE_ID = __TABLE_ID__
const DATE_COLUMN = __DATE_COLUMN__
const PROVINCE_COLUMN = __PROVINCE_COLUMN__
const TYPE_COLUMN = __TYPE_COLUMN__
const STATUS_FIRST_COLUMN = __STATUS_FIRST_COLUMN__
const PREMISES_ID = Regex(__PREMISES_ID__, "i")
const NOT_APPLICABLE = __NOT_APPLICABLE__
const PREMISES_TYPES = __PREMISES_TYPES__
const WOAH_CLASSES = __WOAH_CLASSES__
const LOW_PATHOGENIC = __LOW_PATHOGENIC__
const ORDER_PREFIXES = __ORDER_PREFIXES__
const QUARANTINE_MARKER = __QUARANTINE_MARKER__
# Labels the tool writes for the known premises types and WOAH classes.
const TYPE_LABELS = __TYPE_LABELS__
const WOAH_LABELS = __WOAH_LABELS__

not_applicable(text) = fold(text) in NOT_APPLICABLE

function premises_type(text)
    label = lowercase(replace(clean(text), r"\s*-\s*" => "-"))
    (isempty(label) || not_applicable(label)) && return (missing, missing)
    compact = replace(fold(label), r"[^a-z]" => "")
    for (key, spellings) in PREMISES_TYPES
        compact in spellings && return (key, label)
    end
    return (String(strip(replace(fold(label), r"[^a-z0-9]+" => "_"), '_')), label)
end

function woah_class(text)
    label = clean(text)
    folded = fold(label)
    low = any(marker -> occursin(marker, folded), LOW_PATHOGENIC)
    compact = replace(folded, r"[^a-z]" => "")
    for (key, spellings) in WOAH_CLASSES
        compact in spellings && return (key, label, low)
    end
    return (missing, isempty(label) ? missing : label, low)
end

function order_status(text)
    first_line = fold(first(split(text, ";")))
    for (key, prefixes) in ORDER_PREFIXES
        any(prefix -> startswith(first_line, prefix), prefixes) && return key
    end
    return missing
end

function parse_premises(root, url)
    main = main_element(root, url)
    tables = eachmatch(Selector("table"), main)
    at = findfirst(t -> get(attrs(t), "id", "") == PREMISES_TABLE_ID, tables)
    starts_with_date(t) = any(prefix -> startswith(first(vcat(header_cells(t), [""])), prefix), DATE_COLUMN)
    at === nothing && (at = findfirst(starts_with_date, tables))
    at === nothing && changed(url, "no infected premises table")
    table = tables[at]
    header = header_cells(table)
    if length(header) != 7 || !any(p -> startswith(header[1], p), DATE_COLUMN) || header[3] != PROVINCE_COLUMN || !any(p -> startswith(header[4], p), TYPE_COLUMN)
        changed(url, "unexpected columns $(join(header, " | "))")
    end
    rows = NamedTuple[]
    skipped = 0
    for tr in body_rows(table)
        cells = child_cells(tr)
        if length(cells) != 7
            skipped += 1
            continue
        end
        date_cell, id_cell = cells[1], cells[2]
        sort_key = get(attrs(date_cell), "data-order", "")
        detected = missing
        sort_key_valid = false
        if occursin(r"^\d{8}$", sort_key)
            parts = parse.(Int, (sort_key[1:4], sort_key[5:6], sort_key[7:8]))
            if Dates.validargs(Date, parts...) === nothing
                detected = Date(parts...)
                sort_key_valid = true
            end
        end
        ismissing(detected) && (detected = parse_long_date(clean(text_of(date_cell))))
        # Status markers first, then the hidden padding digit (BC-IP<span>0</span>99).
        current = any(span -> occursin(QUARANTINE_MARKER, fold(text_of(span; separator = ""))), eachmatch(Selector(".invisible"), id_cell))
        released = first_match(id_cell, "a.fn-lnk") !== nothing
        hidden = node -> has_class(node, "invisible") || is_note_link(node) || has_class(node, "wb-inv")
        text = clean(text_of(id_cell, hidden))
        found = match(PREMISES_ID, text)
        if found === nothing
            skipped += 1
            continue
        end
        prefix, digits = uppercase(found[1]), String(found[2])
        location = clean(text[ncodeunits(found.match)+1:end])
        code = prefix in PROVINCE_CODES ? prefix : coalesce(province_code(clean(text_of(cells[3]))), prefix)
        type_key, type_label = premises_type(text_of(cells[4]))
        woah, woah_label, low = woah_class(text_of(cells[5]))
        zone = clean(text_of(cells[6]))
        order_lines = filter(!isempty, [clean(line) for line in split(text_of(cells[7]; separator = "\n"), "\n")])
        order_text = join(order_lines, "; ")
        push!(rows, (
            premises_id = "$(prefix)-IP$(digits)",
            province_code = code,
            number = parse(Int, digits),
            location = isempty(location) ? missing : location,
            date_detected = detected,
            sort_key_valid = sort_key_valid,
            status = current ? "current" : released ? "released" : missing,
            premises_type = type_key,
            premises_type_label = type_label,
            woah_classification = woah,
            woah_classification_label = woah_label,
            low_pathogenic = low,
            control_zone = not_applicable(zone) ? missing : zone,
            control_zone_order = order_status(order_text),
            control_zone_order_text = not_applicable(order_text) ? missing : order_text,
        ))
    end
    isempty(rows) && changed(url, "the infected premises table is empty")
    # A few odd rows are left out with a message; many mean the layout moved.
    skipped > max(5, div(length(rows), 20)) && changed(url, "$(skipped) rows could not be read")
    skipped > 0 && println("$(skipped) row(s) of $(url) could not be read and are left out, as the tool leaves them out.")
    return rows
end

function french_premises()
    rows = try
        parse_premises(fetch_page(URL_FR, FILE_FR), URL_FR)
    catch error
        println("$(URL_FR) could not be read ($(sprint(showerror, error))); labels stay in English, as the tool keeps them.")
        return Dict()
    end
    return Dict((row.province_code, row.number) => row for row in rows)
end

function with_labels(english, french)
    out = NamedTuple[]
    unmatched = 0
    differing = 0
    for row in english
        labels = get(french, (row.province_code, row.number), nothing)
        type_label = get(TYPE_LABELS, coalesce(row.premises_type, ""), row.premises_type_label)
        woah_label = get(WOAH_LABELS, coalesce(row.woah_classification, ""), row.woah_classification_label)
        if labels === nothing
            unmatched += isempty(french) ? 0 : 1
            labels = row
        else
            same_date = !ismissing(labels.date_detected) && !ismissing(row.date_detected) && labels.date_detected == row.date_detected
            differing += (!same_date || !labels.sort_key_valid) ? 1 : 0
            haskey(TYPE_LABELS, coalesce(row.premises_type, "")) || (type_label = labels.premises_type_label)
            haskey(WOAH_LABELS, coalesce(row.woah_classification, "")) || (woah_label = labels.woah_classification_label)
        end
        push!(out, merge(row, (
            location = labels.location,
            control_zone = labels.control_zone,
            control_zone_order_text = labels.control_zone_order_text,
            premises_type_label = type_label,
            woah_classification_label = woah_label,
            province = get(PROVINCE_LABELS, row.province_code, row.province_code),
        )))
    end
    unmatched > 0 && println("$(unmatched) premises are missing from the French page: English labels.")
    differing > 0 && println("The French page gives another or a malformed date for $(differing) premises; dates follow the English page.")
    return out
end

function parse_status(root, url)
    main = main_element(root, url)
    tables = eachmatch(Selector("table"), main)
    at = findfirst(t -> first(vcat(header_cells(t), [""])) == STATUS_FIRST_COLUMN, tables)
    at === nothing && changed(url, "no status-by-province table")
    table = tables[at]
    header = header_cells(table)
    length(header) != 4 && changed(url, "unexpected columns $(join(header, " | "))")
    as_of = match(ISO_DATE, header[4])
    println("Birds impacted as of $(as_of === nothing ? missing : as_of.match).")
    rows = NamedTuple[]
    for tr in eachmatch(Selector("tr"), table)
        cells = eachmatch(Selector("th, td"), tr)
        (length(cells) != 4 || first_match(tr, "td") === nothing) && continue
        texts = [clean(text_of(cell)) for cell in cells]
        code = fold(texts[1]) == "total" ? "total" : province_code(texts[1])
        ismissing(code) && changed(url, "unknown province $(texts[1])")
        push!(rows, (province_code = code, province = texts[1], current_premises = parse_int(texts[2]), released_premises = parse_int(texts[3]), birds_impacted = parse_int(texts[4]), birds_impacted_text = texts[4]))
    end
    any(row -> row.province_code != "total", rows) || changed(url, "the status table is empty")
    return rows
end

const COLUMNS = [:premises_id, :province_code, :number, :location, :date_detected, :sort_key_valid, :status, :premises_type, :premises_type_label, :woah_classification, :woah_classification_label, :low_pathogenic, :control_zone, :control_zone_order, :control_zone_order_text, :province]
const STATUS_COLUMNS = [:province_code, :province, :current_premises, :released_premises, :birds_impacted, :birds_impacted_text]
english = parse_premises(fetch_page(URL_EN, FILE_EN), URL_EN)
french = LANG == "fr" ? french_premises() : Dict()
data = frame(with_labels(english, french), COLUMNS)
province_summary = try
    frame(parse_status(fetch_page(STATUS_URL, STATUS_FILE), STATUS_URL), STATUS_COLUMNS)
catch error
    println("The status-by-province table could not be read ($(sprint(showerror, error))); the tool returns no summary then.")
    DataFrame()
end
"""


@dataclass
class _Premises:
    lang: str
    status: str
    province: str | None
    start: date | None
    end: date | None
    premises_type: str | None
    counts_by: str
    limit: int


def _premises_values(language: str, q: _Premises) -> dict[str, str]:
    dates, province, types = cfia.PREMISES_COLUMNS
    type_labels = {k: v[q.lang == "fr"] for k, v in cfia._PREMISES_TYPE_LABELS.items()}
    woah_labels = {k: v[q.lang == "fr"] for k, v in cfia._WOAH_LABELS.items()}
    not_applicable = sorted(cfia._NOT_APPLICABLE)
    common = {
        "URL_EN": constants.HPAI_PREMISES_PAGE["en"],
        "URL_FR": constants.HPAI_PREMISES_PAGE["fr"],
        "STATUS_URL": constants.HPAI_STATUS_PAGE[q.lang],
        "FILE_EN": "cfia_hpai_premises_en.html",
        "FILE_FR": "cfia_hpai_premises_fr.html",
        "STATUS_FILE": f"cfia_hpai_status_{q.lang}.html",
        "LANG": q.lang,
        "TABLE_ID": cfia.PREMISES_TABLE_ID,
        "PROVINCE_COLUMN": province,
        "STATUS_FIRST_COLUMN": cfia.STATUS_FIRST_COLUMN,
        "PREMISES_ID": cfia._PREMISES_ID.pattern,
        "QUARANTINE_MARKER": cfia.QUARANTINE_MARKER,
    }
    if language == "python":
        values = {k: repr(v) for k, v in common.items()}
        values |= {
            "DATE_COLUMN": repr(tuple(dates)),
            "TYPE_COLUMN": repr(tuple(types)),
            "NOT_APPLICABLE": repr(tuple(not_applicable)),
            "PREMISES_TYPES": _py_dict(cfia.PREMISES_TYPES),
            "WOAH_CLASSES": _py_dict(cfia.WOAH_CLASSES),
            "LOW_PATHOGENIC": repr(tuple(cfia.LOW_PATHOGENIC)),
            "ORDER_PREFIXES": _py_dict(cfia.ORDER_PREFIXES),
            "TYPE_LABELS": _py_dict(type_labels),
            "WOAH_LABELS": _py_dict(woah_labels),
        }
        return values
    if language == "r":
        values = {k: _r_str(v) for k, v in common.items()}
        values |= {
            "DATE_COLUMN": _r_value(list(dates)),
            "TYPE_COLUMN": _r_value(list(types)),
            "NOT_APPLICABLE": _r_value(not_applicable),
            "PREMISES_TYPES": _r_named(dict(cfia.PREMISES_TYPES), as_list=True),
            "WOAH_CLASSES": _r_named(dict(cfia.WOAH_CLASSES), as_list=True),
            "LOW_PATHOGENIC": _r_value(list(cfia.LOW_PATHOGENIC)),
            "ORDER_PREFIXES": _r_named(dict(cfia.ORDER_PREFIXES), as_list=True),
            "TYPE_LABELS": _r_named(type_labels),
            "WOAH_LABELS": _r_named(woah_labels),
        }
        return values
    values = {k: _jl_str(v) for k, v in common.items()}
    values |= {
        "DATE_COLUMN": _jl_value(list(dates)),
        "TYPE_COLUMN": _jl_value(list(types)),
        "NOT_APPLICABLE": _jl_value(not_applicable),
        "PREMISES_TYPES": _jl_pairs(dict(cfia.PREMISES_TYPES)),
        "WOAH_CLASSES": _jl_pairs(dict(cfia.WOAH_CLASSES)),
        "LOW_PATHOGENIC": _jl_value(list(cfia.LOW_PATHOGENIC)),
        "ORDER_PREFIXES": _jl_pairs(dict(cfia.ORDER_PREFIXES)),
        "TYPE_LABELS": _jl_dict(type_labels),
        "WOAH_LABELS": _jl_dict(woah_labels),
    }
    return values


def _premises_steps(q: _Premises) -> list[str]:
    steps = ["Keep the premises cfia_avian_influenza kept, in its order:"]
    if q.status != "all":
        steps.append(f"- status {q.status};")
    if q.province:
        steps.append(f"- province {q.province};")
    if q.premises_type:
        steps.append(f"- premises type {q.premises_type};")
    if q.start or q.end:
        steps.append(
            f"- detected from {q.start or 'the first premises'} to {q.end or 'the latest'} "
            "(premises without a date are left out);"
        )
    steps.append("- newest detection first, ties by premises number, highest first.")
    order = "newest first" if q.counts_by in ("month", "year") else "largest total first"
    steps.append(
        f"Then the counts by {q.counts_by.replace('_', ' ')} of every kept premises "
        f"(current, released, total; {order}), and the first {q.limit} premises."
    )
    return steps


def _premises_py(q: _Premises, counts_file: str, summary_file: str) -> str:
    out = _comment(_premises_steps(q)) + "\n"
    if q.status != "all":
        out += f'data = data.filter(pl.col("status") == {q.status!r})\n'
    if q.province:
        out += f'data = data.filter(pl.col("province_code") == {q.province!r})\n'
    if q.premises_type:
        out += f'data = data.filter(pl.col("premises_type") == {q.premises_type!r})\n'
    for bound, symbol in ((q.start, ">="), (q.end, "<=")):
        if bound:
            out += (
                f'data = data.filter(pl.col("date_detected") {symbol} '
                f"date({bound.year}, {bound.month}, {bound.day}))\n"
            )
    out += (
        'data = data.sort([pl.col("date_detected").fill_null(date.min), pl.col("number")], '
        "descending=True, maintain_order=True)\n"
    )
    key, label = {
        "province": (
            'pl.col("province_code")',
            'pl.col("province_code").replace_strict(PROVINCE_LABELS, default=pl.col("province_code"))',
        ),
        "month": ('pl.col("date_detected").dt.strftime("%Y-%m").fill_null("unknown")', None),
        "year": ('pl.col("date_detected").dt.year().cast(pl.Utf8).fill_null("unknown")', None),
        "premises_type": (
            'pl.col("premises_type").fill_null("unknown")',
            'pl.coalesce("premises_type_label", pl.col("premises_type").fill_null("unknown"))',
        ),
    }[q.counts_by]
    sort = (
        '.sort("key", descending=True)'
        if q.counts_by in ("month", "year")
        else '.sort(["total", "key"], descending=[True, False])'
    )
    out += (
        "\ncounts = (\n"
        f'    data.with_columns({key}.alias("key"), {label or key}.alias("label"))\n'
        '    .group_by("key", maintain_order=True)\n'
        '    .agg(pl.col("label").first(), (pl.col("status") == "current").sum().alias("current"), '
        '(pl.col("status") == "released").sum().alias("released"), pl.len().alias("total"))\n'
        f"    {sort}\n"
        ")\n"
        f'print(counts)\ncounts.write_csv(RAW_DIR / "{counts_file}.csv")\n'
        "\n# The CFIA's status-by-province table, as published (not filtered).\n\n"
        f'print(province_summary)\nprovince_summary.write_csv(RAW_DIR / "{summary_file}.csv")\n'
        f'data = data.head({q.limit}).drop("number", "sort_key_valid")\n'
    )
    return out


def _premises_r(q: _Premises) -> str:
    steps: list[str] = []
    if q.status != "all":
        steps.append(f"filter(status == {_r_str(q.status)})")
    if q.province:
        steps.append(f"filter(province_code == {_r_str(q.province)})")
    if q.premises_type:
        steps.append(f"filter(premises_type == {_r_str(q.premises_type)})")
    if q.start:
        steps.append(f'filter(date_detected >= as.Date("{q.start}"))')
    if q.end:
        steps.append(f'filter(date_detected <= as.Date("{q.end}"))')
    steps.append('arrange(desc(coalesce(date_detected, as.Date("0001-01-01"))), desc(number))')
    out = _comment(_premises_steps(q)) + "\ndata <- data |>\n  " + " |>\n  ".join(steps) + "\n"
    key, label = {
        "province": (
            "province_code",
            "coalesce(unname(province_labels[province_code]), province_code)",
        ),
        "month": ('coalesce(format(date_detected, "%Y-%m"), "unknown")', "key"),
        "year": ('coalesce(format(date_detected, "%Y"), "unknown")', "key"),
        "premises_type": (
            'coalesce(premises_type, "unknown")',
            "coalesce(premises_type_label, key)",
        ),
    }[q.counts_by]
    order = "desc(key)" if q.counts_by in ("month", "year") else "desc(total), key"
    out += (
        "\ncounts <- data |>\n"
        f"  mutate(key = {key}, label = {label}) |>\n"
        "  group_by(key) |>\n"
        "  summarise(\n"
        "    label = first(label),\n"
        '    current = sum(status %in% "current"),\n'
        '    released = sum(status %in% "released"),\n'
        "    total = n(),\n"
        '    .groups = "drop"\n'
        "  ) |>\n"
        f"  arrange({order})\n"
        "print(counts)\n"
        "\n# The CFIA's status-by-province table, as published (not filtered).\n\n"
        "print(province_summary)\n"
        f"data <- data |>\n  slice_head(n = {q.limit}) |>\n  select(-number, -sort_key_valid)\n"
    )
    return out


def _premises_jl(q: _Premises) -> str:
    out = _comment(_premises_steps(q)) + "\n"
    if q.status != "all":
        out += f"data = filter(row -> coalesce(row.status == {_jl_str(q.status)}, false), data)\n"
    if q.province:
        out += f"data = filter(row -> row.province_code == {_jl_str(q.province)}, data)\n"
    if q.premises_type:
        out += (
            f"data = filter(row -> coalesce(row.premises_type == {_jl_str(q.premises_type)}, "
            "false), data)\n"
        )
    for bound, symbol in ((q.start, ">="), (q.end, "<=")):
        if bound:
            out += (
                "data = filter(row -> !ismissing(row.date_detected) && "
                f"row.date_detected {symbol} Date({bound.year}, {bound.month}, {bound.day}), data)\n"
            )
    out += (
        "data.sort_date = coalesce.(data.date_detected, Date(1))\n"
        "data = sort(data, [:sort_date, :number]; rev = true, alg = MergeSort)\n"
        "select!(data, Not(:sort_date))\n"
    )
    key, label = {
        "province": (
            "row.province_code",
            "get(PROVINCE_LABELS, row.province_code, row.province_code)",
        ),
        "month": (
            'ismissing(row.date_detected) ? "unknown" : Dates.format(row.date_detected, "yyyy-mm")',
            None,
        ),
        "year": (
            'ismissing(row.date_detected) ? "unknown" : string(year(row.date_detected))',
            None,
        ),
        "premises_type": (
            'coalesce(row.premises_type, "unknown")',
            'coalesce(row.premises_type_label, row.premises_type, "unknown")',
        ),
    }[q.counts_by]
    order = (
        "sort(counts, :key; rev = true)"
        if q.counts_by in ("month", "year")
        else "sort(counts, [order(:total, rev = true), :key])"
    )
    out += (
        "\ngroups = DataFrame(key = String[], label = Union{Missing, String}[], "
        "status = Union{Missing, String}[])\n"
        "for row in eachrow(data)\n"
        f"    push!(groups, (key = {key}, label = {label or key}, status = row.status))\n"
        "end\n"
        "counts = combine(\n"
        "    groupby(groups, :key; sort = false),\n"
        "    :label => first_or_missing => :label,\n"
        '    :status => (s -> count(isequal("current"), s)) => :current,\n'
        '    :status => (s -> count(isequal("released"), s)) => :released,\n'
        "    nrow => :total,\n"
        ")\n"
        f"counts = {order}\n"
        "println(counts)\n"
        "\n# The CFIA's status-by-province table, as published (not filtered).\n\n"
        "println(province_summary)\n"
        f"data = first(data, {q.limit})\n"
        "select!(data, Not([:number, :sort_key_valid]))\n"
    )
    return out


# Spec -------------------------------------------------------------------------------------

_LAYOUT_NOTE = (
    "The script stops, as the tool raises UpstreamError, when a page no longer has the "
    "structure the tool checks for: no <main>, a missing table, other column headers, a "
    "year table outside a year heading, an unreadable count, many unreadable rows."
)


def _read_code(prefix_lines: list[str], helpers: str, body: str) -> str:
    return _comment(prefix_lines) + "\n" + helpers + body


def _spec(
    plan: _Plan,
    *,
    title: str,
    reads: dict[str, str],
    prepares: dict[str, str],
    frames: list[tuple[str, str, str]],
    r_packages: list[str],
) -> Spec:
    main = plan.pages[0]
    stata = ""
    for frame_name, file, description in frames:
        stata += (
            f"* {description}, written by the Python block above.\n\n"
            f"frame create {frame_name}\n"
            f'frame {frame_name}: import delimited "data/raw/{file}.csv", clear varnames(1) '
            'encoding("utf-8")\n'
            f"frame {frame_name}: list, clean noobs\n\n"
        )
    return Spec(
        kind="html_table",
        url=main.url,
        file_name=main.file,
        method=_METHOD,
        title=f"CFIA: {title}",
        details=_details(plan),
        native={
            "python": Code(list(_PY_IMPORTS), reads["python"]),
            "r": Code([*_R_PACKAGES, *r_packages], reads["r"]),
            "julia": Code(list(_JL_PACKAGES), reads["julia"]),
        },
        prepare={
            "python": Code([], prepares["python"]),
            "r": Code(["dplyr", "stringr", *r_packages], prepares["r"]),
            "julia": Code(["DataFrames"], prepares["julia"]),
            **({"stata": Code([], stata)} if stata else {}),
        },
        notes=plan.notes,
    )


async def reportable(args: dict[str, Any], result: dict[str, Any]) -> Spec:
    lang = _lang(args)
    year_from, year_to = _int(args, "year_from"), _int(args, "year_to")
    disease, totals_by = _text(args, "disease"), _text(args, "totals_by")
    # The tool validates every argument; running it here raises the same
    # InvalidInput and gives the counts for the notes.
    tool = await cfia.get_reportable_diseases(year_from, year_to, disease, totals_by, lang)
    url = constants.REPORTABLE_PAGE[lang]
    file = f"cfia_reportable_{lang}.html"
    plan = _Plan(
        "cfia_reportable_diseases",
        lang,
        _shown(args, ("year_from", "year_to", "disease", "totals_by"), lang),
    )
    plan.pages.append(
        await _page(
            "reportable",
            url,
            constants.REPORTABLE_TTL_SECONDS,
            cfia.parse_reportable_page,
            file,
            "yearly counts and labels",
        )
    )
    folded = cfia._fold(disease) if disease else ""
    q = _Reportable(
        lang=lang,
        year_from=year_from,
        year_to=year_to,
        keys=sorted(cfia.match_diseases(disease)) if disease else None,
        name_query=folded if len(folded) >= 3 else None,
        totals_by=totals_by,
    )
    totals_file = "cfia_reportable_diseases_totals"
    intro = [
        (
            'The tool reads the yearly counts page in the chosen language (for lang="fr" '
            "the French page, whose counts equal the English page's for every year and "
            "disease), so this script reads the same page: every year table, each count "
            "and its table note, keyed by disease as the tool keys it."
        ),
        _LAYOUT_NOTE,
    ]
    reads, prepares = {}, {}
    for language, template, prepare in (
        ("python", _PY_REPORTABLE, _reportable_py(q, totals_file)),
        ("r", _R_REPORTABLE, _reportable_r(q)),
        ("julia", _JL_REPORTABLE, _reportable_jl(q)),
    ):
        body = _fill(template, **_reportable_values(language, url, file))
        helpers = _helpers(language, lang, dates=False, ints=True)
        reads[language] = _read_code(intro, helpers, body)
        prepares[language] = prepare
    plan.notes += [
        (
            f"The tool returned {tool.row_count} rows ({tool.year_from}-{tool.year_to}); the "
            "scripts parse all year tables on the page and repeat its year range, disease "
            "match (folded for case, accents and apostrophes, with the abbreviations and "
            "other names in constants.DISEASES), order"
            + (f" and totals by {totals_by}." if totals_by else ".")
        ),
        (
            "Canada.ca terms allow non-commercial reproduction that credits the title, the "
            "author (Canadian Food Inspection Agency) and the source URL; each script's "
            "header and output name them."
        ),
    ]
    frames = [("totals", totals_file, "The totals the tool returns")] if totals_by else []
    return _spec(
        plan,
        title=plan.pages[0].title or "Federally reportable diseases",
        reads=reads,
        prepares=prepares,
        frames=frames,
        r_packages=[],
    )


async def detections(args: dict[str, Any], result: dict[str, Any]) -> Spec:
    lang = _lang(args)
    disease = _text(args, "disease")
    year_from, year_to = _int(args, "year_from"), _int(args, "year_to")
    province, animal_type = _text(args, "province"), _text(args, "animal_type")
    counts_by = _text(args, "counts_by")
    tool = await cfia.get_disease_detections(
        disease, year_from, year_to, province, animal_type, counts_by, lang
    )
    q = _Detections(
        lang=lang,
        keys=list(tool.diseases),
        read_french=lang == "fr" or bool(animal_type),
        year_from=year_from,
        year_to=year_to,
        province=cfia.province_code(province) if province else None,
        animal=cfia._fold(animal_type) if animal_type else None,
        counts_by=counts_by,
    )
    plan = _Plan(
        "cfia_disease_detections",
        lang,
        _shown(
            args,
            ("disease", "year_from", "year_to", "province", "animal_type", "counts_by"),
            lang,
        ),
    )
    for key in q.keys:
        urls = constants.DETECTION_PAGES[key]
        english_role = "dates, counts and provinces" + ("" if lang == "fr" else " and labels")
        plan.pages.append(
            await _page(
                "detections",
                urls["en"],
                constants.DETECTION_TTL_SECONDS,
                cfia.parse_detection_page,
                _detection_file(key, "en"),
                english_role,
            )
        )
        if q.read_french:
            role = "labels" if lang == "fr" else "French animal types, for the animal filter"
            plan.pages.append(
                await _page(
                    "detections",
                    urls["fr"],
                    constants.DETECTION_TTL_SECONDS,
                    cfia.parse_detection_page,
                    _detection_file(key, "fr"),
                    role,
                )
            )
    intro = []
    if lang == "fr":
        intro.append(
            _LANGUAGE_NOTE + "paired row by row only when every row's year lines up with "
            "the English page; otherwise the labels stay in English, as the tool keeps them."
        )
    elif q.read_french:
        intro.append(
            "The French pages are read too because the tool matches animal_type against "
            'the English and the French animal names ("elk" or "wapiti"); dates, counts '
            "and labels come from the English pages."
        )
    intro.append(_LAYOUT_NOTE)
    counts_file = "cfia_disease_detections_counts"
    reads, prepares = {}, {}
    for language, template, prepare in (
        ("python", _PY_DETECTIONS, _detections_py(q, counts_file)),
        ("r", _R_DETECTIONS, _detections_r(q)),
        ("julia", _JL_DETECTIONS, _detections_jl(q)),
    ):
        body = _fill(template, **_detections_values(language, q))
        helpers = _helpers(language, lang, dates=True, ints=False)
        reads[language] = _read_code(intro, helpers, body)
        prepares[language] = prepare
    plan.notes += [
        (
            f"The tool returned {tool.row_count} detections ({tool.herd_count} herds) from "
            f"{len(q.keys)} disease page(s); the scripts parse the same pages as the tool "
            "does (herd counts such as 'Elk (3 herds)', day and month read with the row's "
            "year, provinces named in the location, BSE's age) and repeat its filters, order"
            + (f" and counts by {counts_by}." if counts_by else ".")
        ),
        "Province codes are one text column, comma-separated ('AB,SK'), in every language.",
    ]
    if lang == "fr":
        plan.notes.append(
            "Dates, years, herds and provinces come from the English pages and labels from "
            "the French pages, as the tool does, because the French pages hold data errors."
        )
    frames = [("counts", counts_file, "The counts the tool returns")] if counts_by else []
    title = plan.pages[0].title or "Detections of reportable diseases"
    if len(q.keys) > 1:
        title = f"detections on {len(q.keys)} disease pages"
    return _spec(
        plan,
        title=title,
        reads=reads,
        prepares=prepares,
        frames=frames,
        r_packages=["tidyr"] if counts_by == "province" else [],
    )


async def avian_influenza(args: dict[str, Any], result: dict[str, Any]) -> Spec:
    lang = _lang(args)
    status = _text(args, "status") or "all"
    province = _text(args, "province")
    date_from, date_to = _text(args, "date_from"), _text(args, "date_to")
    premises_type = _text(args, "premises_type")
    counts_by = _text(args, "counts_by") or "province"
    limit = _int(args, "limit")
    limit = constants.HPAI_DEFAULT_LIMIT if limit is None else limit
    tool = await cfia.get_avian_influenza(
        status, province, date_from, date_to, premises_type, counts_by, limit, lang
    )
    q = _Premises(
        lang=lang,
        status=status,
        province=cfia.province_code(province) if province else None,
        start=cfia.parse_period(date_from, end=False, lang=lang) if date_from else None,
        end=cfia.parse_period(date_to, end=True, lang=lang) if date_to else None,
        premises_type=cfia.normalize_premises_type(premises_type)[0] if premises_type else None,
        counts_by=counts_by,
        limit=limit,
    )
    plan = _Plan(
        "cfia_avian_influenza",
        lang,
        _shown(
            args,
            (
                "status",
                "province",
                "date_from",
                "date_to",
                "premises_type",
                "counts_by",
                "limit",
            ),
            lang,
        ),
    )
    ttl = constants.HPAI_TTL_SECONDS
    plan.pages.append(
        await _page(
            "premises",
            constants.HPAI_PREMISES_PAGE["en"],
            ttl,
            cfia.parse_premises_page,
            "cfia_hpai_premises_en.html",
            "dates and statuses" + (" and labels" if lang == "en" else ""),
        )
    )
    if lang == "fr":
        plan.pages.append(
            await _page(
                "premises",
                constants.HPAI_PREMISES_PAGE["fr"],
                ttl,
                cfia.parse_premises_page,
                "cfia_hpai_premises_fr.html",
                "labels (municipality, control zone, order)",
            )
        )
    plan.pages.append(
        await _page(
            "status",
            constants.HPAI_STATUS_PAGE[lang],
            ttl,
            cfia.parse_status_page,
            f"cfia_hpai_status_{lang}.html",
            "status by province, as the tool returns it",
        )
    )
    intro = []
    if lang == "fr":
        intro.append(
            _LANGUAGE_NOTE + "joined by premises id (province code and number), as the tool "
            "joins them. The status-by-province table comes from the French status page, "
            "as the tool reads it."
        )
    intro.append(_LAYOUT_NOTE)
    counts_file = "cfia_avian_influenza_counts"
    summary_file = "cfia_avian_influenza_province_summary"
    reads, prepares = {}, {}
    for language, template, prepare in (
        ("python", _PY_PREMISES, _premises_py(q, counts_file, summary_file)),
        ("r", _R_PREMISES, _premises_r(q)),
        ("julia", _JL_PREMISES, _premises_jl(q)),
    ):
        body = _fill(template, **_premises_values(language, q))
        helpers = _helpers(language, lang, dates=True, ints=True)
        reads[language] = _read_code(intro, helpers, body)
        prepares[language] = prepare
    plan.notes += [
        (
            f"The tool matched {tool.total_matched} premises and returned {tool.returned_count}; "
            "the scripts parse the investigations-and-orders table as the tool does (hidden "
            "padding digits, quarantine and released markers, premises type, WOAH class, "
            "control zone and order) and repeat its filters, newest-first order, counts by "
            f"{counts_by} and limit of {limit}, and read the status-by-province table."
        ),
    ]
    if lang == "fr":
        plan.notes.append(
            "Dates and statuses come from the English page and labels from the French page, "
            "joined by premises id, as the tool does, because the French page gives six "
            "premises another detection date."
        )
    frames = [
        ("counts", counts_file, "The counts the tool returns"),
        ("province_summary", summary_file, "The CFIA's status-by-province table"),
    ]
    return _spec(
        plan,
        title=plan.pages[0].title or "Avian influenza infected premises",
        reads=reads,
        prepares=prepares,
        frames=frames,
        r_packages=["tibble"],
    )
