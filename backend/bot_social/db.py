import os
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def database_url() -> str:
    if explicit := os.getenv("DATABASE_URL"):
        return explicit
    if all(os.getenv(name) for name in ("PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD")):
        return URL.create(
            "postgresql+psycopg",
            username=os.environ["PGUSER"],
            password=os.environ["PGPASSWORD"],
            host=os.environ["PGHOST"],
            port=int(os.environ["PGPORT"]),
            database=os.environ["PGDATABASE"],
            query={"sslmode": os.getenv("PGSSLMODE", "prefer")},
        ).render_as_string(hide_password=False)
    return "postgresql+psycopg://bot_social:bot_social@localhost:5432/bot_social"


DATABASE_URL = database_url()
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session
