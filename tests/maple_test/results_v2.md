# Maple Test v2 results

> Written by `python -m tests.maple_test grade`. Do not edit by hand.

## Answers

Outcomes are per run (mean over repeats; worst and best run beside correct).

| Arm | Correct | Analyst | Beyond | Core | Release | Worst–best | Consistency | Partial | Abstained | Hallucinated | False claims | Referrals |
| :-- | --: | --: | --: | --: | --: | --: | --: | --: | --: | --: | --: | --: |
| arose26 | 29.3 | 3.3 of 5 | 4 of 24 | 22 of 24 | – | 28–31 | 92% | 4.7 | 19 | 0 | 1 | 57 |
| canada_data_agent | 25.3 | 4 of 5 | 2 of 24 | 19.3 of 24 | – | 25–26 | 96% | 2.7 | 24 | 1 | 6 | 63 |
| candata_mcp | 25 | 2.7 of 5 | 1.7 of 24 | 20.7 of 24 | – | 23–27 | 92% | 4.3 | 23.7 | 0 | 0 | 57 |
| maplestats | 48.7 | 3.3 of 5 | 22.7 of 24 | 22.7 of 24 | – | 48–49 | 92% | 4.3 | 0 | 0 | 0 | 0 |
| maplestats-cost | 46 | – | 22 of 24 | 24 of 24 | – | 46–46 | – | 1 | 1 | 0 | 0 | 0 |
| maplestats-current | 5 | 5 of 5 | – | – | – | 5–5 | 100% | 0 | 0 | 0 | 0 | 0 |
| maplestats-release | 7.3 | – | – | – | 7.3 of 8 | 7–8 | 88% | 0 | 0.7 | 0 | 0 | 0 |
| maplestats_after | 52.3 | 5 of 5 | 23.3 of 24 | 24 of 24 | – | 51–53 | 96% | 0.7 | 0 | 0 | 0 | 0 |
| mcp_canada | 31.3 | 1 of 5 | 9 of 24 | 21.3 of 24 | – | 28–34 | 79% | 3.3 | 18 | 0.3 | 2 | 21 |
| mcp_statcan | 30 | 4 of 5 | 4.3 of 24 | 21.7 of 24 | – | 29–31 | 96% | 2.7 | 20 | 0.3 | 1 | 60 |
| no_tools | 4 | 0 of 5 | 2 of 24 | 2 of 24 | – | 4–4 | 92% | 0.3 | 46.3 | 2.3 | 10 | 56 |
| opencanada | 27 | 1.7 of 5 | 4.3 of 24 | 21 of 24 | – | 25–29 | 89% | 4.3 | 20.7 | 1 | 7 | 33 |
| openmcp | 36 | 3 of 5 | 11 of 24 | 22 of 24 | – | 29–41 | 60% | 2.3 | 14 | 0.7 | 6 | 16 |
| pipeworx | 42.7 | 2.7 of 5 | 17.3 of 24 | 22.7 of 24 | – | 41–44 | 89% | 3.7 | 6.7 | 0 | 4 | 18 |
| statcan2 | 11.3 | 2.3 of 5 | 4.3 of 24 | 4.7 of 24 | – | 11–12 | 94% | 4.3 | 37 | 0.3 | 6 | 66 |

## Citations and cost

