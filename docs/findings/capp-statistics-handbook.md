# CAPP Statistics Handbook

Checked 2026-09-25. Status: investigated, not built (deferred).

## What it is

The Canadian Association of Petroleum Producers publishes its
[Statistics Handbook](https://www.capp.ca/en/resources-news/capp-stats-handbook/)
each December; the current edition covers 2024. It is an industry
association source, not a government one, compiled by CAPP from several
third-party sources.

## What is machine-readable

76 Excel tables, one file each, linked from the handbook page under
`https://www.capp.ca/wp-content/uploads/<year>/<month>/`, in 8 chapters:

| Chapter | Tables | Examples |
|---|---|---|
| 01 | 8 | industry overview |
| 02 | 15 | remaining and initial reserves: crude oil, oil sands, gas, NGL, sulphur |
| 03 | 17 | production, including production by field, sulphur sales and inventory |
| 04 | 22 | value of producer sales by province (from 1947), net cash expenditures by province |
| 05 | 5 | |
| 06 | 4 | natural gas sales, fuel demand, sources of energy consumption |
| 07 | 3 | |
| 08 | 3 | |

A PDF of the whole handbook and a "Frequently Used Statistics" PDF sit
alongside. The CAPP Data Centre page adds no other data files.

## Table layout

Checked on `04-23-Value-of-Producer-Sales-Canada.xlsx`: one sheet with a
title row, a period row ("1947 - 2024"), a units row ("Thousand
Dollars"), a geography row, then column headers split across two rows
("Crude Oil &" / "Condensate"), then one row per year. Cells are empty
where a series had not started. Parsing needs to join the two header
rows and read the units row.

## Terms of use

From the handbook page's "Copyright and Data Use" note: the content is
CAPP's copyright; use is allowed with attribution naming the material,
"© Canadian Association of Petroleum Producers", the year and the page
number or URL. CAPP gives no warranty of accuracy. The page shows an
"I acknowledge" disclaimer overlay, but the Excel files download
directly.

## If built

Two tools: `capp_list_tables` (the 76 tables from the handbook page)
and `capp_get_table` (one table as tidy rows: year, series, value,
unit), each result carrying the attribution CAPP asks for, plus a
`reproduce_code` builder for the Excel parse.
