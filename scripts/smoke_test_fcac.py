"""Live smoke test for the fcac module: drives FCAC's real credit card and
account comparison tools for every tool, in English and French, per AGENTS.md.

Usage:
    uv run python scripts/smoke_test_fcac.py
"""

from __future__ import annotations

import asyncio
import sys

from maplestats_mcp.modules.fcac import client


async def main() -> int:
    ok = True

    cards = await client.search_credit_cards("ON", limit=200)
    print(f"OK: Ontario credit cards -> {cards.total_listed}")
    # confirmed live 2026-09-26: 95 cards, all with a product id and a purchase rate
    ok &= cards.total_listed > 50 and cards.returned_count == cards.total_listed
    ok &= all(c.purchase_rate is not None and c.annual_fee is not None for c in cards.cards)
    ok &= any(c.rewards for c in cards.cards)

    travel = await client.search_credit_cards(
        "QC", lang="fr", rewards=["travel"], max_annual_fee=0, limit=5
    )
    print(
        f"OK: Quebec no-fee travel cards (fr) -> {travel.total_matched}, e.g. {travel.cards[0].name}"
    )
    ok &= travel.total_matched > 0 and all("Voyages" in c.rewards for c in travel.cards)

    students = await client.search_credit_cards("ON", student=True, limit=200)
    print(f"OK: with student cards -> {students.total_listed}")
    ok &= students.total_listed > cards.total_listed

    last = cards.cards[-1]  # on the last result page, so the detail walk covers paging
    card = await client.get_credit_card(last.product_id, "ON")
    print(
        f"OK: detail {card.name}: fee {card.annual_fee}, purchase {card.purchase_rate}%, "
        f"cash advance {card.cash_advance_rate}%, {len(card.sections)} sections"
    )
    ok &= card.name == last.name and card.purchase_rate is not None
    ok &= any(s.key == "insurance_options" for s in card.sections)

    card_fr = await client.get_credit_card(travel.cards[0].product_id, "QC", lang="fr")
    print(f"OK: detail (fr) {card_fr.name}: {card_fr.foreign_conversion_fee}% conversion")
    ok &= card_fr.name == travel.cards[0].name and card_fr.annual_fee == 0.0

    chequing = await client.search_bank_accounts("ON", limit=200)
    print(f"OK: Ontario chequing accounts -> {chequing.total_listed}")
    ok &= chequing.total_listed > 30 and any(a.low_cost_no_cost for a in chequing.accounts)
    ok &= all(a.monthly_fee is not None for a in chequing.accounts)

    savings = await client.search_bank_accounts(
        "BC", account_type="savings", lang="fr", sort="name", limit=200
    )
    print(f"OK: BC savings accounts (fr) -> {savings.total_listed}")
    ok &= savings.total_listed > 10 and any(a.interest_rate for a in savings.accounts)

    seniors = await client.search_bank_accounts("ON", groups=["senior"], limit=1)
    print(f"OK: chequing with senior accounts -> {seniors.total_listed}")
    ok &= seniors.total_listed > chequing.total_listed

    account = await client.get_bank_account(chequing.accounts[-1].product_id, "ON")
    print(
        f"OK: detail {account.name}: monthly {account.monthly_fee}, NSF {account.nsf_fee}, "
        f"{len(account.sections)} sections"
    )
    ok &= account.monthly_fee is not None and account.nsf_fee is not None
    ok &= any(s.key == "withdraw_fees" for s in account.sections)

    saving = await client.get_bank_account(
        savings.accounts[0].product_id, "BC", account_type="savings", lang="fr"
    )
    print(f"OK: savings detail (fr) {saving.name}: {saving.interest_rates}")
    ok &= bool(saving.interest_rates) and saving.name == savings.accounts[0].name

    print("\nFCAC SMOKE TEST PASSED" if ok else "\nFCAC SMOKE TEST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