- **Key coverage:** share of the answer key's own tables and vectors the answer names.
- **Precision:** of the StatCan vectors and Bank of Canada series an answer cites, the share that hold a figure the answer states (checked against the publishers).
- **Invented:** cited StatCan vectors or tables that do not exist. **Off-table:** a vector cited beside a table it does not belong to.
- **Traceable:** answers stating figures in which at least one cited ID holds one of them (a stored value, or one scaled by the series' thousands or millions). **Checked:** the same share among answers that cite a StatCan vector or Bank of Canada series, the only IDs checked; other publishers' IDs are not, so answers on them count as untraceable in the first share. **Release:** answers that mention a release date.

| Arm | Table cov. | Vector cov. | IDs cited | Precision | Invented | Off-table | Traceable | Checked | Release | Tool calls | Seconds | Cost (USD) |
| :-- | --: | --: | --: | --: | --: | --: | --: | --: | --: | --: | --: | --: |
| arose26 | 88% | 83% | 151 | 93% | 0 | 0 | 71% | 98% | 8% | 3.7 | 14.2 | 0.022 |
| canada_data_agent | 93% | 85% | 122 | 93% | 0 | 0 | 62% | 94% | 11% | 2.3 | 14.3 | 0.026 |
| candata_mcp | 88% | 83% | 146 | 83% | 0 | 0 | 69% | 96% | 50% | 4.4 | 19.9 | 0.032 |
| maplestats | 88% | 85% | 131 | 94% | 0 | 0 | 52% | 94% | 53% | 4.8 | 18.8 | 0.116 |
| maplestats-cost | 90% | 90% | 31 | 84% | 0 | 0 | 49% | 91% | 48% | 4.0 | 28.7 | 0.057 |
| maplestats-current | 93% | 63% | 18 | 100% | 0 | 0 | 92% | 100% | 80% | 8.2 | 37.4 | 0.175 |
| maplestats-release | 100% | 100% | 0 | – | 0 | 0 | 0% | – | 100% | 3.9 | 30.2 | 0.044 |
| maplestats_after | 91% | 88% | 116 | 94% | 0 | 0 | 54% | 96% | 54% | 5.3 | 15.5 | 0.074 |
| mcp_canada | 91% | 72% | 122 | 86% | 1 | 0 | 46% | 90% | 43% | 8.6 | 40.9 | 0.075 |
| mcp_statcan | 96% | 85% | 141 | 96% | 0 | 0 | 73% | 98% | 43% | 4.2 | 16.6 | 0.034 |
| no_tools | 74% | 46% | 41 | 22% | 0 | 1 | 7% | 38% | 19% | 0 | 39.6 | 0.013 |
| opencanada | 85% | 49% | 53 | 72% | 0 | 5 | 21% | 96% | 24% | 6.0 | 35.2 | 0.037 |
| openmcp | 90% | 83% | 132 | 92% | 0 | 0 | 58% | 94% | 45% | 4.5 | 95.0 | 0.053 |
| pipeworx | 90% | 84% | 153 | 86% | 0 | 1 | 55% | 95% | 20% | 3.5 | 17.9 | 0.074 |
| statcan2 | 93% | 79% | 123 | 89% | 0 | 0 | 66% | 95% | 33% | 3.5 | 15.3 | 0.059 |

## Per question

| Question | arose26 | canada_data_agent | candata_mcp | maplestats | maplestats-cost | maplestats-current | maplestats-release | maplestats_after | mcp_canada | mcp_statcan | no_tools | opencanada | openmcp | pipeworx | statcan2 |
| :-- | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: |
| C-01 Labour | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct | – | – | correct / correct / correct | correct / hallucinated* / correct | correct / correct / correct | abstained / abstained* / abstained* | correct / correct / correct | correct / correct / correct | correct / correct / correct | abstained* / abstained* / abstained* |
| C-02 Labour | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct | – | – | correct / correct / correct | correct / correct / correct | correct / correct / correct | abstained* / abstained* / abstained* | correct / correct / correct | correct / correct / correct | correct / correct / correct | abstained* / abstained* / abstained* |
| C-03 Labour | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct | – | – | correct / correct / correct | correct / correct / correct | correct / correct / correct | abstained / abstained / abstained* | correct / correct / correct | correct / correct / correct | correct / correct / correct | abstained / abstained / abstained |
| C-04 Labour | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct | – | – | correct / correct / correct | correct / correct / correct | correct / correct / correct | abstained* / abstained* / abstained* | correct / correct / correct | correct / correct / correct | correct / correct / correct | abstained / abstained / abstained |
| C-05 Labour | partial / correct / correct | correct / correct / partial | partial / partial / correct | correct / correct / correct | correct | – | – | correct / correct / correct | correct / correct / correct | correct / correct / correct | abstained* / abstained / abstained | partial / partial / partial | abstained / partial / correct | correct / correct / correct | abstained* / abstained* / abstained* |
| C-06 Prices | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct | – | – | correct / correct / correct | correct / correct / correct | correct / correct / correct | abstained* / abstained* / abstained* | correct / correct / correct | correct / correct / correct | correct / correct / correct | abstained* / abstained* / abstained* |
| C-07 Prices | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct | – | – | correct / correct / correct | correct / correct / correct | correct / correct / correct | abstained* / abstained* / abstained* | correct / correct / correct | correct / correct / correct | correct / correct / correct | abstained / abstained / abstained |
| C-08 Prices | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct | – | – | correct / correct / correct | correct / correct / correct | correct / correct / correct | abstained* / abstained* / abstained | correct / correct / correct | correct / correct / correct | correct / correct / correct | abstained / abstained / abstained |
| C-09 Prices | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct | – | – | correct / correct / correct | abstained / correct / correct | correct / correct / correct | abstained* / abstained / abstained* | correct / hallucinated / correct | correct / correct / correct | correct / correct / correct | abstained / abstained / abstained |
| C-10 Prices | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct | – | – | correct / correct / correct | correct / correct / correct | correct / correct / correct | abstained* / abstained* / abstained* | correct / correct / correct | correct / correct / abstained | correct / correct / correct | abstained / abstained / abstained |
| C-11 Output | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct | – | – | correct / correct / correct | correct / correct / correct | correct / correct / correct | abstained / abstained / abstained* | correct / correct / correct | correct / correct / correct | correct / partial* / partial* | hallucinated / correct / correct |
| C-12 Output | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct | – | – | correct / correct / correct | correct / correct / correct | correct / correct / correct | abstained* / abstained / abstained* | correct / correct / correct | correct / correct / correct | correct / correct / correct | abstained / abstained / abstained |
| C-13 Output | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct | – | – | correct / correct / correct | partial* / abstained / correct | correct / correct / correct | abstained* / abstained* / abstained* | partial* / partial* / partial* | correct / correct / correct | correct / correct / correct | abstained / abstained / abstained |
| C-14 Trade | partial* / partial* / partial* | partial* / partial* / partial* | partial* / partial* / partial* | partial* / partial* / partial* | correct* | – | – | correct / correct / correct | partial* / partial* / correct | partial* / partial* / partial* | abstained* / abstained / abstained* | correct / correct / correct | partial* / partial* / abstained | correct / partial* / partial* | abstained / abstained / abstained |
| C-15 Housing | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct | – | – | correct / correct / correct | correct / correct / correct | correct / correct / correct | abstained / abstained / abstained | correct / correct / correct | correct / correct / correct | correct / correct / correct | abstained / abstained / abstained |
| C-16 Housing | correct / correct / correct | correct / correct / correct | correct* / correct* / correct* | correct / partial* / correct | correct | – | – | correct / correct / correct | correct / abstained / correct | correct / correct / correct | abstained* / abstained / abstained | correct / correct / correct | correct / correct / correct | correct* / correct* / correct* | abstained / abstained / abstained |
| C-17 Population | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct | – | – | correct / correct / correct | correct / correct / correct | correct / correct / correct | abstained / abstained / abstained | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct |
| C-18 Population | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct | – | – | correct / correct / correct | correct / correct / correct | correct / correct / correct | abstained / abstained* / abstained | abstained / abstained* / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct |
| C-19 Markets | correct / correct / correct | hallucinated* / hallucinated* / hallucinated* | correct / correct / correct | correct / correct / correct | correct | – | – | correct / correct / correct | correct / correct / correct | correct / hallucinated* / correct | abstained* / abstained* / abstained* | correct / correct / correct | correct / correct / correct | correct / correct / correct | abstained* / abstained* / abstained* |
| C-20 Markets | correct / correct / correct | abstained* / abstained / abstained* | abstained / abstained / abstained | correct / correct / correct | correct | – | – | correct / correct / correct | correct / correct / correct | abstained / abstained / abstained | abstained* / abstained* / abstained* | correct / correct / correct | correct / correct / correct | correct / correct / correct | abstained / abstained / abstained |
| C-21 Markets | correct / correct / correct | abstained / abstained / abstained | abstained / abstained / correct | correct / correct / correct | correct | – | – | correct / correct / correct | correct / correct / correct | correct / correct / correct | abstained / abstained* / abstained* | correct / correct / correct | correct / correct / correct | correct / correct / correct | abstained / abstained / abstained |
| C-22 Unanswerable | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct | – | – | correct / correct / correct | correct* / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct |
| C-23 Unanswerable | correct / correct / correct | partial* / correct / correct | correct / correct / correct | correct / correct / correct | correct | – | – | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct |
| C-24 Housing | partial / partial / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct | – | – | correct / correct / correct | abstained / correct / correct | correct / correct / correct | partial / abstained* / abstained* | correct / correct / correct | correct / correct / correct | correct / correct / correct | partial / partial / partial |
| X-01 Climate | abstained / abstained / abstained | abstained / abstained / abstained | abstained / abstained / abstained | correct / correct / correct | correct | – | – | correct / correct / correct | correct / correct / correct | abstained / abstained / abstained | abstained* / abstained* / abstained | correct / correct / correct | abstained / correct / correct | correct / correct / correct | abstained / abstained / abstained |
| X-02 Climate | abstained* / abstained / abstained | abstained / abstained / abstained | abstained / abstained / abstained | correct / correct / partial* | correct | – | – | correct / partial* / correct | correct / correct / correct | abstained / abstained / abstained | abstained* / abstained* / abstained* | correct / correct / correct | abstained* / correct / correct | correct / correct / partial* | abstained / abstained / abstained |
| X-03 Hydrometric | abstained / abstained / abstained | abstained* / abstained / abstained* | abstained / abstained / abstained* | correct / correct / correct | correct | – | – | correct / correct / correct | correct / correct / correct | abstained / abstained / abstained | abstained* / abstained* / abstained* | correct / correct / correct | correct / correct / abstained | abstained / abstained* / abstained | abstained / abstained / abstained |
| X-04 Climate | abstained* / abstained* / abstained* | abstained* / abstained* / abstained* | abstained* / abstained* / abstained* | partial* / partial / partial* | partial | – | – | correct / partial / correct | abstained* / abstained* / abstained* | abstained* / abstained* / abstained* | abstained / abstained* / abstained* | partial* / partial* / partial | abstained* / abstained* / abstained* | abstained* / abstained* / abstained* | abstained* / abstained* / abstained* |
| X-05 International | abstained / abstained / abstained | abstained / abstained / abstained | abstained / abstained / abstained | correct / correct / correct | correct | – | – | correct / correct / correct | abstained / abstained / abstained | abstained / abstained / abstained | abstained / hallucinated* / abstained | abstained / abstained / abstained | abstained / abstained / abstained | correct / correct / correct | abstained / abstained / abstained |
| X-06 International | abstained / abstained / abstained* | abstained / abstained / abstained | abstained / abstained / abstained | correct / correct / correct | correct | – | – | correct / correct / correct | abstained / abstained / abstained | abstained / abstained / abstained* | abstained / abstained / abstained | abstained / abstained* / abstained | abstained / abstained / abstained | correct / correct / correct | abstained / abstained* / abstained* |
| X-07 International | abstained / abstained / abstained | abstained / abstained / abstained | abstained / abstained / abstained | correct / correct / correct | correct | – | – | correct / correct / correct | abstained / abstained / abstained | abstained / abstained / abstained | abstained / abstained* / abstained | abstained / abstained / abstained | abstained* / correct / abstained | correct / correct / correct | abstained / abstained / abstained |
| X-08 Unanswerable | abstained / abstained / abstained | abstained / abstained / abstained | abstained* / abstained / abstained | correct / correct / correct | correct | – | – | correct / correct / correct | abstained / abstained / abstained | abstained* / abstained* / abstained | abstained* / abstained* / abstained* | abstained / abstained / abstained | abstained / abstained* / abstained | correct / correct / correct | abstained* / abstained* / abstained |
| X-09 Finance | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct | – | – | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / hallucinated / hallucinated | correct / correct / correct | correct / correct / correct | correct / correct / correct |
| X-10 Finance | abstained / abstained / abstained | abstained / abstained / abstained | abstained / abstained / abstained | correct / correct / correct | correct | – | – | correct / correct / correct | abstained / abstained / abstained | abstained / abstained / abstained | abstained / abstained* / abstained | abstained / abstained / abstained | abstained / correct / correct | correct / correct / correct | abstained / abstained / abstained |
| X-11 Finance | abstained / abstained / abstained | abstained / abstained / abstained | abstained / abstained* / abstained | correct / correct / correct | correct | – | – | correct / correct / correct | abstained / abstained / abstained | abstained / abstained* / abstained | abstained* / abstained / abstained* | abstained / abstained / abstained | abstained / abstained* / correct | correct / correct / correct | abstained / abstained / abstained |
| X-12 Finance | abstained* / abstained / abstained* | abstained / abstained* / abstained | abstained* / abstained* / abstained* | correct / correct / correct | correct | – | – | correct / correct / correct | abstained / abstained / abstained* | abstained* / abstained / abstained | abstained / abstained / abstained* | abstained / abstained* / abstained | abstained / abstained* / abstained* | correct / correct / correct | abstained* / abstained / abstained* |
| X-13 Health products | abstained / abstained / abstained | abstained / abstained / abstained | abstained / abstained / abstained | correct / correct / correct | correct | – | – | correct / correct / correct | correct / abstained / correct | abstained / abstained / abstained | abstained / abstained / abstained* | abstained / abstained* / abstained* | abstained* / correct / correct | correct / correct / correct | abstained / abstained / abstained |
| X-14 Health products | abstained / abstained / abstained | abstained / abstained / abstained | abstained / abstained / abstained | correct / correct / correct | correct | – | – | correct / correct / correct | correct / correct / correct | abstained / abstained / abstained | abstained* / abstained / abstained | abstained / abstained / abstained | abstained / abstained / correct | correct / correct / correct | abstained / abstained / abstained |
| X-15 Health products | abstained* / abstained* / abstained* | abstained* / abstained* / abstained* | abstained* / abstained* / abstained* | correct / correct / correct | correct | – | – | correct / correct / correct | correct / correct / correct | abstained* / abstained / abstained* | abstained* / abstained* / abstained | abstained* / abstained* / abstained* | abstained* / abstained* / correct | correct / correct / correct | abstained* / abstained* / abstained* |
| X-16 Health products | abstained* / abstained* / abstained* | abstained* / abstained* / abstained* | abstained* / abstained* / abstained* | correct / correct / correct | correct | – | – | correct / correct / correct | correct / correct / correct | abstained* / abstained* / abstained* | abstained* / abstained* / abstained* | partial* / partial* / partial* | abstained* / abstained* / correct | correct / correct / correct | abstained* / abstained* / abstained* |
| X-17 Immigration | abstained / abstained / abstained | abstained / abstained / abstained | abstained / abstained / abstained | correct / correct / correct | correct | – | – | correct / correct / correct | abstained / abstained / abstained | abstained / abstained / abstained* | abstained / abstained / abstained | abstained / abstained / abstained | correct / abstained / correct | abstained / abstained / abstained | abstained / abstained / abstained |
| X-18 Immigration | abstained / abstained / abstained | abstained / abstained / abstained | abstained / abstained / abstained | correct / correct / correct | correct | – | – | correct / correct / correct | abstained / abstained / abstained | abstained / abstained / abstained | abstained* / abstained / abstained | abstained / abstained / abstained | abstained* / correct / abstained | abstained / abstained / abstained | abstained / abstained / abstained |
| X-19 Immigration | abstained / abstained / abstained | abstained / abstained / abstained | abstained / abstained / abstained | correct / correct / correct | correct | – | – | correct / correct / correct | abstained / abstained / abstained | abstained / abstained / abstained | abstained* / abstained / abstained | abstained / abstained / abstained | abstained / correct / correct | abstained / abstained / abstained | abstained / abstained / abstained |
| X-20 Immigration | abstained / abstained / abstained* | abstained / abstained* / abstained | abstained / abstained* / abstained | correct / correct / correct | correct | – | – | correct / correct / correct | abstained / abstained / abstained | abstained / abstained / abstained | abstained / abstained / abstained | abstained / abstained / abstained | correct / correct / correct | abstained* / abstained / abstained | abstained / abstained / abstained |
| X-21 Census | correct / correct / correct | abstained / abstained / abstained | abstained / abstained / abstained | correct / correct / correct | correct | – | – | correct / correct / correct | correct / abstained* / correct | correct / correct / correct | abstained / abstained* / abstained* | abstained / abstained / correct | abstained / correct / correct | correct / correct / correct | correct / correct / correct |
| X-22 Census | correct / correct / correct | abstained / abstained / abstained | abstained / abstained / abstained | correct / correct / correct | abstained | – | – | correct / correct / correct | abstained / abstained* / abstained | correct / correct / correct | hallucinated* / hallucinated / hallucinated* | abstained / abstained / abstained | hallucinated* / correct / correct | correct / correct / correct | correct / correct / correct |
| X-23 Census | correct / correct / correct | abstained / abstained* / abstained | abstained / abstained / abstained | correct / correct / correct | correct | – | – | correct / correct / correct | abstained / abstained / abstained | partial* / partial* / correct | hallucinated* / hallucinated* / abstained | abstained / abstained / abstained | abstained / abstained / hallucinated* | correct / correct / correct | correct / correct / correct |
| X-24 Census | partial / partial / partial | correct / correct / correct | partial / correct / correct | correct / correct / correct | correct | – | – | correct / correct / correct | correct* / correct* / partial | correct / correct / correct | correct / correct / correct | correct / partial / correct* | correct / correct / correct | correct* / correct* / partial | correct / partial / partial |
| A-01 Analyst | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct | – | correct / correct / correct | – | correct / correct / correct | correct / abstained* / abstained | correct / correct / correct | abstained / abstained / abstained | abstained / abstained* / abstained* | abstained / correct / correct | correct / correct / correct | correct / correct / correct |
| A-02 Analyst | correct / partial* / correct | correct / correct / correct | partial* / correct / correct | correct / correct / partial* | – | correct / correct / correct | – | correct / correct / correct | abstained / abstained / abstained | correct / correct / correct | abstained / abstained / abstained | abstained / abstained / abstained | abstained / partial* / correct | abstained / correct / correct | partial* / correct / partial* |
| A-03 Analyst | correct / partial* / correct | correct / correct / correct | partial / partial* / partial* | partial / correct / correct | – | correct / correct / correct | – | correct / correct / correct | partial / partial / partial | correct / correct / correct | abstained / abstained / abstained | abstained* / correct / correct | correct / correct / correct | partial / partial / partial | partial / partial* / partial* |
| A-04 Analyst | partial / partial / partial | partial / partial / partial | partial / partial / partial | partial / partial / partial | – | correct / correct / correct | – | correct / correct / correct | partial / partial / partial | partial / partial / partial | abstained / hallucinated* / abstained* | abstained / abstained / abstained | partial / partial / partial | partial / partial / abstained | partial / partial / partial |
| A-05 Analyst | correct / correct / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct | – | correct / correct / correct | – | correct / correct / correct | correct / abstained* / correct | correct / correct / correct | abstained / abstained / abstained | correct / correct* / correct | correct / correct / correct | correct / correct / correct | correct / correct / correct |
| R-01 Release | – | – | – | – | – | – | correct / correct / correct | – | – | – | – | – | – | – | – |
| R-02 Release | – | – | – | – | – | – | correct / correct / correct | – | – | – | – | – | – | – | – |
| R-03 Release | – | – | – | – | – | – | correct / correct / correct | – | – | – | – | – | – | – | – |
| R-04 Release | – | – | – | – | – | – | correct / correct / correct | – | – | – | – | – | – | – | – |
| R-05 Release | – | – | – | – | – | – | correct / correct / correct | – | – | – | – | – | – | – | – |
| R-06 Release | – | – | – | – | – | – | abstained* / abstained* / correct | – | – | – | – | – | – | – | – |
| R-07 Release | – | – | – | – | – | – | correct / correct / correct | – | – | – | – | – | – | – | – |
| R-08 Release | – | – | – | – | – | – | correct / correct / correct | – | – | – | – | – | – | – | – |

`*` re-graded by hand (see the overrides file).

## False claims

- arose26 X-12: Says the Federal Reserve's household debt service ratio includes some rent and lease payments; those are in the Fed's financial obligations ratio, not the DSR.
- canada_data_agent A-03: Says the figures are in current dollars (not adjusted for inflation); table 11-10-0239 is in constant 2024 dollars.
- canada_data_agent A-04: Says the CIS figures are in current dollars; table 11-10-0190 is in constant 2024 dollars.
- canada_data_agent C-21: Says the BCPI is not in a Statistics Canada table; StatCan republishes it in 10-10-0132-01.
- canada_data_agent X-04: Gives Toronto Intl A's climate ID as 6158733; that is the Pearson station closed in 2013 (Toronto Intl A is 6158731).
- canada_data_agent C-14: Says the customs basis is the basis of the headline trade release; Statistics Canada's monthly trade release is on a balance-of-payments basis.
- canada_data_agent C-21: Says the BCPI isn't published in Statistics Canada tables and gives its base as 2010=100; StatCan republishes it in 10-10-0132-01, base 1972=100.
- mcp_canada A-05: Points to an Alberta vector in table 11-10-0090-01 and tells the user to select Geography = Alberta; the table is Canada only.
- mcp_canada A-04: Says the CIS figure is in current dollars; table 11-10-0237 is in constant 2024 dollars.
- mcp_statcan X-02: Gives Ottawa CDA's climate ID as 6105978; that is Ottawa CDA RCS, and Ottawa CDA is 6105976.
- no_tools A-05: Says the poverty rate by disability status is published for the provinces, including Alberta; 11-10-0090 is Canada only.
- no_tools A-05: Says table 11-10-0090-01 has provincial breakdowns and to set Geography to Alberta; it is Canada only.
- no_tools A-05: Says the CIS publishes the poverty rate by disability status with provincial breakdowns and the CSD reports one by province; no Alberta rate is published.
- no_tools A-04: Says table 11-10-0237-01 gives median income of households by household size; it reports economic families and persons not in an economic family.
- no_tools A-04: Says table 11-10-0237-01 reports household-level medians; it reports economic families and persons not in an economic family.
- no_tools X-12: Says the Federal Reserve's household debt service ratio includes rent and auto lease payments; those are in the financial obligations ratio, not the DSR.
- no_tools C-05: Describes table 14-10-0371-01 as seasonally adjusted; it is the unadjusted monthly table (the adjusted one is 14-10-0432-01).
- no_tools C-14: Says the headline figure in The Daily is seasonally adjusted, customs basis; Statistics Canada's monthly trade release is on a balance-of-payments basis.
- no_tools X-12: Says the US household debt service ratio includes rent and auto lease payments; those are in the Fed's financial obligations ratio, not the DSR.
- no_tools C-17: Says Statistics Canada has not published British Columbia's July 1, 2026 estimate (due in December); it was released on 2026-09-23 (5,710,598).
- opencanada A-04: Says Statistics Canada doesn't publish a household median; the 2021 Census Profile does (median total income of household, $96,000 for Alberta).
- opencanada C-19: Reads series V80691310 (the Bank Rate) as the overnight target, and so says the target was 2.50% from September 2; the target was 2.25% until October 28.
- opencanada C-19: Reads series V80691310 (the Bank Rate) as the overnight target, and so says the target was 2.50% from September 2; the target was 2.25% until October 28.
- opencanada X-09: Presents series V80691310 (the Bank Rate, 25 bp above the target) as the target for the overnight rate.
- opencanada X-14: Concludes from an empty lookup that the Drug Product Database has no product under DIN 02242705; it lists AROMASIN (exemestane 25 mg).
- opencanada C-19: Reads series V80691310 (the Bank Rate) as the overnight target, and so says the target was 2.50% from September 2; the target was 2.25% until October 28.
- opencanada X-09: Presents series V80691310 (the Bank Rate, 25 bp above the target) as the target for the overnight rate.
- openmcp A-03: Says the figures are in current dollars (not adjusted for inflation); table 11-10-0239 is in constant 2024 dollars.
- openmcp A-04: Says the CIS figure is in current dollars; table 11-10-0237 is in constant 2024 dollars.
- openmcp A-03: Says the figures are in current dollars (not adjusted for inflation); table 11-10-0239 is in constant 2024 dollars.
- openmcp A-04: Says the CIS figure is in current dollars; table 11-10-0190 is in constant 2024 dollars.
- openmcp A-03: Says the figures are in current dollars (not adjusted for inflation); table 11-10-0239 is in constant 2024 dollars.
- openmcp C-21: States the index base as 2012=100; the BCPI is 1972=100.
- pipeworx A-03: Says the figures are in current dollars (not adjusted for inflation); table 11-10-0239 is in constant 2024 dollars.
- pipeworx A-04: Says the CIS figure is in current dollars; table 11-10-0190 is in constant 2024 dollars.
- pipeworx A-03: Says the figures are in current dollars (not adjusted for inflation); table 11-10-0239 is in constant 2024 dollars.
- pipeworx C-14: Calls the seasonally adjusted customs-basis figure the headline measure; Statistics Canada's monthly trade release is on a balance-of-payments basis.
- statcan2 A-02: Calls July 2026 the latest month available; August 2026 was published on 2026-10-29.
- statcan2 A-02: Calls July 2026 the latest month; August 2026 was published on 2026-10-29.
- statcan2 C-11: Presents the 0.8% quarter-over-quarter change as the annualized rate; annualized growth was 3.3%.
- statcan2 C-21: Says table 10-10-0132-01 is a different, older index and not the BCPI; it is the Bank of Canada's BCPI (Fisher index, US dollars, 1972=100) as republished by Statistics Canada.
- statcan2 C-23: Calls the Q1 and Q2 2026 changes (0.1%, 0.8%) annualized rates; they are quarter-over-quarter changes (Q2 annualized was 3.3%).
- statcan2 C-01: Says the September 2026 figures should appear in the next release; they were published on 2026-10-09.

## Direction of the hand review

Re-grades that changed the grader's outcome, by arm. A review that favoured one arm would raise it and lower the others; correct answers gained and lost are the ones that move the score.

| Arm | Answers | Raised | Lowered | Correct gained | Correct lost | Net correct per run |
| :-- | --: | --: | --: | --: | --: | --: |
| arose26 | 159 | 13 | 6 | 0 | 6 | -2.0 |
| canada_data_agent | 159 | 13 | 10 | 0 | 10 | -3.3 |
| candata_mcp | 159 | 19 | 6 | 3 | 6 | -1.0 |
| maplestats | 159 | 8 | 0 | 0 | 0 | +0.0 |
| maplestats-cost | 48 | 1 | 0 | 1 | 0 | +1.0 |
| maplestats-current | 15 | 0 | 0 | 0 | 0 | +0.0 |
| maplestats-release | 24 | 0 | 1 | 0 | 1 | -0.3 |
| maplestats_after | 159 | 1 | 0 | 0 | 0 | +0.0 |
| mcp_canada | 159 | 12 | 3 | 3 | 3 | +0.0 |
| mcp_statcan | 159 | 11 | 9 | 0 | 9 | -3.0 |
| no_tools | 159 | 71 | 8 | 0 | 2 | -0.7 |
| opencanada | 159 | 17 | 4 | 2 | 4 | -0.7 |
| openmcp | 159 | 16 | 4 | 0 | 2 | -0.7 |
| pipeworx | 159 | 15 | 0 | 5 | 0 | +1.7 |
| statcan2 | 159 | 15 | 19 | 0 | 19 | -6.3 |
