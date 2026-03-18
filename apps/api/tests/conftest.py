import os
import pytest
import pytest_asyncio

# Set required env vars before any app imports
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("DATABASE_URL_SYNC", "postgresql://test:test@localhost/test")
os.environ.setdefault("CLERK_SECRET_KEY", "sk_test_dummy")
os.environ.setdefault("CLERK_PUBLISHABLE_KEY", "pk_test_dummy")
os.environ.setdefault("CLERK_WEBHOOK_SECRET", "whsec_dummy")
os.environ.setdefault("ENCRYPTION_KEY", "a" * 64)

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from src.database import Base, get_db
from src.main import app
import src.models  # noqa: F401 — ensure all models are registered

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def tmp_db():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_db():
        async with Session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.pop(get_db, None)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
