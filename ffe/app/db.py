import os
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from .config import DATABASE_URL

url = DATABASE_URL
if url.startswith("postgres://"):
    url = url.replace("postgres://", "postgresql+psycopg://", 1)
elif url.startswith("postgresql://"):
    url = url.replace("postgresql://", "postgresql+psycopg://", 1)
if url.startswith("sqlite"):
    os.makedirs("./data", exist_ok=True)
    engine = create_engine(url, connect_args={"check_same_thread": False})
else:
    engine = create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Columns added to tables that already exist in production. create_all() only creates missing tables, so each new column
# is listed here with the SQL that adds it (SQLite and Postgres both accept ADD COLUMN ... DEFAULT) and migrate() applies
# the missing ones at startup. Prefer a new table when you can; when a column is the right model, add it here too.
COLUMN_MIGRATIONS = [
    ("items", "draft", "BOOLEAN NOT NULL DEFAULT FALSE"),           # quick-capture drafts
    ("rooms", "kind", "VARCHAR(10) NOT NULL DEFAULT 'room'"),       # room | area
    ("project_images", "layer", "VARCHAR(20) NOT NULL DEFAULT 'furniture'"),  # what a floor plan shows (config.PLAN_LAYERS)
]


def migrate(eng=None) -> list[str]:
    """Add the columns in COLUMN_MIGRATIONS that the database does not have yet. Returns what was added."""
    eng = eng or engine
    insp = inspect(eng)
    tables = set(insp.get_table_names())
    added = []
    for table, column, ddl in COLUMN_MIGRATIONS:
        if table not in tables:
            continue
        if column in {c["name"] for c in insp.get_columns(table)}:
            continue
        try:
            with eng.begin() as conn:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
        except Exception:
            # another instance (autoscale starts several) may have added it a moment ago; only a still-missing column is an error
            if column not in {c["name"] for c in inspect(eng).get_columns(table)}:
                raise
            continue
        added.append(f"{table}.{column}")
    return added
