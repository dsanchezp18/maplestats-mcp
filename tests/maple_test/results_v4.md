# Maple Test v4 results

> Written by `python -m tests.maple_test grade --version v4`. Do not edit by hand.

**Correct** is the share of questions answered correctly, each question weighted once (a question asked three times counts its share of correct passes). Dev is the public set, test the held-out one (README, 'Version 4').

| Arm | Correct | Dev | Test | Answers | USD per answer | Seconds per answer | Flagged for review | JSON decided | Run errors |
| :-- | --: | --: | --: | --: | --: | --: | --: | --: | --: |
| maplestats_hosted | 89.4% | 92.2% | 84.0% | 84 | 0.048 | 13.7 | 11.9% | 75.0% | 0 |
| openmcp | 62.5% | 68.1% | 52.0% | 84 | 0.063 | 93.9 | 22.6% | 59.5% | 0 |

## By source

| Arm | boc | cmhc | federal | international | municipal | provincial | statcan |
| :-- | --: | --: | --: | --: | --: | --: | --: |
| maplestats_hosted | 100.0% (8) | 73.3% (5) | 90.9% (11) | 100.0% (6) | 33.3% (3) | 100.0% (6) | 89.9% (33) |
| openmcp | 75.0% (8) | 60.0% (5) | 45.5% (11) | 66.7% (6) | 33.3% (3) | 16.7% (6) | 75.8% (33) |

## Judge

| Arm | Judged | Agrees with the grader | Flagged |
| :-- | --: | --: | --: |
| maplestats_hosted | 84 | 90.5% | 10 of 84 (11.9%) |
| openmcp | 84 | 78.6% | 19 of 84 (22.6%) |

## Per answer

