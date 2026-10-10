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
    ("project_images", "layer", "VARCHAR(20) NOT NULL DEFAULT 'main'"),  # what a floor plan shows (a plan_layers key, layers.py)
    ("item_photos", "thumb_key", "VARCHAR(255) NOT NULL DEFAULT ''"),  # the small copy of a photo ('' = not made yet, '-' = cannot be made)
]

# Data fixes for rows written by an older version. Each must be idempotent (safe to run at every start, by several instances):
# the main plan of a floor used to be stored as "furniture"; that key now belongs to no layer (the furniture layout is
# "furnishing"), so relabelling it matches nothing new.
DATA_MIGRATIONS = [
    ("project_images", "layer", "UPDATE project_images SET layer = 'main' WHERE layer = 'furniture'"),
]


def migrate(eng=None) -> list[str]:
    """Add the columns in COLUMN_MIGRATIONS that the database does not have yet, then apply DATA_MIGRATIONS.
    Returns what was added or changed."""
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
    for table, column, sql in DATA_MIGRATIONS:
        if table not in tables or column not in {c["name"] for c in inspect(eng).get_columns(table)}:
            continue
        with eng.begin() as conn:
            n = conn.execute(text(sql)).rowcount
        if n and n > 0:
            added.append(f"{table}.{column}: {n} rows relabelled")
    return added
