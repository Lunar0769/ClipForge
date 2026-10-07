import logging
from pathlib import Path

from sqlalchemy import Engine, inspect, text
from sqlmodel import SQLModel, create_engine

from app import models  # noqa: F401  (registers tables on SQLModel.metadata)

logger = logging.getLogger(__name__)


def add_missing_columns(engine: Engine) -> list[str]:
    """Lightweight forward-only migration: add nullable columns that newer code expects.

    create_all() creates missing tables but never alters existing ones, so a database made by an
    older ClipForge would otherwise break on new columns (e.g. Phase 2's Project.options).
    """
    inspector = inspect(engine)
    added: list[str] = []
    with engine.begin() as conn:
        for table in SQLModel.metadata.sorted_tables:
            if not inspector.has_table(table.name):
                continue
            existing = {col["name"] for col in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing:
                    continue
                if not column.nullable:
                    raise RuntimeError(f"Cannot add required column {table.name}.{column.name} to an existing database")
                ddl_type = column.type.compile(dialect=engine.dialect)
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {ddl_type}'))
                added.append(f"{table.name}.{column.name}")
    if added:
        logger.info("Upgraded database schema: added %s", ", ".join(added))
    return added


def make_engine(url: str) -> Engine:
    connect_args: dict = {}
    if url.startswith("sqlite:///"):
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        connect_args["check_same_thread"] = False
    engine = create_engine(url, connect_args=connect_args)
    SQLModel.metadata.create_all(engine)
    add_missing_columns(engine)
    return engine
