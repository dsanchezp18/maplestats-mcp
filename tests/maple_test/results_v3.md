# Maple Test v3 results

> Written by `python -m tests.maple_test grade`. Do not edit by hand.

## Answers

Outcomes are per run (mean over repeats; worst and best run beside correct).

| Arm | Correct | BoC | CMHC | Federal | Municipal | Provincial | StatCan | Worst–best | Consistency | Partial | Abstained | Hallucinated | False claims | Referrals |
| :-- | --: | --: | --: | --: | --: | --: | --: | --: | --: | --: | --: | --: | --: | --: |
| maplestats-brief | 27 | 3 of 3 | 3 of 4 | 0 of 3 | 3 of 4 | 8 of 9 | 10 of 13 | 26–28 | 92% | 6.3 | 1.7 | 1 | 3 | 1 |
| maplestats-full | 23 | 2.7 of 3 | 3 of 4 | 0.7 of 3 | 3 of 4 | 5 of 9 | 8.7 of 13 | 23–23 | 86% | 7.7 | 4 | 1.3 | 1 | 7 |
| maplestats-postfix | 32.7 | 3 of 3 | 3.7 of 4 | 3 of 3 | 3 of 4 | 7.3 of 9 | 12.7 of 13 | 31–34 | 89% | 2.7 | 0.3 | 0.3 | 1 | 1 |
| openmcp-1109 | 17.7 | 3 of 3 | 3 of 4 | 0.3 of 3 | 2.7 of 4 | 2.3 of 9 | 6.3 of 13 | 17–18 | 81% | 8.3 | 7 | 3 | 1 | 8 |

Partly in-sample: `maplestats-postfix` ran server fixes chosen after seeing the first v3 runs' misses; MapleStats' comparable v3 score is `maplestats-brief` (README).

## Citations and cost

