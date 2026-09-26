# Competition Bureau Canada

Checked 2026-09-25. Status: investigated, worth building (merger reviews).

## What is on open.canada.ca

Almost nothing. The only Bureau entry is "Monthly report of concluded
merger reviews", published by ISED (`ic`), with a single HTML link to the
report page and no data file. Last modified 2023-07-11.

## Merger reviews: the usable data

Two pages on competition-bureau.canada.ca carry the full record as plain
HTML tables (no script loads them, no pagination):

- **Report of merger reviews**
  (`/en/mergers-and-acquisitions/report-concluded-merger-reviews`): about
  830 reviews opened since November 2023, ongoing and concluded, updated
  weekly (on or after each Tuesday, for reviews started or finished the
  previous week). Columns: parties to the transaction, opened date,
  concluded date (or "Ongoing"), industry (NAICS code), outcome.
- **Archived report of merger reviews**
  (`/en/mergers-and-acquisitions/archived-report-merger-reviews`): about
  1,725 concluded reviews from January 2015 to April 2023, monthly.
  Columns: parties, industry (NAICS), result, month (`YYYY-MM`).

The report covers transactions with a pre-merger notification (section
114 of the Competition Act), a request for an advance ruling certificate
(section 102), and non-notifiable transactions with a reasonable
prospect of concern. Parties can ask to delay or omit publication, so
the list is not every merger.

Outcome codes, from the page's own legend:

| Code | Meaning | Current report | Archive |
|---|---|---|---|
| NAL | No action letter | 413 | 848 |
| ARC | Advance ruling certificate (s. 102) | 322 | 833 |
| CA | Consent agreement registered | 13 | 40 |
| JD | Judicial decision | 1 | 3 |
| TA | Transaction abandoned by the parties | 5 | 0 |
| Other | Other | 31 | 1 |
| Ongoing | Review not concluded | 46 | 0 |

Counts are as of 2026-09-22 (current) and 2024-04-16 (archive, the
page's last modification). The gap between April and November 2023 is
not covered by either page.

## What is not usable

- **Competition Tribunal** (ct-tc.gc.ca): the "All cases" page loads its
  list with a script, and the decisions site
  (decisions.ct-tc.gc.ca) answers HTTP 403 to automated requests.
- **Enforcement actions, market studies and guidance** are news releases
  and PDF reports, not data.

## If built

One tool, `competition_bureau_search_mergers`, over both tables: search
by party name, NAICS prefix (e.g. `2111` for oil and gas extraction),
outcome and date range, with the outcome legend in the result. The
tables are small (under 0.5 MB together), so the tool reads both pages
and filters in memory; a cache of a few hours matches the weekly update.
NAICS codes can be joined to StatCan industry data through `rdaas_*`.
`reproduce_code` already reads HTML tables, and needs a builder only to
repeat the tool's filters.
