import logging
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from src.config import settings

logger = logging.getLogger(__name__)

engine = create_async_engine(settings.database_url, echo=not settings.is_production)

# `echo=True` makes SQLAlchemy attach its *own* StreamHandler to the
# "sqlalchemy.engine.Engine" logger. Now that logging_config.setup_logging()
# also installs a root handler, every statement would be printed twice — once
# in SQLAlchemy's format, once in ours (confirmed by running a real query).
# Keep SQLAlchemy's output, which is what echo is for, and drop the duplicate.
if engine.echo:
    logging.getLogger("sqlalchemy.engine.Engine").propagate = False
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
            # Debug, not error: the exception is re-raised and gets logged with
            # full context by the request middleware or the Celery task_failure
            # handler. This line only records that a rollback happened, which
            # matters when tracing partial writes.
            logger.debug("db_session rolling back after exception", exc_info=True)
            await session.rollback()
            raise
        finally:
            await session.close()
