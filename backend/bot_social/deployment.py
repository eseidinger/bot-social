"""Container entry points for the Platform's API and long-running worker services."""

import logging
import sys
import time

import uvicorn
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from .db import engine
from .logging_config import configure_logging
from .web_research import configured_research_hosts
from .workflow import run_forever


def wait_for_schema(poll_seconds: float = 2, timeout_seconds: float = 180) -> None:
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1 FROM jobs LIMIT 1"))
            return
        except SQLAlchemyError as exc:
            if time.monotonic() >= deadline:
                raise RuntimeError("Database schema did not become ready") from exc
            time.sleep(poll_seconds)


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in {"serve", "worker"}:
        raise SystemExit("Usage: python -m bot_social.deployment {serve|worker}")
    configure_logging()
    if sys.argv[1] == "serve":
        migration_config = Config("alembic.ini")
        migration_config.attributes["platform_logging"] = True
        command.upgrade(migration_config, "head")
        uvicorn.run(
            "bot_social.api:app", host="0.0.0.0", port=8080, log_config=None, access_log=False
        )
    else:
        configured_research_hosts()
        wait_for_schema()
        logging.getLogger(__name__).info("Worker ready")
        run_forever()


if __name__ == "__main__":
    main()
