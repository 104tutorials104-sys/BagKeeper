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
CREATE TABLE IF NOT EXISTS map_places (      -- stores etc. added by hand on the admin map
    id INTEGER PRIMARY KEY,
    mall_id INTEGER NOT NULL REFERENCES malls(id),
    name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'shop',       -- shop | food | service | other
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS osm_places (      -- stores pulled from OpenStreetMap, refreshed weekly
    mall_id INTEGER NOT NULL REFERENCES malls(id),
    osm_id TEXT NOT NULL,                    -- e.g. node/123456
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    seen_at REAL NOT NULL,
    PRIMARY KEY (mall_id, osm_id)
);
CREATE TABLE IF NOT EXISTS osm_refresh (
    mall_id INTEGER PRIMARY KEY REFERENCES malls(id),
    last_try REAL,
    last_ok REAL,
    count INTEGER,
    last_error TEXT
);
CREATE TABLE IF NOT EXISTS runner_positions ( -- latest live position of a runner on one job
    runner_id INTEGER PRIMARY KEY REFERENCES users(id),
    order_id INTEGER NOT NULL REFERENCES orders(id),
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    acc REAL,
    heading REAL,
    ts REAL NOT NULL                         -- unix seconds
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
                  ("on_duty", "INTEGER NOT NULL DEFAULT 0"),
                  ("badge", "TEXT")],                        # runner badge number shoppers can see
        "malls": [("lat", "REAL"), ("lon", "REAL"), ("radius_m", "INTEGER"),
                  ("levels", "TEXT NOT NULL DEFAULT 'Ground'")],
        "osm_refresh": [("last_error", "TEXT")],
        "orders": [("pickup_pin", "TEXT"),                  # shopper's 4-digit PIN for the runner
                   ("verify_secret", "TEXT"),               # seeds the rotating two-word phrase
                   ("verified_at", "TEXT"),                 # shopper confirmed the runner's phrase
                   ("pin_ok_at", "TEXT"),                   # runner entered the right PIN
                   ("pin_fails", "INTEGER NOT NULL DEFAULT 0"),
                   ("pin_locked", "INTEGER NOT NULL DEFAULT 0"),
                   ("delivery_verified_at", "TEXT"),        # shopper confirmed the runner at delivery
                   ("safety_flag", "TEXT"), ("safety_note", "TEXT"),   # "this isn't my runner"
                   ("pickup_zone_id", "INTEGER REFERENCES zones(id)"),
                   ("pickup_level", "TEXT"), ("pickup_details", "TEXT"),
                   ("pickup_lat", "REAL"), ("pickup_lon", "REAL"), ("pickup_acc", "REAL"),
                   ("pickup_src", "TEXT"), ("dropoff_src", "TEXT"),    # gps | map
                   ("dropoff_zone_id", "INTEGER REFERENCES zones(id)"),
                   ("dropoff_details", "TEXT"),
                   ("dropoff_lat", "REAL"), ("dropoff_lon", "REAL"), ("dropoff_acc", "REAL")],
    }
    for table, cols_to_add in wanted.items():
        have = {r["name"] for r in db.execute(f"PRAGMA table_info({table})")}
        for col, decl in cols_to_add:
            if col not in have:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
    # every runner gets a badge number that shoppers can check (1000 + their id)
    db.execute("UPDATE users SET badge = CAST(1000 + id AS TEXT) WHERE role='runner' AND badge IS NULL")
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
