# Maple Test v2 results

> Written by `python -m tests.maple_test grade`. Do not edit by hand.

## Answers

Outcomes are per run (mean over repeats; worst and best run beside correct).

| Arm | Correct | Analyst | Beyond | Core | Worst–best | Consistency | Partial | Abstained | Hallucinated | False claims |
| :-- | --: | --: | --: | --: | --: | --: | --: | --: | --: | --: |
| arose26 | 33 | 3.3 of 5 | 7 of 24 | 22.7 of 24 | 31–35 | 89% | 3.7 | 16.3 | 0 | 6 |
| canada_data_agent | 28.7 | 4 of 5 | 4 of 24 | 20.7 of 24 | 28–29 | 96% | 2.7 | 21.7 | 0 | 5 |
| candata_mcp | 27.3 | 2.7 of 5 | 4 of 24 | 20.7 of 24 | 26–29 | 91% | 5 | 20.7 | 0 | 6 |
| maplestats | 49.7 | 3.7 of 5 | 23.3 of 24 | 22.7 of 24 | 49–50 | 92% | 3.3 | 0 | 0 | 0 |
| maplestats-current | 4.7 | 4.7 of 5 | – | – | 4–5 | 80% | 0.3 | 0 | 0 | 0 |
| mcp_canada | 33 | 1.7 of 5 | 9.3 of 24 | 22 of 24 | 31–36 | 79% | 2.7 | 17.3 | 0 | 7 |
| mcp_statcan | 33 | 4 of 5 | 7 of 24 | 22 of 24 | 32–34 | 89% | 3 | 17 | 0 | 6 |
| no_tools | 6 | 1 of 5 | 2.7 of 24 | 2.3 of 24 | 5–7 | 91% | 0.3 | 46.3 | 0.3 | 5 |
| opencanada | 29 | 1.7 of 5 | 6 of 24 | 21.3 of 24 | 27–31 | 79% | 3.7 | 19.7 | 0.7 | 3 |
| openmcp | 37.7 | 3.7 of 5 | 12 of 24 | 22 of 24 | 30–42 | 58% | 3 | 12.3 | 0 | 4 |
| pipeworx | 42 | 2.7 of 5 | 16.7 of 24 | 22.7 of 24 | 41–43 | 89% | 4 | 7 | 0 | 7 |
| statcan2 | 19.3 | 2.3 of 5 | 8.3 of 24 | 8.7 of 24 | 18–21 | 91% | 3.3 | 30 | 0.3 | 8 |

## Citations and cost

- **Key coverage:** share of the answer key's own tables and vectors the answer names.
- **Precision:** of the StatCan vectors and Bank of Canada series an answer cites, the share that hold a figure the answer states (checked against the publishers).
- **Invented:** cited StatCan vectors or tables that do not exist. **Off-table:** a vector cited beside a table it does not belong to.
- **Traceable:** answers stating figures in which at least one cited ID holds one of them. **Release:** answers that mention a release date.

| Arm | Table cov. | Vector cov. | IDs cited | Precision | Invented | Off-table | Traceable | Release | Tool calls | Seconds | Cost (USD) |
| :-- | --: | --: | --: | --: | --: | --: | --: | --: | --: | --: | --: |
| arose26 | 88% | 83% | 151 | 86% | 0 | 0 | 63% | 8% | 3.7 | 14.2 | 0.022 |
| canada_data_agent | 93% | 85% | 122 | 80% | 0 | 0 | 53% | 11% | 2.3 | 14.3 | 0.026 |
| candata_mcp | 88% | 83% | 146 | 82% | 0 | 0 | 68% | 50% | 4.4 | 19.9 | 0.032 |
| maplestats | 88% | 85% | 131 | 87% | 0 | 0 | 48% | 53% | 4.8 | 18.8 | 0.116 |
| maplestats-current | 93% | 63% | 18 | 100% | 0 | 0 | 92% | 80% | 8.2 | 37.4 | 0.175 |
| mcp_canada | 91% | 72% | 122 | 80% | 1 | 0 | 42% | 43% | 8.6 | 40.9 | 0.075 |
| mcp_statcan | 96% | 85% | 141 | 87% | 0 | 0 | 65% | 43% | 4.2 | 16.6 | 0.034 |
| no_tools | 74% | 46% | 41 | 22% | 0 | 1 | 7% | 19% | 0 | 39.6 | 0.013 |
| opencanada | 85% | 49% | 53 | 72% | 0 | 5 | 21% | 24% | 6.0 | 35.2 | 0.037 |
| openmcp | 90% | 83% | 132 | 86% | 0 | 0 | 54% | 45% | 4.5 | 95.0 | 0.053 |
| pipeworx | 90% | 84% | 153 | 81% | 0 | 1 | 53% | 20% | 3.5 | 17.9 | 0.074 |
| statcan2 | 93% | 79% | 123 | 81% | 0 | 0 | 58% | 33% | 3.5 | 15.3 | 0.059 |

