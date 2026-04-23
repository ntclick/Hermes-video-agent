"""
Database — Autonomous Content Bridge
SQLite via SQLAlchemy async with session management.
"""
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from backend.config import get_settings


class Base(DeclarativeBase):
    pass


_engine = None
_session_factory = None


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.db_url,
            echo=False,
            connect_args={"check_same_thread": False},
        )
    return _engine


def get_session_factory():
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _session_factory


async def get_db() -> AsyncSession:
    """FastAPI dependency — yields an async database session."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db():
    """Create all tables on startup."""
    engine = get_engine()
    async with engine.begin() as conn:
        from backend.models import Job, XAccount  # noqa: F401
        await conn.run_sync(Base.metadata.create_all)
        # Attempt to add x_account_id if it's an old DB
        try:
            from sqlalchemy import text
            await conn.execute(text("ALTER TABLE jobs ADD COLUMN x_account_id INTEGER"))
        except Exception:
            pass # column already exists or other error
        try:
            from sqlalchemy import text
            await conn.execute(text("ALTER TABLE jobs ADD COLUMN summary TEXT"))
        except Exception:
            pass
        try:
            from sqlalchemy import text
            await conn.execute(text("ALTER TABLE jobs ADD COLUMN frames_path VARCHAR(1024)"))
        except Exception:
            pass
        # Cover video columns
        for col_sql in [
            "ALTER TABLE jobs ADD COLUMN cover_path VARCHAR(1024)",
            "ALTER TABLE jobs ADD COLUMN ai_scenes_path VARCHAR(1024)",
            "ALTER TABLE jobs ADD COLUMN script_json TEXT",
        ]:
            try:
                from sqlalchemy import text
                await conn.execute(text(col_sql))
            except Exception:
                pass


async def close_db():
    """Close engine on shutdown."""
    global _engine
    if _engine:
        await _engine.dispose()
        _engine = None
