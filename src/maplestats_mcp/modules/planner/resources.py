"""docs:// resources for the planner: the fitness-for-use rules.

Zero-parameter is a hard requirement: any parameter makes FastMCP treat
a decorated function as a ResourceTemplate instead of a FunctionResource.
The text is built from shared/fitness_rules.py, so the notes tool results
carry and this page cannot drift apart.
"""

from __future__ import annotations

from fastmcp.resources import resource

from maplestats_mcp.shared.fitness_rules import RULES, FitnessRule
from maplestats_mcp.shared.i18n import french_text


def _table(product_id: int) -> str:
    digits = str(product_id)
    return f"{digits[:2]}-{digits[2:4]}-{digits[4:]}"


def _rules_doc(french: bool) -> str:
    if french:
        lines = [
            "# Règles d'usage des données",
            "",
            (
                "Des mises en garde courtes sur l'usage d'un chiffre : ce qu'il mesure, "
                "s'il peut être comparé ou additionné, s'il sera révisé. Les résultats des "
                "outils et les plans de plan_query les reprennent quand l'outil ou le tableau "
                "visé correspond. Chaque règle cite les pages officielles sur lesquelles elle "
                "repose. Version anglaise : docs://planner/fitness-rules."
            ),
        ]
    else:
        lines = [
            "# Fitness-for-use rules",
            "",
            (
                "Short cautions on how a number can be used: what it measures, whether it can "
                "be compared or added up, whether it will be revised. Tool results and "
                "plan_query plans carry them when the tool or table matches. Each rule cites "
                "the official pages it rests on. French version: docs://planner/fr/regles-d-usage."
            ),
        ]
    for rule in RULES:
        lines += ["", f"## {rule.title_fr if french else rule.title_en}", ""]
        lines.append(rule.note_fr if french else rule.note_en)
        lines += ["", *_applies(rule, french), "", "Sources :" if french else "Sources:"]
        lines += [f"- {url}" for url in rule.sources]
    text = "\n".join(lines) + "\n"
    # The same no-break spaces the notes get in tool results (fitness.note_text).
    return french_text(text) if french else text


def _applies(rule: FitnessRule, french: bool) -> list[str]:
    out = []
    if rule.tool_prefixes:
        names = ", ".join(f"`{prefix}*`" for prefix in rule.tool_prefixes)
        out.append(f"- {'Outils' if french else 'Tools'}: {names}")
        if rule.exclude_prefixes:
            skipped = ", ".join(f"`{prefix}*`" for prefix in rule.exclude_prefixes)
            out.append(f"- {'Sauf' if french else 'Except'}: {skipped}")
    if rule.product_ids:
        tables = ", ".join(_table(pid) for pid in rule.product_ids)
        out.append(f"- {'Tableaux' if french else 'Tables'}: {tables}")
    if french:
        out = [line.replace(": ", " : ", 1) for line in out]
    return out


@resource("docs://planner/fitness-rules")
def planner_fitness_rules_doc() -> str:
    """Fitness-for-use rules: when and how a Statistics Canada, Bank of Canada or CMHC
    number can be used, with the official sources. French version: docs://planner/fr/regles-d-usage."""
    return _rules_doc(french=False)


@resource("docs://planner/fr/regles-d-usage")
def planner_fitness_rules_doc_fr() -> str:
    """Règles d'usage des données : quand et comment utiliser un chiffre de Statistique
    Canada, de la Banque du Canada ou de la SCHL, avec les sources officielles.
    Version française de docs://planner/fitness-rules."""
    return _rules_doc(french=True)
