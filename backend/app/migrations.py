"""Non-destructive, versioned schema bootstrap for this compact project.

Only additive migrations are allowed here. Existing tables/data are never dropped.
"""
from sqlalchemy import text

from .db import Base, engine

SCHEMA_VERSION = "2026_11_22_polza_ai_router_v2"


def apply_migrations() -> None:
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE IF NOT EXISTS schema_migrations (version VARCHAR(120) PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"))
        exists = connection.execute(text("SELECT version FROM schema_migrations WHERE version=:version"), {"version": SCHEMA_VERSION}).first()
    if exists:
        return
    # SQLAlchemy emits dialect-correct CREATE TABLE IF NOT EXISTS statements.
    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO schema_migrations (version) VALUES (:version)"), {"version": SCHEMA_VERSION})
