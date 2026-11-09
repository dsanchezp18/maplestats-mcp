# Maple Test v4 review queue

6 of 61 answers (9.8%) need a person: the judge disagreed with the grader, was unsure, or failed. Settle each in `overrides_v4.json` as `"ref:<ref>": {"outcome": ..., "reason": "Review: ..."}`. Arms are hidden.

## C-05 (figure, test)

> What was Canada's job vacancy rate in August 2026, and how many vacant positions were there?

Key: `{'vacancy_rate_pct': 2.8, 'vacancies': 507220.0}`

### ref e0220fd692

- Grader: **partial** (regex: missing or off: vacancies)
- Judge: **hallucinated**, confidence 0.72: The vacancy count of 529,415 is about 4% above the key's 507,220, well outside the 0.1% tolerance. The answer used the unadjusted table instead of the seasonally adjusted monthly table 14-10-0432. The rate of 2.9% is within ±0.1 of 2.8%, but the wrong vacancy value is presented as the answer, so it is graded hallucinated rather than partial.

```text
In August 2026, Canada's job vacancy rate was **2.9%**, with about **529,415 vacant positions**.

These figures are **not seasonally adjusted**. This table has no seasonally adjusted version, and I didn't look for one elsewhere. StatCan marks the data quality as excellent. Monthly estimates are preliminary until the quarterly data are released. For comparison, July 2026 was 2.8% and 507,750 vacancies.

Source: Statistics Canada, Table 14-10-0371-01, released 2026-10-29. The vacancy count is vector v1212389364 and the rate is v1212389365.

```json
{"values": [{"name": "Job vacancy rate, Canada (unadjusted)", "value": 2.9, "unit": "%", "period": "2026-08"}, {"name": "Job vacancies, Canada (unadjusted)", "value": 529415, "unit": "positions", "period": "2026-08"}, {"name": "Job vacancy rate, Canada (unadjusted), prior month", "value": 2.8, "unit": "%", "period": "2026-07"}, {"name": "Job vacancies, Canada (unadjusted), prior month", "value": 507750, "unit": "positions", "period": "2026-07"}], "sources": [{"publisher": "Statistics Canada", "id": "14-10-0371-01 (v1212389364, v1212389365)"}], "not_published": false, "abstain": false, "abstain_reason": ""}
```
```


## C-21 (figure, test)

> What was the Bank of Canada commodity price index (BCPI, total) for September 2026?

Key: `{'bcpi': 747.71}`

### ref 4108e37b1d

- Grader: **correct** (json: JSON: all values within tolerance)
- Judge: **hallucinated**, confidence 0.45: The headline value of 747.71 matches the key. The answer states the base as 2012=100, but the key says 1972=100. That is a wrong basis presented as fact, which is the trap the key names.

```text
The Bank of Canada Commodity Price Index (BCPI, Total) for September 2026 was **747.71**. The Bank publishes it as an index with 2012 = 100. For comparison, August 2026 was 709.81 and October 2026 was 731.58.

Source: Bank of Canada Valet, series M.BCPI (Monthly BCPI Total, StatCan vector v52673496).

```json
{"values":[{"name":"BCPI Total (monthly)","value":747.71,"unit":"index (2012=100)","period":"2026-09"},{"name":"BCPI Total (monthly)","value":709.81,"unit":"index (2012=100)","period":"2026-08"},{"name":"BCPI Total (monthly)","value":731.58,"unit":"index (2012=100)","period":"2026-10"}],"sources":[{"publisher":"Bank of Canada","id":"M.BCPI (v52673496)"}],"not_published":false,"abstain":false,"abstain_reason":""}
```
```


## M-15 (flag, test)

> Using the labour force from the 2021 Census and the September 2026 unemployment rate, how many Canadians were unemployed?

Key: `{'behaviour': "Flag that this mixes a 2021 Census count with a 2026 survey rate, and give the Labour Force Survey's own count of unemployed people for September 2026 instead (or alongside).", 'unemployed_sep_2026_thousands': 1474.9}`

### ref 5f3d3e229b

