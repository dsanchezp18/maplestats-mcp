# Maple Test results

> Written by `python -m tests.maple_test grade`. Do not edit by hand.

| Arm | Model | Run date | Correct | Partial | Abstained | Hallucinated | False claims | Table citations | Vector citations | Tool calls | Errors |
| :-- | :-- | :-- | --: | --: | --: | --: | --: | --: | --: | --: | --: |
| arose26 | claude-sonnet-5-5 | 2026-11-02 | 14 | 1 | 0 | 0 | 0 | 93% | 80% | 4.3 | 0 |
| candata_mcp | claude-sonnet-5-5 | 2026-11-02 | 15 | 0 | 0 | 0 | 0 | 87% | 53% | 4.1 | 0 |
| maplestats | claude-sonnet-5-5 | 2026-11-02 | 14 | 1 | 0 | 0 | 0 | 87% | 57% | 4.3 | 0 |
| mcp_canada | claude-sonnet-5-5 | 2026-11-02 | 14 | 1 | 0 | 0 | 0 | 87% | 50% | 6.7 | 0 |
| mcp_statcan | claude-sonnet-5-5 | 2026-11-02 | 12 | 2 | 1 | 0 | 0 | 87% | 53% | 5.1 | 0 |
| no_tools | claude-sonnet-5-5 | 2026-11-02 | 2 | 0 | 13 | 0 | 0 | 93% | 37% | 0.0 | 0 |
| openmcp | claude-sonnet-5-5 | 2026-11-02 | 15 | 0 | 0 | 0 | 0 | 100% | 77% | 2.8 | 0 |
| pipeworx | claude-sonnet-5-5 | 2026-11-02 | 12 | 2 | 1 | 0 | 0 | 80% | 67% | 2.9 | 0 |

| Question | arose26 | candata_mcp | maplestats | mcp_canada | mcp_statcan | no_tools | openmcp | pipeworx |
| :-- | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: |
| M-01 Labour | correct | correct | correct | correct | correct | abstained | correct | correct |
| M-02 Labour | correct | correct | correct | correct | correct | abstained | correct | correct |
| M-03 Population | correct | correct | correct | correct | correct | abstained | correct | correct |
| M-04 Population | correct | correct | correct | correct | correct | abstained* | correct | abstained* |
| M-05 Population | correct | correct | correct | correct | correct | abstained | correct | correct |
| M-06 Prices | correct | correct | correct | correct | correct | abstained | correct | correct |
| M-07 Prices | correct | correct | correct | correct | correct | abstained | correct | correct |
| M-08 Output | correct | correct | correct | correct | correct | abstained* | correct | correct |
| M-09 Trade | correct | correct | correct | correct | partial* | abstained* | correct | correct |
| M-10 Labour | correct | correct | correct | correct | correct | abstained | correct | partial* |
| M-11 Markets | correct | correct | correct | correct | abstained | abstained* | correct | correct |
| M-12 Markets | correct | correct | correct | correct | correct | abstained* | correct | correct |
| M-13 Unanswerable | correct | correct* | correct | correct | correct | correct | correct | correct |
| M-14 Unanswerable | correct | correct | correct | correct | correct | correct | correct | correct |
| M-15 Labour | partial* | correct* | partial* | partial* | partial* | abstained* | correct* | partial* |

`*` re-graded by hand (overrides.json).
