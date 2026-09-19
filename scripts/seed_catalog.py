from __future__ import annotations

from pathlib import Path

import pandas as pd

from services.merchant_admin.routers.upload import ingest_catalog_dataframe
from shared.db import AsyncSessionLocal
from shared.redis_client import close_redis_client, get_redis_client


def _seed_file_path() -> Path:
    return Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "sample_catalog.csv"


async def run_seed() -> dict[str, object]:
    seed_file = _seed_file_path()
    dataframe = pd.read_csv(seed_file, dtype=object)
    redis_client = get_redis_client()
    try:
        async with AsyncSessionLocal() as db_session:
            return await ingest_catalog_dataframe(db_session, redis_client, dataframe)
    finally:
        await close_redis_client(redis_client)


if __name__ == "__main__":
    import asyncio

    result = asyncio.run(run_seed())
    print("Seed completed.")
    print(result)
