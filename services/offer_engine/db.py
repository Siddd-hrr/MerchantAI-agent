from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from shared.config import get_settings

settings = get_settings()

offer_engine: AsyncEngine = create_async_engine(
    settings.offer_database_url_resolved,
    echo=False,
    pool_pre_ping=True,
)

OfferSessionLocal = async_sessionmaker(
    bind=offer_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_offer_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with OfferSessionLocal() as session:
        yield session
