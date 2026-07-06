from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.shared.module_registry import BUSINESS_SCHEMAS

settings = get_settings()

_search_path = "public,identity,permission," + ",".join(BUSINESS_SCHEMAS)

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    pool_recycle=1800,  # 30 分钟后强制回收连接，防止残留脏事务
    connect_args={
        "server_settings": {
            "search_path": _search_path,
            # 防御性超时：idle in transaction 超过 10 分钟自动断开，防止连接泄漏
            "idle_in_transaction_session_timeout": "600000",
        }
    },
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession]:
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
