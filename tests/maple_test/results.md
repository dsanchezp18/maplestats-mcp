# Maple Test results

> Written by `python -m tests.maple_test grade`. Do not edit by hand.

| Arm | Model | Run date | Correct | Partial | Abstained | Hallucinated | False claims | Table citations | Vector citations | Tool calls | Errors |
| :-- | :-- | :-- | --: | --: | --: | --: | --: | --: | --: | --: | --: |
| maplestats | claude-sonnet-5-5 | 2026-11-02 | 14 | 1 | 0 | 0 | 0 | 87% | 57% | 4.3 | 0 |
| mcp_statcan | claude-sonnet-5-5 | 2026-11-02 | 12 | 2 | 1 | 0 | 0 | 87% | 53% | 5.1 | 0 |
| no_tools | claude-sonnet-5-5 | 2026-11-02 | 2 | 0 | 13 | 0 | 0 | 93% | 37% | 0.0 | 0 |
| pipeworx | claude-sonnet-5-5 | 2026-11-02 | 12 | 2 | 1 | 0 | 0 | 80% | 67% | 2.9 | 0 |

| Question | maplestats | mcp_statcan | no_tools | pipeworx |
| :-- | :-: | :-: | :-: | :-: |
| M-01 Labour | correct | correct | abstained | correct |
| M-02 Labour | correct | correct | abstained | correct |
| M-03 Population | correct | correct | abstained | correct |
| M-04 Population | correct | correct | abstained* | abstained* |
| M-05 Population | correct | correct | abstained | correct |
| M-06 Prices | correct | correct | abstained | correct |
| M-07 Prices | correct | correct | abstained | correct |
| M-08 Output | correct | correct | abstained* | correct |
| M-09 Trade | correct | partial* | abstained* | correct |
| M-10 Labour | correct | correct | abstained | partial* |
| M-11 Markets | correct | abstained | abstained* | correct |
| M-12 Markets | correct | correct | abstained* | correct |
| M-13 Unanswerable | correct | correct | correct | correct |
| M-14 Unanswerable | correct | correct | correct | correct |
| M-15 Labour | partial* | partial* | abstained* | partial* |

`*` re-graded by hand (overrides.json).