## Per question

| Question | arose26 | canada_data_agent | candata_mcp | maplestats | maplestats-current | mcp_canada | mcp_statcan | no_tools | opencanada | openmcp | pipeworx | statcan2 |
| :-- | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: |
| C-01 Labour | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct | – | correct / correct / correct | correct / correct / correct | abstained / abstained* / abstained* | correct / correct / correct | correct / correct / correct | correct / correct / correct | abstained* / abstained* / abstained* |
| C-02 Labour | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct | – | correct / correct / correct | correct / correct / correct | abstained* / abstained* / abstained* | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct |
| C-03 Labour | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct | – | correct / correct / correct | correct / correct / correct | abstained / abstained / abstained* | correct / correct / correct | correct / correct / correct | correct / correct / correct | abstained / abstained / abstained |
| C-04 Labour | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct | – | correct / correct / correct | correct / correct / correct | abstained* / abstained* / abstained* | correct / correct / correct | correct / correct / correct | correct / correct / correct | abstained / abstained / abstained |
| C-05 Labour | partial* / correct / correct | correct / correct / partial* | partial* / partial* / correct | correct / correct / correct | – | correct / correct / correct | correct / correct / correct | abstained* / abstained / abstained | partial* / partial* / partial* | abstained / partial* / correct | correct / correct / correct | correct / correct / correct |
| C-06 Prices | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct | – | correct / correct / correct | correct / correct / correct | abstained* / abstained* / abstained* | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct |
| C-07 Prices | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct | – | correct / correct / correct | correct / correct / correct | abstained* / abstained* / abstained* | correct / correct / correct | correct / correct / correct | correct / correct / correct | abstained / abstained / abstained |
| C-08 Prices | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct | – | correct / correct / correct | correct / correct / correct | abstained* / abstained* / abstained | correct / correct / correct | correct / correct / correct | correct / correct / correct | abstained / abstained / abstained |
| C-09 Prices | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct | – | abstained / correct / correct | correct / correct / correct | abstained* / abstained / abstained* | correct / partial* / correct | correct / correct / correct | correct / correct / correct | abstained / abstained / abstained |
| C-10 Prices | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct | – | correct / correct / correct | correct / correct / correct | abstained* / abstained* / abstained* | correct / correct / correct | correct / correct / abstained | correct / correct / correct | abstained / abstained / abstained |
| C-11 Output | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct | – | correct / correct / correct | correct / correct / correct | abstained / abstained / abstained* | correct / correct / correct | correct / correct / correct | correct / partial* / partial* | hallucinated* / correct / correct |
| C-12 Output | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct | – | correct / correct / correct | correct / correct / correct | abstained* / abstained / abstained* | correct / correct / correct | correct / correct / correct | correct / correct / correct | abstained / abstained / abstained |
| C-13 Output | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct | – | abstained / abstained / correct | correct / correct / correct | abstained* / abstained* / abstained* | partial* / partial* / abstained | correct / correct / correct | correct / correct / correct | abstained / abstained / abstained |
| C-14 Trade | partial* / partial* / partial* | partial* / partial* / partial* | partial* / partial* / partial* | partial* / partial* / partial* | – | partial* / correct / correct | partial* / partial* / partial* | abstained* / abstained / abstained* | correct / correct / correct | partial* / partial* / abstained | correct / partial* / partial* | abstained / abstained / abstained |
| C-15 Housing | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct | – | correct / correct / correct | correct / correct / correct | abstained / abstained / abstained | correct / correct / correct | correct / correct / correct | correct / correct / correct | abstained / abstained / abstained |
| C-16 Housing | correct / correct / correct | correct / correct / correct | correct* / correct* / correct* | correct / partial* / correct | – | correct / abstained / correct | correct / correct / correct | abstained* / abstained / abstained | correct / correct / correct | correct / correct / correct | correct* / correct* / correct* | abstained / abstained / abstained |
| C-17 Population | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct | – | correct / correct / correct | correct / correct / correct | abstained / abstained / abstained | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct |
| C-18 Population | correct / correct / correct* | correct / correct / correct | correct / correct / correct* | correct / correct / correct | – | correct / correct* / correct | correct / correct / correct | abstained / abstained* / abstained | abstained / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct |
| C-19 Markets | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct | – | correct / correct / correct | correct / correct / correct | abstained* / abstained* / abstained* | correct / correct / correct | correct / correct / correct | correct / correct / correct | abstained* / abstained* / abstained* |
| C-20 Markets | correct / correct / correct | abstained* / abstained / abstained* | abstained / abstained / abstained | correct / correct / correct | – | correct / correct / correct | abstained / abstained / abstained | abstained* / abstained* / abstained* | correct / correct / correct | correct / correct / correct | correct / correct / correct | abstained / abstained / abstained |
| C-21 Markets | correct / correct / correct | abstained / abstained / abstained | abstained / abstained / correct | correct / correct / correct | – | correct / correct / correct | correct / correct / correct | abstained / abstained* / abstained* | correct / correct / correct | correct / correct / correct | correct / correct / correct | abstained / abstained / abstained |
| C-22 Unanswerable | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct | – | correct* / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct |
| C-23 Unanswerable | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct | – | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct |
| C-24 Housing | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct | – | abstained* / correct / correct | correct / correct / correct | correct / abstained* / abstained* | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct |
| X-01 Climate | abstained / abstained / abstained | abstained / abstained / abstained | abstained / abstained / abstained | correct / correct / correct | – | correct / correct / correct | abstained / abstained / abstained | abstained* / abstained* / abstained | correct / correct / correct | abstained / correct / correct | correct / correct / correct | abstained / abstained / abstained |
| X-02 Climate | abstained* / abstained / abstained | abstained / abstained / abstained | abstained / abstained / abstained | correct / correct / partial* | – | correct / correct / correct | abstained / abstained / abstained | abstained* / abstained* / abstained* | correct / correct / correct | abstained* / correct / correct | correct / correct / partial* | abstained / abstained / abstained |
| X-03 Hydrometric | abstained / abstained / abstained | abstained* / abstained / abstained* | abstained / abstained / abstained* | correct / correct / correct | – | correct / correct / correct | abstained / abstained / abstained | abstained* / abstained* / abstained* | correct / correct / correct | correct / correct / abstained | abstained / abstained* / abstained | abstained / abstained / abstained |
| X-04 Climate | abstained* / abstained* / abstained* | abstained* / abstained* / abstained* | abstained* / abstained* / abstained* | partial* / correct / correct | – | abstained* / abstained* / abstained* | abstained* / abstained* / abstained* | abstained* / abstained* / abstained* | partial* / partial* / correct | abstained* / abstained* / correct | abstained* / abstained* / abstained* | abstained* / abstained* / abstained* |
| X-05 International | abstained / abstained / abstained | abstained / abstained / abstained | abstained / abstained / abstained | correct / correct / correct | – | abstained / abstained / abstained | abstained / abstained / abstained | abstained / abstained / abstained | abstained / abstained / abstained | abstained / abstained / abstained | correct / correct / correct | abstained / abstained / abstained |
| X-06 International | abstained / abstained / correct | abstained / abstained / abstained | abstained / abstained / abstained | correct / correct / correct | – | abstained / abstained / abstained | abstained / abstained / correct | abstained / abstained / abstained | abstained / correct / abstained | abstained / abstained / abstained | correct / correct / correct | abstained / correct / correct |
| X-07 International | abstained / abstained / abstained | abstained / abstained / abstained | abstained / abstained / abstained | correct / correct / correct | – | abstained / abstained / abstained | abstained / abstained / abstained | abstained / abstained* / abstained | abstained / abstained / abstained | abstained* / correct / abstained | correct / correct / correct | abstained / abstained / abstained |
| X-08 Unanswerable | abstained* / abstained* / abstained* | abstained* / abstained* / abstained* | correct / abstained* / abstained* | correct / correct / correct | – | abstained* / abstained* / abstained* | correct / correct / abstained* | abstained* / abstained* / abstained* | abstained* / abstained* / abstained* | abstained* / correct / abstained* | correct / correct / correct | correct / correct / abstained* |
| X-09 Finance | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct | – | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / hallucinated* / hallucinated* | correct / correct / correct | correct / correct / correct | correct / correct / correct |
| X-10 Finance | abstained / abstained / abstained | abstained / abstained / abstained | abstained / abstained / abstained | correct / correct / correct | – | abstained / abstained / abstained | abstained / abstained / abstained | abstained / abstained* / abstained | abstained / abstained / abstained | abstained / correct / correct | correct / correct / correct | abstained / abstained / abstained |
| X-11 Finance | abstained / abstained / abstained | abstained / abstained / abstained | abstained / abstained* / abstained | correct / correct / correct | – | abstained / abstained / abstained | abstained / partial* / abstained | abstained* / abstained / abstained* | abstained / abstained / abstained | abstained / partial* / correct | correct / correct / correct | abstained / abstained / abstained |
| X-12 Finance | partial* / abstained / partial* | abstained / partial* / abstained | partial* / partial* / partial* | correct / correct / correct | – | abstained / abstained / partial* | partial* / abstained / abstained | abstained / abstained / partial* | abstained / partial* / abstained | abstained / partial* / partial* | partial* / partial* / abstained | partial* / abstained / partial* |
| X-13 Health products | abstained / abstained / abstained | abstained / abstained / abstained | abstained / abstained / abstained | correct / correct / correct | – | correct / abstained / correct | abstained / abstained / abstained | abstained / abstained / abstained* | abstained / abstained* / abstained* | abstained* / correct / correct | correct / correct / correct | abstained / abstained / abstained |
| X-14 Health products | abstained / abstained / abstained | abstained / abstained / abstained | abstained / abstained / abstained | correct / correct / correct | – | correct / correct / correct | abstained / abstained / abstained | abstained* / abstained / abstained | abstained / abstained / abstained | abstained / abstained / correct | correct / correct / correct | abstained / abstained / abstained |
| X-15 Health products | correct / abstained* / correct | correct / correct / correct | correct / abstained* / correct | correct / correct / correct | – | correct / correct / correct | correct / abstained / correct | correct / abstained* / abstained | abstained* / correct / abstained* | abstained* / correct / correct | correct / correct / correct | correct / correct / correct |
| X-16 Health products | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct | – | correct / correct / correct | correct / correct / correct | abstained* / abstained* / correct | partial* / partial* / correct | abstained* / abstained* / correct | correct / correct / correct | correct / correct / correct |
| X-17 Immigration | abstained / abstained / abstained | abstained / abstained / abstained | abstained / abstained / abstained | correct / correct / correct | – | abstained / abstained / abstained | abstained / abstained / abstained* | abstained / abstained / abstained | abstained / abstained / abstained | correct / abstained / correct | abstained / abstained / abstained | abstained / abstained / abstained |
| X-18 Immigration | abstained / abstained / abstained | abstained / abstained / abstained | abstained / abstained / abstained | correct / correct / correct | – | abstained / abstained / abstained | abstained / abstained / abstained | abstained* / abstained / abstained | abstained / abstained / abstained | abstained* / correct / abstained | abstained / abstained / abstained | abstained / abstained / abstained |
| X-19 Immigration | abstained / abstained / abstained | abstained / abstained / abstained | abstained / abstained / abstained | correct / correct / correct | – | abstained / abstained / abstained | abstained / abstained / abstained | abstained* / abstained / abstained | abstained / abstained / abstained | abstained / correct / correct | abstained / abstained / abstained | abstained / abstained / abstained |
| X-20 Immigration | abstained* / abstained* / abstained* | abstained* / abstained* / abstained* | abstained* / abstained* / abstained* | correct / correct / correct | – | abstained* / abstained* / abstained* | abstained* / abstained* / abstained* | abstained* / abstained* / abstained* | abstained* / abstained* / abstained* | correct / correct / correct | abstained* / abstained* / abstained* | abstained* / abstained* / abstained* |
| X-21 Census | correct* / correct* / correct* | abstained / abstained / abstained | abstained / abstained / abstained | correct* / correct* / correct* | – | correct* / abstained* / correct* | correct* / correct* / correct* | abstained / abstained* / abstained* | abstained / abstained / correct* | abstained / correct* / correct* | correct* / correct* / correct* | correct / correct* / correct* |
| X-22 Census | correct* / correct* / correct* | abstained / abstained / abstained | abstained / abstained / abstained | correct* / correct* / correct* | – | abstained / abstained* / abstained | correct* / correct* / correct* | abstained / hallucinated* / abstained | abstained / abstained / abstained | abstained / correct* / correct* | correct* / correct* / correct* | correct* / correct* / correct* |
| X-23 Census | correct / correct / correct | abstained / abstained* / abstained | abstained / abstained / abstained | correct / correct / correct | – | abstained / abstained / abstained | abstained / partial* / correct | abstained / abstained / abstained | abstained / abstained / abstained | abstained / abstained / abstained | correct / correct / correct | correct / correct / correct |
| X-24 Census | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct | – | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct |
| A-01 Analyst | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / abstained* / abstained | correct / correct / correct | abstained / abstained / abstained | abstained / abstained* / abstained* | abstained / correct / correct | correct / correct / correct | correct / correct / correct |
| A-02 Analyst | correct* / partial* / correct* | correct / correct / correct | partial* / correct* / correct | correct / correct / correct | correct / correct / correct | abstained* / correct / correct | correct* / correct / correct* | correct / correct / correct | abstained* / abstained* / abstained* | correct / correct / correct | abstained* / correct* / correct | partial* / correct / partial* |
| A-03 Analyst | correct / partial* / correct | correct / correct / correct | partial* / partial* / partial* | partial* / correct / correct | correct / correct / correct | partial* / partial* / partial* | correct / correct / correct | abstained / abstained / abstained | abstained* / correct / correct | correct / correct / correct | partial* / partial* / partial* | partial* / partial* / partial* |
| A-04 Analyst | partial* / partial* / partial* | partial* / partial* / partial* | partial* / partial* / partial* | partial* / partial* / partial* | correct / correct / partial* | partial* / partial* / partial* | partial* / partial* / partial* | abstained / abstained / abstained* | abstained / abstained / abstained | partial* / partial* / partial* | partial* / partial* / abstained | partial* / partial* / partial* |
| A-05 Analyst | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / abstained* / correct | correct / correct / correct | abstained* / abstained* / abstained* | correct / correct* / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct |

