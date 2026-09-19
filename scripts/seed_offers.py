from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, select

from shared.db import AsyncSessionLocal
from shared.models.cross_sell import CrossSellPreference
from shared.models.item import Item
from shared.models.offer import Offer

SEED_ITEM_LOOKUPS: dict[str, tuple[str, str]] = {
    "beans_freshfarm": ("Beans", "FreshFarm"),
    "beans_homeselect": ("Beans", "HomeSelect"),
    "milk_dairygold": ("Milk", "DairyGold"),
    "milk_amul": ("Milk", "Amul"),
    "rice_fortune": ("Rice", "Fortune"),
    "sugar_madhur": ("Sugar", "Madhur"),
}


async def _resolve_item_id(db_session, name: str, brand: str) -> UUID:
    item = (
        await db_session.execute(
            select(Item).where(
                and_(
                    func.lower(Item.name) == name.lower(),
                    func.lower(Item.brand) == brand.lower(),
                )
            )
        )
    ).scalar_one_or_none()
    if item is None:
        raise RuntimeError(f"Could not resolve item by name+brand: {name} ({brand})")
    return item.id


async def run_seed() -> dict[str, Any]:
    async with AsyncSessionLocal() as db_session:
        resolved_item_ids = {
            key: await _resolve_item_id(db_session, name, brand)
            for key, (name, brand) in SEED_ITEM_LOOKUPS.items()
        }

        offers = [
            Offer(
                offer_type="DISCOUNT",
                name="FreshFarm Beans Bulk Saver",
                description="Buy 2+ FreshFarm Beans packs and get 10% off.",
                item_ids=[str(resolved_item_ids["beans_freshfarm"])],
                condition={"min_qty": 2},
                discount_type="PERCENT",
                value=10,
            ),
            Offer(
                offer_type="DISCOUNT",
                name="Fortune Rice Family Deal",
                description="Flat Rs 30 off on Fortune Rice when buying one 5kg pack.",
                item_ids=[str(resolved_item_ids["rice_fortune"])],
                condition={"min_qty": 1},
                discount_type="FLAT",
                value=3000,
            ),
            Offer(
                offer_type="COMBO",
                name="Breakfast Combo",
                description="Buy DairyGold Milk with Madhur Sugar and save Rs 15.",
                item_ids=[str(resolved_item_ids["milk_dairygold"])],
                combo_with_item_ids=[str(resolved_item_ids["sugar_madhur"])],
                condition={"min_qty_each": 1},
                discount_type="FLAT",
                value=1500,
            ),
            Offer(
                offer_type="COUPON",
                name="Weekend Coupon",
                description="Use code SAVE20 for Rs 20 off orders above Rs 500.",
                item_ids=None,
                condition={"min_bill_paise": 50000},
                discount_type="FLAT",
                value=2000,
                coupon_code="SAVE20",
            ),
            Offer(
                offer_type="FESTIVAL_CAMPAIGN",
                name="Monsoon Pantry Festival",
                description="5% cashback on Amul Milk and Fortune Rice basket.",
                item_ids=[str(resolved_item_ids["milk_amul"]), str(resolved_item_ids["rice_fortune"])],
                condition={"min_qty_total": 2},
                discount_type="CASHBACK",
                value=5,
                festival_name="Monsoon Specials",
            ),
        ]

        cross_sell_preference = CrossSellPreference(
            source_item_id=resolved_item_ids["beans_homeselect"],
            target_item_ids=[str(resolved_item_ids["beans_freshfarm"])],
            priority=1,
            is_active=True,
        )

        inserted_offers = 0
        for offer in offers:
            existing_offer = (
                await db_session.execute(
                    select(Offer).where(
                        func.lower(Offer.name) == offer.name.lower(),
                        Offer.offer_type == offer.offer_type,
                    )
                )
            ).scalar_one_or_none()
            if existing_offer is None:
                db_session.add(offer)
                inserted_offers += 1

        existing_cross_sell = (
            await db_session.execute(
                select(CrossSellPreference).where(
                    CrossSellPreference.source_item_id == cross_sell_preference.source_item_id
                )
            )
        ).scalar_one_or_none()
        if existing_cross_sell is None:
            db_session.add(cross_sell_preference)

        await db_session.commit()
        return {
            "inserted_offers": inserted_offers,
            "cross_sell_source_item_id": str(cross_sell_preference.source_item_id),
            "resolved_items": {key: str(value) for key, value in resolved_item_ids.items()},
        }


if __name__ == "__main__":
    import asyncio

    result = asyncio.run(run_seed())
    print("Offer seed completed.")
    print(result)
