from __future__ import annotations

from services.merchant_agent.memory.procedural import ProceduralMemoryStore
from shared.db import AsyncSessionLocal


async def run_seed() -> dict[str, object]:
    procedural_store = ProceduralMemoryStore()
    async with AsyncSessionLocal() as db_session:
        async with db_session.begin():
            row = await procedural_store.upsert(
                db_session,
                playbook_name="handle_stockout",
                version=1,
                steps=[
                    {"step": 1, "action": "check_cross_sell_preference"},
                    {"step": 2, "action": "fallback_same_name_alternatives"},
                    {"step": 3, "action": "append_creative_promo_stub_safe"},
                ],
            )
        await db_session.commit()
    return {
        "playbook_name": row.playbook_name,
        "version": int(row.version),
        "steps_count": len(row.steps),
    }


if __name__ == "__main__":
    import asyncio

    result = asyncio.run(run_seed())
    print("Memory seed completed.")
    print(result)
