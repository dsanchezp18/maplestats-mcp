# Maple Test v1 results

> Written by `python -m tests.maple_test grade`. Do not edit by hand.

## Answers

Outcomes are per run.

| Arm | Correct | Partial | Abstained | Hallucinated | False claims |
| :-- | --: | --: | --: | --: | --: |
| arose26 | 14 | 1 | 0 | 0 | 0 |
| candata_mcp | 15 | 0 | 0 | 0 | 0 |
| maplestats | 14 | 1 | 0 | 0 | 0 |
| mcp_canada | 14 | 1 | 0 | 0 | 0 |
| mcp_statcan | 12 | 2 | 1 | 0 | 0 |
| no_tools | 2 | 0 | 13 | 0 | 0 |
| openmcp | 15 | 0 | 0 | 0 | 0 |
| pipeworx | 12 | 2 | 1 | 0 | 0 |

## Citations and cost

- **Key coverage:** share of the answer key's own tables and vectors the answer names.
- **Precision:** of the StatCan vectors and Bank of Canada series an answer cites, the share that hold a figure the answer states (checked against the publishers).
- **Invented:** cited StatCan vectors or tables that do not exist. **Off-table:** a vector cited beside a table it does not belong to.
- **Traceable:** answers stating figures in which at least one cited ID holds one of them. **Release:** answers that mention a release date.

| Arm | Table cov. | Vector cov. | IDs cited | Precision | Invented | Off-table | Traceable | Release | Tool calls | Seconds | Cost (USD) |
| :-- | --: | --: | --: | --: | --: | --: | --: | --: | --: | --: | --: |
| arose26 | 93% | 93% | 22 | 95% | 0 | 0 | 100% | 0% | 4.3 | 10.8 | – |
| candata_mcp | 87% | 67% | 18 | 94% | 0 | 0 | 92% | 73% | 4.1 | 17.6 | – |
| maplestats | 87% | 70% | 20 | 95% | 0 | 0 | 92% | 47% | 4.3 | 15.3 | – |
| mcp_canada | 87% | 57% | 16 | 100% | 0 | 0 | 85% | 53% | 6.7 | 32.1 | – |
| mcp_statcan | 87% | 67% | 25 | 100% | 0 | 0 | 100% | 47% | 5.1 | 15.9 | – |
| no_tools | 93% | 37% | 7 | 43% | 0 | 0 | 17% | 47% | 0 | 8.7 | – |
| openmcp | 100% | 90% | 21 | 95% | 0 | 0 | 100% | 67% | 2.8 | 36.2 | – |
| pipeworx | 80% | 73% | 17 | 100% | 0 | 0 | 92% | 13% | 2.9 | 11.5 | – |

## Per question

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

`*` re-graded by hand (see the overrides file).
