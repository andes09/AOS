from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from src.config import settings

engine = create_async_engine(settings.database_url, echo=not settings.is_production)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with db_session() as session:
        yield session


@asynccontextmanager
async def db_session():
    """
    Same commit/rollback/close contract as `get_db`, as a plain async context
    manager instead of a FastAPI-dependency generator.

    FastMCP tool functions (src/mcp_server/tools.py) aren't FastAPI request
    handlers and can't use `Depends(get_db)`, so they need a session outside
    the DI chain — same need src/services/cost_tracker.py already has, which
    solves it by using `AsyncSessionLocal` directly. This gives tools.py that
    same capability but keeps the commit/rollback/close bookkeeping in one
    place rather than duplicated in every tool.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