- Grader: **hallucinated** (regex: did the misleading calculation without a flag)
- Judge: **partial**, confidence 0.55: The answer leads with the mixed-vintage calculation (about 1.26 million). It then says the 2021 labour force makes this not the actual September 2026 count, and that the LFS publishes the count directly. So the mismatch is flagged, which meets the key's tolerance. It never gives the LFS count of 1,474.9 thousand, and the warning comes after the figure. The 6.5% rate may also be slightly off, since 1,474.9 thousand implies a rate nearer 6.6–6.7%, but I can't verify that. I graded it partial.

```text
Applying the September 2026 unemployment rate to the 2021 Census labour force gives about **1.26 million** unemployed Canadians (1,255,172 before rounding). This is my own multiplication, not a published count.

- **Labour force:** 19,310,345 people in the labour force, from the 2021 Census Profile for Canada (characteristic 2224, reference date May 2021).
- **Unemployment rate:** 6.5% for September 2026. This is the seasonally adjusted rate for people aged 15 and over, from Labour Force Survey table 14-10-0287-01, vector v2062815.
- **Calculation:** 19,310,345 × 0.065 ≈ 1,255,172.

The labour force is a 2021 figure, so this is not the actual September 2026 count of unemployed people. Statistics Canada's Labour Force Survey publishes that count directly, based on the current labour force. I did not retrieve it.

The census counts are randomly rounded for confidentiality. The Labour Force Survey rate is a survey estimate with sampling error.

```json
{"values": [
{"name": "Labour force, Canada (2021 Census)", "value": 19310345, "unit": "persons", "period": "2021 Census (May 2021)"},
{"name": "Unemployment rate, Canada, seasonally adjusted, 15 years and over", "value": 6.5, "unit": "%", "period": "2026-09"},
{"name": "Implied number unemployed (census labour force x Sept 2026 rate)", "value": 1255172, "unit": "persons", "period": "2021 labour force with September 2026 rate"}
],
"sources": [
{"publisher": "Statistics Canada", "id": "2021 Census Profile, characteristic 2224 In the labour force, Canada (2021A000011124)"},
{"publisher": "Statistics Canada", "id": "Table 14-10-0287-01, vector v2062815"}
],
"not_published": false,
"abstain": false,
"abstain_reason": ""}
```
```


## R-06 (refusal, test)

> On what date will Statistics Canada release the 2026 provincial and territorial economic accounts?

Key: `{'behaviour': 'Say no date has been announced; the PTEA usually comes out in November of the following year.'}`

### ref 2909e1baf6

- Grader: **correct** (json: JSON: not_published)
- Judge: **correct**, confidence 0.6: The answer says the release covering 2026 has no announced date. It labels 4 Nov 2027 as its own estimate from the past pattern, not a scheduled date. Its 5 Nov 2026 date for the reference-year-2025 release matches the key's reference value. The "not_published" flag is set to true. Some risk remains because it offers a specific 2027 date and leads with a different reading of the question.

```text
The 2026 provincial and territorial economic accounts have already been released. Statistics Canada put them out on **5 November 2026**, and they cover reference year 2025. The earlier ones came out on 6 November 2025 (reference year 2024) and 7 November 2024 (reference year 2023).

If the question meant the next release, covering 2026, Statistics Canada has not announced a date. Going by the past pattern, it would come out around 4 November 2027. That is my estimate from past dates, not a scheduled date.

Source: Statistics Canada release calendar and The Daily (https://www150.statcan.gc.ca/daily-quotidien/261105/dq261105a-eng.htm).

```json
{"values": [
{"name": "Latest release of Provincial and territorial economic accounts (reference year 2025)", "value": "2026-11-05", "unit": "date", "period": "2025"},
{"name": "Previous release (reference year 2024)", "value": "2025-11-06", "unit": "date", "period": "2024"},
{"name": "Estimated next release (not scheduled, based on past pattern)", "value": "2027-11-04", "unit": "date", "period": "2026"}
],
"sources": [{"publisher": "Statistics Canada", "id": "The Daily release calendar: Provincial and territorial economic accounts (dq261105a)"}],
"not_published": true,
"abstain": false,
"abstain_reason": ""}
```
```