- **Key coverage:** share of the answer key's own tables and vectors the answer names.
- **Precision:** of the StatCan vectors and Bank of Canada series an answer cites, the share that hold a figure the answer states (checked against the publishers).
- **Invented:** cited StatCan vectors or tables that do not exist. **Off-table:** a vector cited beside a table it does not belong to.
- **Traceable:** answers stating figures in which at least one cited ID holds one of them (a stored value, or one scaled by the series' thousands or millions). **Checked:** the same share among answers that cite a StatCan vector or Bank of Canada series, the only IDs checked; other publishers' IDs are not, so answers on them count as untraceable in the first share. **Release:** answers that mention a release date.
- **Cost** is per answer (headless Claude Code's `total_cost_usd`). **Tokens in** is the input the model read per answer, cached or not (runs before 2026-11-08 did not record the cached share, so they show a dash); **out** is what it wrote.

| Arm | Table cov. | Vector cov. | IDs cited | Precision | Invented | Off-table | Traceable | Checked | Release | Tool calls | Seconds | Cost (USD) | Tokens in | Tokens out |
| :-- | --: | --: | --: | --: | --: | --: | --: | --: | --: | --: | --: | --: | --: | --: |
| maplestats-brief | 100% | 99% | 35 | 66% | 0 | 0 | 10% | 50% | 36% | 4.5 | 14.8 | 0.063 | 50.6k | 1.0k |
| maplestats-full | 100% | 99% | 33 | 70% | 0 | 0 | 9% | 50% | 31% | 4.3 | 15.3 | 0.060 | 47.6k | 0.9k |
| maplestats-postfix | 100% | 99% | 32 | 47% | 0 | 0 | 9% | 53% | 26% | 4.0 | 17.3 | 0.048 | 37.4k | 0.9k |
| openmcp-1109 | 100% | 99% | 32 | 28% | 0 | 3 | 3% | 20% | 20% | 3.3 | 79.5 | 0.047 | 45.4k | 0.9k |

## Per question

| Question | maplestats-brief | maplestats-full | maplestats-postfix | openmcp-1109 |
| :-- | :-: | :-: | :-: | :-: |
| T-01 Survey documentation | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct |
| T-02 Survey documentation | correct / correct / correct | partial* / partial* / partial* | correct / correct / correct | partial* / correct* / partial* |
| T-03 Survey documentation | hallucinated / hallucinated / hallucinated | hallucinated / hallucinated / hallucinated | correct / correct / correct | hallucinated / hallucinated / hallucinated |
| T-04 Revisions | correct / correct / correct | correct / correct / correct | correct / correct* / correct | correct* / correct / correct |
| T-05 Seasonal adjustment | partial* / partial* / partial* | partial* / partial* / partial* | partial* / correct / correct | abstained / abstained* / abstained* |
| T-06 Units | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / partial |
| T-07 Survey documentation | partial / partial / partial | partial / partial / partial* | correct / correct / correct | partial / partial / partial |
| T-08 Classification | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct |
| T-09 Classification | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct |
| T-10 Series metadata | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct |
| T-11 Series metadata | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct |
| T-12 Discontinued series | correct / correct / correct | hallucinated / correct / correct* | correct* / correct / correct | correct / correct / correct |
| T-13 Definitions | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct |
| T-14 Survey documentation | correct / partial* / partial* | partial / correct / correct | correct / correct / correct | correct / correct / correct |
| T-15 Quality flags | correct / correct / abstained | correct / partial* / partial* | hallucinated / correct / correct | hallucinated* / abstained* / abstained |
| T-16 Not published | correct* / correct / correct | correct* / correct* / correct | correct / correct* / correct* | correct / correct / correct |
| T-17 Dataset metadata | partial* / partial* / partial* | correct / correct / partial* | correct / correct / correct | partial* / partial* / partial* |
| T-18 Dataset metadata | partial* / partial* / partial* | partial* / partial* / partial* | correct / correct / correct | abstained* / abstained* / abstained* |
| T-19 Dataset metadata | abstained* / abstained / abstained* | abstained* / abstained* / abstained* | correct / correct / correct | hallucinated* / hallucinated* / correct |
| T-20 Dataset metadata | correct / correct / correct | correct / correct / correct | correct / correct / correct | partial* / partial / partial |
| T-21 Dataset metadata | correct / correct / correct | correct / correct / correct | correct / correct / correct | hallucinated / hallucinated / hallucinated |
| T-22 Survey documentation | correct / correct / correct | correct / correct / correct | correct / correct / correct | partial / partial / partial |
| T-23 Not published | correct / correct* / correct | correct / correct / correct | correct / correct / correct | correct* / correct / correct |
| T-24 DataStore value | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct |
| T-25 DataStore fields | partial* / partial* / partial* | partial* / partial* / partial* | partial* / abstained* / partial* | correct / partial / correct |
| T-26 DataStore value | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct |
| T-27 Dataset documentation | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct |
| T-28 DataStore fields | correct / correct / correct | correct / correct / correct | correct / correct / correct | partial* / partial* / partial* |
| T-29 Units | correct / correct / correct | correct / correct / correct | correct / correct / correct | abstained / abstained / abstained |
| T-30 Series metadata | correct / correct / correct | correct / correct / correct | correct / correct / correct | abstained* / abstained* / abstained* |
| T-31 Seasonal adjustment | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / abstained* / abstained* |
| T-32 Release dates | correct / correct / correct | correct / partial* / correct | correct / correct / correct | correct / correct / correct |
| T-33 Dataset metadata | correct / correct / correct | abstained / abstained / abstained | partial / partial / correct | abstained* / abstained* / abstained* |
| T-34 DataStore fields | correct / correct / correct | abstained / abstained / abstained | correct / correct / correct | partial* / partial* / partial* |
| T-35 Dataset metadata | abstained* / partial* / partial* | partial* / partial* / partial* | partial* / partial* / partial* | partial* / partial* / partial* |
| T-36 Dataset metadata | correct / correct / correct | abstained* / abstained / abstained* | correct / correct / correct | abstained / abstained* / correct |

`*` re-graded by hand (see the overrides file).

## Cost per question

Mean USD per answer, with the input tokens read in brackets where the run recorded them.

| Question | maplestats-brief | maplestats-full | maplestats-postfix | openmcp-1109 |
| :-- | --: | --: | --: | --: |
| T-01 | 0.052 (41.7k) | 0.036 (20.3k) | 0.027 (19.6k) | 0.035 (23.0k) |
| T-02 | 0.061 (51.5k) | 0.057 (41.4k) | 0.050 (24.7k) | 0.058 (25.7k) |
| T-03 | 0.038 (23.9k) | 0.036 (21.3k) | 0.025 (18.0k) | 0.026 (22.6k) |
| T-04 | 0.039 (23.7k) | 0.038 (26.4k) | 0.059 (48.3k) | 0.008 (9.8k) |
| T-05 | 0.127 (113.5k) | 0.126 (110.9k) | 0.052 (39.8k) | 0.091 (93.9k) |
| T-06 | 0.027 (13.7k) | 0.022 (14.3k) | 0.023 (15.3k) | 0.016 (11.4k) |
| T-07 | 0.045 (40.0k) | 0.029 (21.8k) | 0.032 (18.9k) | 0.048 (32.8k) |
| T-08 | 0.129 (148.5k) | 0.159 (186.1k) | 0.107 (123.5k) | 0.066 (96.9k) |
| T-09 | 0.031 (20.9k) | 0.027 (15.6k) | 0.020 (13.2k) | 0.010 (7.3k) |
| T-10 | 0.051 (33.2k) | 0.049 (29.4k) | 0.025 (18.3k) | 0.011 (15.5k) |
| T-11 | 0.046 (30.5k) | 0.045 (30.0k) | 0.041 (28.4k) | 0.018 (16.6k) |
| T-12 | 0.032 (28.4k) | 0.033 (37.1k) | 0.024 (23.7k) | 0.010 (15.2k) |
| T-13 | 0.045 (30.4k) | 0.054 (43.5k) | 0.021 (18.5k) | 0.022 (15.5k) |
| T-14 | 0.026 (12.2k) | 0.026 (12.2k) | 0.032 (18.9k) | 0.035 (20.7k) |
| T-15 | 0.036 (21.9k) | 0.049 (28.8k) | 0.033 (22.2k) | 0.112 (118.8k) |
| T-16 | 0.061 (50.9k) | 0.087 (74.3k) | 0.061 (54.8k) | 0.051 (46.6k) |
| T-17 | 0.095 (52.7k) | 0.101 (50.0k) | 0.085 (42.9k) | 0.037 (29.3k) |
| T-18 | 0.061 (46.2k) | 0.064 (47.7k) | 0.049 (37.9k) | 0.023 (32.9k) |
| T-19 | 0.126 (68.5k) | 0.134 (78.7k) | 0.104 (51.2k) | 0.054 (81.3k) |
| T-20 | 0.061 (48.5k) | 0.068 (59.9k) | 0.043 (34.8k) | 0.058 (62.5k) |
| T-21 | 0.027 (19.9k) | 0.027 (19.9k) | 0.020 (17.0k) | 0.045 (23.9k) |
| T-22 | 0.083 (76.3k) | 0.085 (73.2k) | 0.068 (62.2k) | 0.084 (53.7k) |
| T-23 | 0.089 (77.6k) | 0.097 (73.5k) | 0.058 (53.8k) | 0.071 (52.6k) |
| T-24 | 0.096 (125.1k) | 0.088 (110.7k) | 0.074 (89.5k) | 0.092 (78.5k) |
| T-25 | 0.082 (64.7k) | 0.074 (53.3k) | 0.049 (40.4k) | 0.052 (81.1k) |
| T-26 | 0.079 (78.1k) | 0.092 (89.6k) | 0.062 (63.7k) | 0.073 (53.2k) |
| T-27 | 0.062 (49.7k) | 0.056 (42.2k) | 0.058 (47.1k) | 0.066 (56.3k) |
| T-28 | 0.075 (64.0k) | 0.079 (65.9k) | 0.057 (49.5k) | 0.051 (42.7k) |
| T-29 | 0.045 (33.2k) | 0.037 (27.3k) | 0.023 (17.0k) | 0.039 (40.4k) |
| T-30 | 0.030 (20.3k) | 0.029 (20.2k) | 0.022 (17.2k) | 0.032 (38.1k) |
| T-31 | 0.029 (20.0k) | 0.030 (22.4k) | 0.024 (17.3k) | 0.037 (37.5k) |
| T-32 | 0.033 (21.9k) | 0.034 (22.0k) | 0.024 (17.8k) | 0.023 (32.1k) |
| T-33 | 0.044 (40.7k) | 0.031 (30.5k) | 0.025 (22.1k) | 0.039 (57.1k) |
| T-34 | 0.056 (59.1k) | 0.048 (54.5k) | 0.040 (43.6k) | 0.045 (65.8k) |
| T-35 | 0.061 (30.1k) | 0.080 (32.6k) | 0.071 (29.0k) | 0.070 (76.6k) |
| T-36 | 0.171 (141.5k) | 0.028 (27.0k) | 0.123 (85.6k) | 0.082 (65.0k) |

## False claims

- maplestats-brief T-14: States the Rental Market Survey currently runs twice a year (April and October); CMHC methodology says it runs in the first two weeks of October and the April survey was last run in 2015.
- maplestats-brief T-04: Says seasonally adjusted CPI revisions affect the previous three months; the policy is the previous month monthly and the last three years each January.
- maplestats-brief T-14: States the Rental Market Survey currently runs twice a year (April and October); CMHC methodology says it runs in the first two weeks of October and the April survey was last run in 2015.
- maplestats-full T-14: States the Rental Market Survey currently runs twice a year (April and October); CMHC methodology says it runs in the first two weeks of October and the April survey was last run in 2015.
- maplestats-postfix T-09: Says the TEER category is the fourth digit of the NOC 2021 code; it is the second digit.
- openmcp-1109 T-07: Gives the CIS survey record number as 3252; the CIS IMDB record is 5200.

## Direction of the hand review

Re-grades that changed the grader's outcome, by arm. A review that favoured one arm would raise it and lower the others; correct answers gained and lost are the ones that move the score.

| Arm | Answers | Raised | Lowered | Correct gained | Correct lost | Net correct per run |
| :-- | --: | --: | --: | --: | --: | --: |
| maplestats-brief | 108 | 10 | 11 | 2 | 10 | -2.7 |
| maplestats-full | 108 | 19 | 9 | 3 | 9 | -2.0 |
| maplestats-postfix | 108 | 6 | 5 | 4 | 5 | -0.3 |
| openmcp-1109 | 108 | 22 | 14 | 3 | 11 | -2.7 |
