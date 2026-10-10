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
    name TEXT NOT NULL UNIQUE
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
    cols = {r["name"] for r in db.execute("PRAGMA table_info(users)")}
    if "mall_id" not in cols:
        db.execute("ALTER TABLE users ADD COLUMN mall_id INTEGER REFERENCES malls(id)")
    if "on_duty" not in cols:
        db.execute("ALTER TABLE users ADD COLUMN on_duty INTEGER NOT NULL DEFAULT 0")
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
