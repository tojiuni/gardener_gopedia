from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from gardener_gopedia.config import get_settings

Base = declarative_base()
_engine = None
_SessionLocal = None


def get_engine():
    global _engine, _SessionLocal
    if _engine is None:
        settings = get_settings()
        url = settings.database_url
        connect_args: dict = {}
        if url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
        elif url.startswith("postgresql") and settings.postgres_schema:
            sch = settings.postgres_schema.strip()
            if sch:
                # Put Gardener tables in this schema (create it in Postgres first).
                connect_args["options"] = f"-csearch_path={sch},public"
        _engine = create_engine(url, connect_args=connect_args)
        _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
    return _engine


def init_db() -> None:
    from gardener_gopedia import models  # noqa: F401

    Base.metadata.create_all(bind=get_engine())


def get_session() -> Generator[Session, None, None]:
    get_engine()
    assert _SessionLocal is not None
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()
