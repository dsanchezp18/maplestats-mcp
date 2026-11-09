# Maple Test v4 results

> Written by `python -m tests.maple_test grade --version v4`. Do not edit by hand.

**Correct** is the share of questions answered correctly, each question weighted once (a question asked three times counts its share of correct passes). Dev is the public set, test the held-out one (README, 'Version 4').

| Arm | Correct | Dev | Test | Answers | USD per answer | Seconds per answer | Flagged for review | JSON decided | Run errors |
| :-- | --: | --: | --: | --: | --: | --: | --: | --: | --: |
| maplestats_hosted | 92.9% | 95.5% | 90.7% | 61 | 0.049 | 19.8 | 9.8% | 77.0% | 0 |

## By source

| Arm | boc | cmhc | federal | international | municipal | provincial | statcan |
| :-- | --: | --: | --: | --: | --: | --: | --: |
| maplestats_hosted | 80.0% (5) | 100.0% (3) | 100.0% (7) | 100.0% (4) | 100.0% (2) | 100.0% (4) | 89.4% (22) |

## Judge

| Arm | Judged | Agrees with the grader | Flagged |
| :-- | --: | --: | --: |
| maplestats_hosted | 61 | 91.8% | 6 of 61 (9.8%) |

## Per answer

| Question | Split | Arm | Pass | Grade | Basis | Judge | Review |
| :-- | :-- | :-- | --: | :-- | :-- | :-- | :-- |
| A-01 | test | maplestats_hosted | 0 | correct | json | correct (0.85) |  |
| A-02 | dev | maplestats_hosted | 0 | correct | regex | correct (0.85) |  |
| A-02 | dev | maplestats_hosted | 1 | correct | regex | correct (0.88) |  |
| A-02 | dev | maplestats_hosted | 2 | correct | regex | correct (0.85) |  |
| A-03 | test | maplestats_hosted | 0 | correct | json | correct (0.93) |  |
| A-03 | test | maplestats_hosted | 1 | correct | json | correct (0.90) |  |
| A-03 | test | maplestats_hosted | 2 | correct | json | correct (0.93) |  |
| A-05 | dev | maplestats_hosted | 0 | correct | json | correct (0.88) |  |
| C-01 | test | maplestats_hosted | 0 | correct | json | correct (0.93) |  |
| C-05 | test | maplestats_hosted | 0 | partial | regex | hallucinated (0.72) | yes |
| C-05 | test | maplestats_hosted | 1 | correct | json | correct (0.93) |  |
| C-05 | test | maplestats_hosted | 2 | correct | json | correct (0.90) |  |
| C-09 | dev | maplestats_hosted | 0 | correct | json | correct (0.80) |  |
| C-10 | dev | maplestats_hosted | 0 | correct | json | correct (0.90) |  |
| C-11 | test | maplestats_hosted | 0 | correct | json | correct (0.90) |  |
| C-16 | test | maplestats_hosted | 0 | correct | json | correct (0.85) |  |
| C-19 | dev | maplestats_hosted | 0 | correct | json | correct (0.85) |  |
| C-21 | test | maplestats_hosted | 0 | correct | json | hallucinated (0.45) | yes |
| C-24 | dev | maplestats_hosted | 0 | correct | regex | correct (0.92) |  |
| M-04 | dev | maplestats_hosted | 0 | correct | json | correct (0.93) |  |
| M-09 | dev | maplestats_hosted | 0 | hallucinated | regex | hallucinated (0.70) |  |
| M-11 | test | maplestats_hosted | 0 | correct | json | correct (0.90) |  |
| M-15 | test | maplestats_hosted | 0 | hallucinated | regex | partial (0.55) | yes |
| R-01 | test | maplestats_hosted | 0 | correct | json | correct (0.72) |  |
| R-03 | dev | maplestats_hosted | 0 | correct | json | correct (0.90) |  |
| R-04 | test | maplestats_hosted | 0 | correct | json | correct (0.90) |  |
| R-06 | test | maplestats_hosted | 0 | correct | json | correct (0.60) | yes |
| T-02 | dev | maplestats_hosted | 0 | correct | json | correct (0.95) |  |
| T-06 | dev | maplestats_hosted | 0 | correct | json | correct (0.90) |  |
| T-12 | test | maplestats_hosted | 0 | hallucinated | regex | abstained (0.50) | yes |
| T-14 | test | maplestats_hosted | 0 | correct | json | correct (0.88) |  |
| T-14 | test | maplestats_hosted | 1 | correct | json | correct (0.88) |  |
| T-14 | test | maplestats_hosted | 2 | correct | json | correct (0.80) |  |
| T-15 | test | maplestats_hosted | 0 | correct | json | correct (0.90) |  |
| T-15 | test | maplestats_hosted | 1 | correct | json | correct (0.93) |  |
| T-15 | test | maplestats_hosted | 2 | correct | json | correct (0.93) |  |
| T-17 | test | maplestats_hosted | 0 | correct | json | correct (0.90) |  |
| T-19 | test | maplestats_hosted | 0 | correct | json | correct (0.85) |  |
| T-19 | test | maplestats_hosted | 1 | correct | json | correct (0.90) |  |
| T-19 | test | maplestats_hosted | 2 | correct | json | correct (0.90) |  |
| T-20 | test | maplestats_hosted | 0 | correct | json | correct (0.88) |  |
| T-22 | dev | maplestats_hosted | 0 | correct | regex | correct (0.95) |  |
| T-25 | test | maplestats_hosted | 0 | correct | json | partial (0.72) | yes |
| T-28 | dev | maplestats_hosted | 0 | correct | json | correct (0.90) |  |
| T-30 | test | maplestats_hosted | 0 | correct | json | correct (0.88) |  |
| T-31 | dev | maplestats_hosted | 0 | correct | json | correct (0.88) |  |
| T-34 | test | maplestats_hosted | 0 | correct | json | correct (0.90) |  |
| T-36 | dev | maplestats_hosted | 0 | correct | json | correct (0.88) |  |
| X-01 | dev | maplestats_hosted | 0 | correct | json | correct (0.92) |  |
| X-05 | test | maplestats_hosted | 0 | correct | json | correct (0.88) |  |
| X-08 | test | maplestats_hosted | 0 | correct | json | correct (0.90) |  |
| X-10 | dev | maplestats_hosted | 0 | correct | json | correct (0.93) |  |
| X-12 | dev | maplestats_hosted | 0 | correct | json | correct (0.88) |  |
| X-15 | test | maplestats_hosted | 0 | correct | regex | correct (0.90) |  |
| X-16 | dev | maplestats_hosted | 0 | correct | regex | correct (0.93) |  |
| X-17 | dev | maplestats_hosted | 0 | correct | json | correct (0.96) |  |
| X-20 | test | maplestats_hosted | 0 | correct | json | correct (0.90) |  |
| X-23 | dev | maplestats_hosted | 0 | correct | json | correct (0.93) |  |
| X-24 | dev | maplestats_hosted | 0 | correct | regex | correct (0.88) |  |
| X-24 | dev | maplestats_hosted | 1 | correct | regex | correct (0.88) |  |
| X-24 | dev | maplestats_hosted | 2 | correct | regex | correct (0.80) |  |

`*` settled by a person (overrides_v4.json).