| Question | Split | Arm | Pass | Grade | Basis | Judge | Review |
| :-- | :-- | :-- | --: | :-- | :-- | :-- | :-- |
| A-01 | dev | maplestats_hosted | 0 | correct | json | correct (0.90) |  |
| A-01 | dev | openmcp | 0 | correct | json | correct (0.90) |  |
| A-02 | dev | maplestats_hosted | 0 | correct | regex | correct (0.85) |  |
| A-02 | dev | maplestats_hosted | 1 | correct | regex | correct (0.85) |  |
| A-02 | dev | maplestats_hosted | 2 | correct | regex | correct (0.90) |  |
| A-02 | dev | openmcp | 0 | hallucinated* | regex | hallucinated (0.90) | settled |
| A-02 | dev | openmcp | 1 | correct | regex | correct (0.90) |  |
| A-02 | dev | openmcp | 2 | partial* | regex | partial (0.70) | settled |
| A-03 | dev | maplestats_hosted | 0 | correct | json | correct (0.93) |  |
| A-03 | dev | maplestats_hosted | 1 | correct | json | correct (0.93) |  |
| A-03 | dev | maplestats_hosted | 2 | correct | json | correct (0.90) |  |
| A-03 | dev | openmcp | 0 | partial | regex | partial (0.80) |  |
| A-03 | dev | openmcp | 1 | correct | json | correct (0.90) |  |
| A-03 | dev | openmcp | 2 | correct | json | correct (0.85) |  |
| A-05 | dev | maplestats_hosted | 0 | correct | json | correct (0.85) |  |
| A-05 | dev | openmcp | 0 | correct | json | correct (0.80) |  |
| C-01 | dev | maplestats_hosted | 0 | correct | json | correct (0.93) |  |
| C-01 | dev | openmcp | 0 | correct | json | correct (0.88) |  |
| C-05 | dev | maplestats_hosted | 0 | correct | json | correct (0.90) |  |
| C-05 | dev | maplestats_hosted | 1 | partial* | regex | hallucinated (0.90) | settled |
| C-05 | dev | maplestats_hosted | 2 | correct | json | correct (0.90) |  |
| C-05 | dev | openmcp | 0 | correct | json | correct (0.90) |  |
| C-05 | dev | openmcp | 1 | correct | json | correct (0.93) |  |
| C-05 | dev | openmcp | 2 | correct | json | correct (0.93) |  |
| C-09 | dev | maplestats_hosted | 0 | correct | json | correct (0.85) |  |
| C-09 | dev | openmcp | 0 | correct | json | correct (0.82) |  |
| C-10 | dev | maplestats_hosted | 0 | correct | json | correct (0.90) |  |
| C-10 | dev | openmcp | 0 | correct | json | correct (0.90) |  |
| C-11 | dev | maplestats_hosted | 0 | correct | json | correct (0.93) |  |
| C-11 | dev | openmcp | 0 | correct | json | correct (0.90) |  |
| C-16 | dev | maplestats_hosted | 0 | correct | json | correct (0.93) |  |
| C-16 | dev | openmcp | 0 | correct | regex | correct (0.90) |  |
| C-19 | dev | maplestats_hosted | 0 | correct | json | correct (0.80) |  |
| C-19 | dev | openmcp | 0 | correct | json | correct (0.85) |  |
| C-21 | dev | maplestats_hosted | 0 | correct* | json | hallucinated (0.40) | settled |
| C-21 | dev | openmcp | 0 | correct | json | correct (0.93) |  |
| C-24 | dev | maplestats_hosted | 0 | correct | regex | correct (0.88) |  |
| C-24 | dev | openmcp | 0 | correct | regex | correct (0.93) |  |
| M-04 | dev | maplestats_hosted | 0 | correct | json | correct (0.90) |  |
| M-04 | dev | openmcp | 0 | correct | json | correct (0.90) |  |
| M-09 | dev | maplestats_hosted | 0 | correct | regex | correct (0.90) |  |
| M-09 | dev | openmcp | 0 | correct | json | correct (0.88) |  |
| M-11 | dev | maplestats_hosted | 0 | correct | json | correct (0.93) |  |
| M-11 | dev | openmcp | 0 | correct | json | correct (0.95) |  |
| M-15 | dev | maplestats_hosted | 0 | partial* | regex | partial (0.60) | settled |
| M-15 | dev | openmcp | 0 | partial* | regex | correct (0.68) | settled |
| N-01 | test | maplestats_hosted | 0 | correct | json | correct (0.90) |  |
| N-01 | test | openmcp | 0 | correct | json | correct (0.88) |  |
| N-02 | test | maplestats_hosted | 0 | correct | json | correct (0.90) |  |
| N-02 | test | openmcp | 0 | correct | json | correct (0.93) |  |
| N-03 | test | maplestats_hosted | 0 | correct | json | correct (0.90) |  |
| N-03 | test | openmcp | 0 | correct | json | correct (0.90) |  |
| N-04 | test | maplestats_hosted | 0 | correct | json | correct (0.93) |  |
| N-04 | test | openmcp | 0 | hallucinated | regex | hallucinated (0.95) |  |
| N-05 | test | maplestats_hosted | 0 | correct | json | correct (0.93) |  |
| N-05 | test | openmcp | 0 | correct | json | correct (0.88) |  |
| N-06 | test | maplestats_hosted | 0 | correct | regex | correct (0.93) |  |
| N-06 | test | openmcp | 0 | correct | regex | correct (0.93) |  |
| N-07 | test | maplestats_hosted | 0 | correct | json | correct (0.90) |  |
| N-07 | test | openmcp | 0 | correct | json | correct (0.88) |  |
| N-08 | test | maplestats_hosted | 0 | correct | json | correct (0.90) |  |
| N-08 | test | openmcp | 0 | partial* | json | partial (0.72) | settled |
| N-09 | test | maplestats_hosted | 0 | correct | json | correct (0.85) |  |
| N-09 | test | openmcp | 0 | correct | json | correct (0.90) |  |
| N-10 | test | maplestats_hosted | 0 | correct | json | correct (0.90) |  |
| N-10 | test | openmcp | 0 | abstained | regex | abstained (0.90) |  |
| N-11 | test | maplestats_hosted | 0 | abstained* | regex | abstained (0.90) | settled |
| N-11 | test | openmcp | 0 | abstained | regex | abstained (0.85) |  |
| N-12 | test | maplestats_hosted | 0 | correct | json | correct (0.96) |  |
| N-12 | test | openmcp | 0 | correct | regex | correct (0.95) |  |
| N-13 | test | maplestats_hosted | 0 | correct | json | correct (0.93) |  |
| N-13 | test | openmcp | 0 | partial* | json | partial (0.80) | settled |
| N-14 | test | maplestats_hosted | 0 | correct | json | correct (0.82) |  |
| N-14 | test | openmcp | 0 | correct | json | correct (0.93) |  |
| N-15 | test | maplestats_hosted | 0 | partial* | regex | partial (0.50) | settled |
| N-15 | test | openmcp | 0 | hallucinated* | json | hallucinated (0.72) | settled |
| N-16 | test | maplestats_hosted | 0 | correct | json | correct (0.92) |  |
| N-16 | test | openmcp | 0 | correct | json | correct (0.93) |  |
| N-17 | test | maplestats_hosted | 0 | correct | json | correct (0.90) |  |
| N-17 | test | openmcp | 0 | partial* | regex | partial (0.62) | settled |
| N-18 | test | maplestats_hosted | 0 | correct | json | correct (0.93) |  |
| N-18 | test | openmcp | 0 | partial* | regex | partial (0.60) | settled |
| N-19 | test | maplestats_hosted | 0 | partial* | regex | partial (0.60) | settled |
| N-19 | test | openmcp | 0 | partial* | regex | partial (0.80) | settled |
| N-20 | test | maplestats_hosted | 0 | correct | json | correct (0.85) |  |
| N-20 | test | openmcp | 0 | partial* | regex | partial (0.75) | settled |
| N-21 | test | maplestats_hosted | 0 | correct | json | correct (0.93) |  |
| N-21 | test | openmcp | 0 | correct | json | correct (0.93) |  |
| N-22 | test | maplestats_hosted | 0 | partial* | json | partial (0.72) | settled |
| N-22 | test | openmcp | 0 | abstained | json | abstained (0.85) |  |
| N-23 | test | maplestats_hosted | 0 | correct | json | correct (0.85) |  |
| N-23 | test | openmcp | 0 | abstained* | regex | abstained (0.90) | settled |
| N-24 | test | maplestats_hosted | 0 | correct | json | correct (0.96) |  |
| N-24 | test | openmcp | 0 | correct | json | correct (0.93) |  |
| N-25 | test | maplestats_hosted | 0 | correct | json | correct (0.85) |  |
| N-25 | test | openmcp | 0 | correct | json | correct (0.88) |  |
| R-01 | dev | maplestats_hosted | 0 | correct* | json | correct (0.60) | settled |
| R-01 | dev | openmcp | 0 | correct | json | correct (0.75) |  |
| R-03 | dev | maplestats_hosted | 0 | hallucinated | regex | hallucinated (0.95) |  |
| R-03 | dev | openmcp | 0 | hallucinated | regex | hallucinated (0.95) |  |
| R-04 | dev | maplestats_hosted | 0 | correct | json | correct (0.93) |  |
| R-04 | dev | openmcp | 0 | correct | json | correct (0.90) |  |
| R-06 | dev | maplestats_hosted | 0 | correct | json | correct (0.85) |  |
| R-06 | dev | openmcp | 0 | partial* | regex | hallucinated (0.62) | settled |
| T-02 | dev | maplestats_hosted | 0 | correct | json | correct (0.93) |  |
| T-02 | dev | openmcp | 0 | correct | json | correct (0.78) |  |
| T-06 | dev | maplestats_hosted | 0 | correct | json | correct (0.93) |  |
| T-06 | dev | openmcp | 0 | correct | json | correct (0.93) |  |
| T-12 | dev | maplestats_hosted | 0 | correct* | regex | correct (0.62) | settled |
| T-12 | dev | openmcp | 0 | hallucinated | regex | hallucinated (0.90) |  |
| T-14 | dev | maplestats_hosted | 0 | correct | json | correct (0.90) |  |
| T-14 | dev | maplestats_hosted | 1 | correct | json | correct (0.85) |  |
| T-14 | dev | maplestats_hosted | 2 | correct | json | correct (0.85) |  |
| T-14 | dev | openmcp | 0 | correct | regex | correct (0.80) |  |
| T-14 | dev | openmcp | 1 | correct | json | correct (0.82) |  |
| T-14 | dev | openmcp | 2 | correct | json | correct (0.80) |  |
| T-15 | dev | maplestats_hosted | 0 | correct | json | correct (0.88) |  |
| T-15 | dev | maplestats_hosted | 1 | hallucinated | regex | hallucinated (0.85) |  |
| T-15 | dev | maplestats_hosted | 2 | correct | json | correct (0.93) |  |
| T-15 | dev | openmcp | 0 | hallucinated* | regex | hallucinated (0.60) | settled |
| T-15 | dev | openmcp | 1 | hallucinated | regex | hallucinated (0.80) |  |
| T-15 | dev | openmcp | 2 | hallucinated* | json | hallucinated (0.60) | settled |
| T-17 | dev | maplestats_hosted | 0 | correct | regex | correct (0.88) |  |
| T-17 | dev | openmcp | 0 | correct | regex | correct (0.72) |  |
| T-19 | dev | maplestats_hosted | 0 | correct | json | correct (0.90) |  |
| T-19 | dev | openmcp | 0 | abstained* | regex | abstained (0.90) | settled |
| T-20 | dev | maplestats_hosted | 0 | correct | json | correct (0.88) |  |
| T-20 | dev | openmcp | 0 | partial | regex | partial (0.80) |  |
| T-22 | dev | maplestats_hosted | 0 | correct | regex | correct (0.93) |  |
| T-22 | dev | openmcp | 0 | partial | regex | partial (0.80) |  |
| T-25 | dev | maplestats_hosted | 0 | partial* | json | partial (0.72) | settled |
| T-25 | dev | openmcp | 0 | correct | json | correct (0.88) |  |
| T-28 | dev | maplestats_hosted | 0 | correct | json | correct (0.90) |  |
| T-28 | dev | openmcp | 0 | partial* | regex | hallucinated (0.80) | settled |
| T-30 | dev | maplestats_hosted | 0 | correct | json | correct (0.88) |  |
| T-30 | dev | openmcp | 0 | correct | json | correct (0.90) |  |
| T-31 | dev | maplestats_hosted | 0 | correct | json | correct (0.85) |  |
| T-31 | dev | openmcp | 0 | correct | json | correct (0.93) |  |
| T-34 | dev | maplestats_hosted | 0 | correct | json | correct (0.93) |  |
| T-34 | dev | openmcp | 0 | correct | json | correct (0.90) |  |
| T-36 | dev | maplestats_hosted | 0 | correct | json | correct (0.78) |  |
| T-36 | dev | openmcp | 0 | hallucinated* | regex | hallucinated (0.93) | settled |
| X-01 | dev | maplestats_hosted | 0 | correct | json | correct (0.95) |  |
| X-01 | dev | openmcp | 0 | correct | json | correct (0.93) |  |
| X-05 | dev | maplestats_hosted | 0 | correct | json | correct (0.95) |  |
| X-05 | dev | openmcp | 0 | correct | json | correct (0.93) |  |
| X-08 | dev | maplestats_hosted | 0 | correct | json | correct (0.90) |  |
| X-08 | dev | openmcp | 0 | abstained | json | abstained (0.85) |  |
| X-10 | dev | maplestats_hosted | 0 | correct | json | correct (0.93) |  |
| X-10 | dev | openmcp | 0 | correct | json | correct (0.95) |  |
| X-12 | dev | maplestats_hosted | 0 | correct | json | correct (0.90) |  |
| X-12 | dev | openmcp | 0 | abstained* | regex | abstained (0.85) | settled |
| X-15 | dev | maplestats_hosted | 0 | correct | regex | correct (0.93) |  |
| X-15 | dev | openmcp | 0 | abstained* | regex | abstained (0.95) | settled |
| X-16 | dev | maplestats_hosted | 0 | correct | regex | correct (0.93) |  |
| X-16 | dev | openmcp | 0 | abstained | json | abstained (0.90) |  |
| X-17 | dev | maplestats_hosted | 0 | correct | json | correct (0.96) |  |
| X-17 | dev | openmcp | 0 | correct | json | correct (0.93) |  |
| X-20 | dev | maplestats_hosted | 0 | correct | json | correct (0.92) |  |
| X-20 | dev | openmcp | 0 | correct | json | correct (0.80) |  |
| X-23 | dev | maplestats_hosted | 0 | correct | json | correct (0.93) |  |
| X-23 | dev | openmcp | 0 | correct | json | correct (0.90) |  |
| X-24 | dev | maplestats_hosted | 0 | correct | regex | correct (0.85) |  |
| X-24 | dev | maplestats_hosted | 1 | correct | regex | correct (0.85) |  |
| X-24 | dev | maplestats_hosted | 2 | correct | regex | correct (0.90) |  |
| X-24 | dev | openmcp | 0 | correct | regex | correct (0.90) |  |
| X-24 | dev | openmcp | 1 | correct | regex | correct (0.85) |  |
| X-24 | dev | openmcp | 2 | correct | regex | correct (0.90) |  |

`*` settled by a person (overrides_v4.json).