`*` re-graded by hand (see the overrides file).

## False claims

- arose26 X-04: True
- arose26 X-20: True
- arose26 X-04: True
- arose26 X-20: True
- arose26 X-04: True
- arose26 X-20: True
- canada_data_agent A-04: True
- canada_data_agent X-04: True
- canada_data_agent X-04: True
- canada_data_agent X-20: True
- canada_data_agent X-04: True
- candata_mcp X-04: True
- candata_mcp X-20: True
- candata_mcp X-04: True
- candata_mcp X-20: True
- candata_mcp X-04: True
- candata_mcp X-20: True
- mcp_canada A-05: True
- mcp_canada A-04: True
- mcp_canada X-04: True
- mcp_canada X-20: True
- mcp_canada X-20: True
- mcp_canada X-04: True
- mcp_canada X-20: True
- mcp_statcan X-04: True
- mcp_statcan X-20: True
- mcp_statcan X-04: True
- mcp_statcan X-20: True
- mcp_statcan X-04: True
- mcp_statcan X-20: True
- no_tools A-05: True
- no_tools A-05: True
- no_tools A-05: True
- no_tools X-20: True
- no_tools X-04: True
- opencanada X-20: True
- opencanada X-09: True
- opencanada X-09: True
- openmcp A-04: True
- openmcp A-04: True
- openmcp X-04: True
- openmcp X-04: True
- pipeworx A-03: True
- pipeworx A-04: True
- pipeworx A-03: True
- pipeworx X-04: True
- pipeworx X-20: True
- pipeworx X-04: True
- pipeworx X-04: True
- statcan2 A-02: True
- statcan2 C-11: True
- statcan2 X-04: True
- statcan2 X-20: True
- statcan2 X-04: True
- statcan2 C-01: True
- statcan2 X-04: True
- statcan2 X-20: True
