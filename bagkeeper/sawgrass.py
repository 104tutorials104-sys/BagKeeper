"""Starter data for Sawgrass Mills (Sunrise, FL).

Zone names come from public mall listings and are meant to be reviewed by the mall.
Per-zone map positions are left empty on purpose (admin can set them by standing at
the spot and tapping "Use my location"). The centre point is approximate.
"""
NAME = "Sawgrass Mills"
CENTER = (26.1500, -80.3220)     # approximate
RADIUS_M = 1800                  # the property is very large; admin can adjust
LEVELS = "Ground"                # single-level mall

ZONES = [
    # (name, kind)
    ("East Entrance (by adidas)", "entrance"),
    ("West Entrance (near Marshalls)", "entrance"),
    ("BrandsMart USA entrance", "entrance"),
    ("East Court / East Dining Pavilion", "area"),
    ("West Court / West Dining Pavilion", "area"),
    ("The Oasis", "area"),
    ("The Colonnade", "area"),
    ("Fashion Row", "area"),
    ("The Loop", "area"),
    ("Garage between Super Target and Burlington", "parking"),
    ("Garage near The Colonnade Outlets", "parking"),
    ("Surface parking (perimeter lots)", "parking"),
]


def ensure(db):
    """Create Sawgrass Mills and its zones if missing. Returns the mall id."""
    db.execute(
        "INSERT OR IGNORE INTO malls (name, lat, lon, radius_m, levels) VALUES (?,?,?,?,?)",
        (NAME, CENTER[0], CENTER[1], RADIUS_M, LEVELS),
    )
    mall_id = db.execute("SELECT id FROM malls WHERE name=?", (NAME,)).fetchone()[0]
    for zone_name, kind in ZONES:
        db.execute("INSERT OR IGNORE INTO zones (mall_id, name, kind) VALUES (?,?,?)",
                   (mall_id, zone_name, kind))
    db.commit()
    return mall_id
