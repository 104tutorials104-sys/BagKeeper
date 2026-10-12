import sqlite3

import click
from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    phone TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL DEFAULT 'customer',   -- customer | runner | admin
    pw_hash TEXT NOT NULL,
    mall_id INTEGER REFERENCES malls(id),    -- runners: the mall they work at
    on_duty INTEGER NOT NULL DEFAULT 0,      -- runners: 1 = taking jobs
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS malls (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    lat REAL,                                -- mall centre, used to sanity-check GPS pins
    lon REAL,
    radius_m INTEGER,
    levels TEXT NOT NULL DEFAULT 'Ground'    -- comma-separated; one level = no level question
);
CREATE TABLE IF NOT EXISTS zones (           -- named places shoppers can pick
    id INTEGER PRIMARY KEY,
    mall_id INTEGER NOT NULL REFERENCES malls(id),
    name TEXT NOT NULL,
    kind TEXT NOT NULL,                      -- area | entrance | parking
    lat REAL,                                -- optional map position
    lon REAL,
    active INTEGER NOT NULL DEFAULT 1,
    UNIQUE (mall_id, name)
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,               -- short public reference e.g. BK-7F3A
    customer_id INTEGER NOT NULL REFERENCES users(id),
    runner_id INTEGER REFERENCES users(id),
    mall_id INTEGER NOT NULL REFERENCES malls(id),
    pickup_spot TEXT NOT NULL,               -- "Level 2, near Zara"
    dropoff_spot TEXT,                       -- "Car park B, bay 114"
    bag_count INTEGER NOT NULL DEFAULT 1,
    note TEXT,
    status TEXT NOT NULL DEFAULT 'requested',
    seal_no TEXT,
    seal_method TEXT,                        -- tamper_tag | biometric | ...
    seal_ok INTEGER,                         -- NULL = not checked, 1 = intact, 0 = broken
    storage_slot TEXT,
    handover_code TEXT,
    fee_cents INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS photos (
    id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    kind TEXT NOT NULL,                      -- pickup | sealed | delivery
    filename TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS events (          -- append-only audit trail for disputes
    id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    actor_id INTEGER REFERENCES users(id),
    event TEXT NOT NULL,
    detail TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_exc=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_db():
    db = get_db()
    db.executescript(SCHEMA)
    # lightweight migration for databases created before runner/mall support
    wanted = {
        "users": [("mall_id", "INTEGER REFERENCES malls(id)"),
                  ("on_duty", "INTEGER NOT NULL DEFAULT 0")],
        "malls": [("lat", "REAL"), ("lon", "REAL"), ("radius_m", "INTEGER"),
                  ("levels", "TEXT NOT NULL DEFAULT 'Ground'")],
        "orders": [("pickup_zone_id", "INTEGER REFERENCES zones(id)"),
                   ("pickup_level", "TEXT"), ("pickup_details", "TEXT"),
                   ("pickup_lat", "REAL"), ("pickup_lon", "REAL"), ("pickup_acc", "REAL"),
                   ("dropoff_zone_id", "INTEGER REFERENCES zones(id)"),
                   ("dropoff_details", "TEXT"),
                   ("dropoff_lat", "REAL"), ("dropoff_lon", "REAL"), ("dropoff_acc", "REAL")],
    }
    for table, cols_to_add in wanted.items():
        have = {r["name"] for r in db.execute(f"PRAGMA table_info({table})")}
        for col, decl in cols_to_add:
            if col not in have:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
    db.commit()


@click.command("init-db")
def init_db_command():
    """Create tables."""
    init_db()
    click.echo("Database ready.")


def init_app(app):
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
    with app.app_context():
        init_db()
