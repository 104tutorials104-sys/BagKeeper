"""Create demo data:  python seed.py
DEV ONLY - demo logins below. Change/remove before any real deployment."""
from bagkeeper import create_app, sawgrass, services as svc
from bagkeeper.db import get_db

DEMO_USERS = [
    ("Demo Admin", "0500000001", "admin1234", "admin"),
    ("Demo Runner", "0500000002", "runner1234", "runner"),
    ("Demo Customer", "0500000003", "customer1234", "customer"),
]

app = create_app()
with app.app_context():
    db = get_db()
    mall_id = sawgrass.ensure(db)      # Sawgrass Mills + its places
    for name, phone, pw, role in DEMO_USERS:
        try:
            svc.create_user(name, phone, pw, role, mall_id=mall_id)
        except svc.RuleError:
            pass
    # demo runner works at Sawgrass Mills and starts on duty
    db.execute("UPDATE users SET mall_id=?, on_duty=1 WHERE phone='0500000002'", (mall_id,))
    db.commit()
    print("Seeded. Demo logins (phone / password):")
    for _, phone, pw, role in DEMO_USERS:
        print(f"  {role:9} {phone} / {pw}")