## T-12 (refusal, test)

> What was the Bank of Canada's noon USD/CAD exchange rate on October 30, 2026?

Key: `{'behaviour': 'Say the Bank no longer publishes noon rates (the last was on April 28, 2017); it publishes one daily average rate, by 16:30 ET.'}`

### ref 67d8291024

- Grader: **hallucinated** (regex: gave a figure for something not published)
- Judge: **abstained**, confidence 0.5: The answer gives 1.396 but labels it as the daily average, not a noon rate. It says only that it "didn't find" a noon series. It never says noon rates were discontinued in 2017, so it doesn't make the required call. It also doesn't invent a noon rate. A reviewer could instead grade it hallucinated, because it answers a noon-rate question with the average rate.

```text
On October 30, 2026, the Bank of Canada's USD/CAD rate was **1.3960** Canadian dollars per US dollar.

The Bank of Canada's Valet series FXUSDCAD describes this as the daily average exchange rate. It is an indicative rate, not a rate banks or dealers trade at. I didn't find a separate "noon" series in the data I pulled.

```json
{"values": [{"name": "USD/CAD daily exchange rate (Bank of Canada)", "value": 1.396, "unit": "CAD per USD", "period": "2026-10-30"}],
 "sources": [{"publisher": "Bank of Canada", "id": "Valet series FXUSDCAD"}],
 "not_published": false,
 "abstain": false,
 "abstain_reason": ""}
```
```


## T-25 (documentation, test)

> On Toronto's open data portal (CKAN), which City division owns the 'TTC Subway Delay Data' dataset, how often is it refreshed, and what data type does the DataStore give the 'Min Delay' field of the table of delays since 2025?

Key: `{'owner': 'Toronto Transit Commission', 'refresh': 'Monthly', 'min_delay_type': 'text'}`

### ref 0e6b25d2de

- Grader: **correct** (json: JSON: every expected fact)
- Judge: **partial**, confidence 0.72: Refresh (monthly) and Min Delay type (text) are correct. The owner division (Toronto Transit Commission) is not given. The answer says it could not check and names only "City of Toronto" as publisher. That is two of three values with a headline value missing, so partial.

```text
**Division:** I couldn't check this. The portal record names the publisher as "City of Toronto" (organization `city-of-toronto`). The tool I used doesn't return the portal's separate "owner division" field, so I won't guess a division. The dataset page, https://open.toronto.ca/dataset/ttc-subway-delay-data/, should show it under "Owner division".

**Refresh rate:** Monthly (`refresh_rate` = "Monthly"). The record was last modified on 2026-10-29.

**'Min Delay' data type:** In the DataStore table "TTC Subway Delay Data since 2025" (resource `6088e14f-e46e-4f5c-9daa-dea1359ad396`), 'Min Delay' is `text`, not a number. A sample value is "5". The table had 47,915 records when I queried it on 2026-11-09. 'Min Gap' is also `text`.

```json
{"values": [
{"name": "Publishing organization (owner division not exposed)", "value": "City of Toronto", "unit": "text", "period": "as of 2026-11-09"},
{"name": "Refresh rate", "value": "Monthly", "unit": "text", "period": "as of 2026-11-09"},
{"name": "DataStore type of 'Min Delay' (TTC Subway Delay Data since 2025)", "value": "text", "unit": "text", "period": "as of 2026-11-09"},
{"name": "DataStore record count", "value": 47915, "unit": "records", "period": "as of 2026-11-09"}
],
"sources": [{"publisher": "City of Toronto Open Data (CKAN)", "id": "ttc-subway-delay-data / resource 6088e14f-e46e-4f5c-9daa-dea1359ad396"}],
"not_published": false,
"abstain": true,
"abstain_reason": "The owner division field is not returned by the available tools. Only the organization 'City of Toronto' could be confirmed. Refresh rate and field type were checked."}
```
```

