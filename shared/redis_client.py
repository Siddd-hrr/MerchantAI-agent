from redis.asyncio import Redis

from shared.config import get_settings


def get_redis_client(url: str | None = None) -> Redis:
    settings = get_settings()
    redis_url = url or settings.redis_url
    return Redis.from_url(redis_url, encoding="utf-8", decode_responses=True)


async def close_redis_client(redis_client: Redis) -> None:
    await redis_client.aclose()
