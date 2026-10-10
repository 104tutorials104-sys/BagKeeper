"""Create demo data:  python seed.py
DEV ONLY - demo logins below. Change/remove before any real deployment."""
from bagkeeper import create_app, services as svc
from bagkeeper.db import get_db

DEMO_USERS = [
    ("Demo Admin", "0500000001", "admin1234", "admin"),
    ("Demo Runner", "0500000002", "runner1234", "runner"),
    ("Demo Customer", "0500000003", "customer1234", "customer"),
]
MALLS = ["City Centre Mall", "Riverside Mall", "Harbour Plaza"]

app = create_app()
with app.app_context():
    db = get_db()
    for m in MALLS:
        db.execute("INSERT OR IGNORE INTO malls (name) VALUES (?)", (m,))
    db.commit()
    for name, phone, pw, role in DEMO_USERS:
        try:
            svc.create_user(name, phone, pw, role, mall_id=1)
        except svc.RuleError:
            pass
    # demo runner works at mall 1 and starts on duty; also fixes pre-mall databases
    db.execute("UPDATE users SET mall_id=1, on_duty=1 WHERE phone='0500000002'")
    db.commit()
    print("Seeded. Demo logins (phone / password):")
    for _, phone, pw, role in DEMO_USERS:
        print(f"  {role:9} {phone} / {pw}")
