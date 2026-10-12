import os
import secrets
from pathlib import Path

from flask import Flask

from . import db


def _secret_key(instance: Path) -> str:
    env = os.environ.get("BAGKEEPER_SECRET")
    if env:
        return env
    key_file = instance / "secret.key"
    if not key_file.exists():
        key_file.write_text(secrets.token_hex(32))
    return key_file.read_text()


def _bootstrap_admin(app: Flask) -> None:
    """First deploy: create the first admin from env vars if no admin exists yet."""
    phone = os.environ.get("BAGKEEPER_ADMIN_PHONE")
    password = os.environ.get("BAGKEEPER_ADMIN_PASSWORD")
    if not (phone and password):
        return
    from . import services
    with app.app_context():
        if db.get_db().execute("SELECT 1 FROM users WHERE role='admin'").fetchone():
            return
        services.create_user(os.environ.get("BAGKEEPER_ADMIN_NAME", "Admin"),
                             phone, password, "admin")


def _seed_demo(app: Flask) -> None:
    """Demo hosting (free tier, ephemeral disk): recreate the demo mall and logins on every
    start. Enabled only when BAGKEEPER_DEMO_PASSWORD is set; that value is the demo password."""
    password = os.environ.get("BAGKEEPER_DEMO_PASSWORD")
    if not password:
        return
    from . import services
    with app.app_context():
        conn = db.get_db()
        conn.execute("INSERT OR IGNORE INTO malls (name) VALUES ('Sawgrass Mills')")
        conn.commit()
        mall_id = conn.execute("SELECT id FROM malls WHERE name='Sawgrass Mills'").fetchone()[0]
        for name, phone, role in (("Demo Runner", "0500000002", "runner"),
                                  ("Demo Customer", "0500000003", "customer")):
            try:
                services.create_user(name, phone, password, role, mall_id)
            except services.RuleError:
                pass  # already exists
        conn.execute("UPDATE users SET on_duty=1 WHERE phone='0500000002'")
        conn.commit()


def create_app() -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    # BAGKEEPER_DATA_DIR points at a persistent disk in production
    instance = Path(os.environ.get("BAGKEEPER_DATA_DIR") or app.instance_path)
    instance.mkdir(parents=True, exist_ok=True)
    (instance / "uploads").mkdir(exist_ok=True)
    production = os.environ.get("BAGKEEPER_ENV") == "production"

    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=production,
        SECRET_KEY=_secret_key(instance),
        DATABASE=str(instance / "bagkeeper.sqlite"),
        UPLOAD_DIR=str(instance / "uploads"),
        MAX_CONTENT_LENGTH=8 * 1024 * 1024,
        BASE_FEE_CENTS=500,
        EXTRA_BAG_FEE_CENTS=200,
    )

    if production:
        # behind Cloudflare / the host's proxy: trust X-Forwarded-* for scheme and host
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db.init_app(app)
    _bootstrap_admin(app)
    _seed_demo(app)

    from . import api, web

    app.register_blueprint(web.bp)
    app.register_blueprint(api.bp, url_prefix="/api")

    @app.template_filter("money")
    def money(cents):
        return f"${(cents or 0) / 100:,.2f}"

    @app.template_filter("label")
    def label(status):
        return status.replace("_", " ").title()

    return app
