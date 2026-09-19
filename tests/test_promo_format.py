from services.merchant_agent.promo_format import format_offer_bullet, format_surfaced_promotions


def test_format_surfaced_promotions_groups_offers() -> None:
    text = format_surfaced_promotions(
        [
            {
                "id": "1",
                "offer_type": "DISCOUNT",
                "name": "Bulk Saver",
                "description": "Buy 2+ FreshFarm Beans packs and get 10% off.",
                "discount_type": "PERCENT",
                "value": 10,
            },
            {
                "id": "2",
                "offer_type": "COMBO",
                "name": "Breakfast Combo",
                "description": "Buy DairyGold Milk with Madhur Sugar and save Rs 15.",
                "discount_type": "FLAT",
                "value": 1500,
            },
        ]
    )
    assert "Promotions & deals you can unlock" in text
    assert "Buy 2+ FreshFarm Beans" in text
    assert "Breakfast Combo" in text or "DairyGold Milk" in text


def test_format_offer_bullet_festival_campaign() -> None:
    bullet = format_offer_bullet(
        {
            "id": "3",
            "offer_type": "FESTIVAL_CAMPAIGN",
            "name": "Monsoon Pantry Festival",
            "description": "5% cashback on Amul Milk and Fortune Rice basket.",
            "discount_type": "CASHBACK",
            "value": 5,
            "festival_name": "Monsoon Specials",
        }
    )
    assert "Festival campaign" in bullet
    assert "5% cashback" in bullet
    assert "Monsoon Specials" in bullet
