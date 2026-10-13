import base64
import hashlib
import sqlite3
from urllib.parse import urlsplit, urlunsplit
import os


from flask import Flask, g, jsonify, redirect, request, url_for, Blueprint

bp = Blueprint("main", __name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS urls (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    original_url TEXT NOT NULL,
    short_code   TEXT NOT NULL UNIQUE,
    created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    click_count  INTEGER NOT NULL DEFAULT 0,
    user_id      INTEGER
);

CREATE TABLE IF NOT EXISTS clicks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    url_id     INTEGER NOT NULL REFERENCES urls(id) ON DELETE CASCADE,
    timestamp  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ip_address TEXT,
    user_agent TEXT,
    referrer   TEXT
);

CREATE INDEX IF NOT EXISTS idx_clicks_url_id ON clicks(url_id);
"""


# DATABASE

def get_db() -> sqlite3.Connection:
    """One connection per request, stored on Flask's `g`."""
    if "db" not in g:
        g.db = sqlite3.connect(os.getenv("DATABASE"))
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@bp.teardown_app_request
def close_db(exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db() -> None:
    with sqlite3.connect(os.getenv("DATABASE")) as db:
        db.executescript(SCHEMA)


# HELPERS

def full_hash(url: str) -> str:
    digest = hashlib.sha256(url.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def normalize_url(url: str) -> str:
    p = urlsplit(url.strip())
    return urlunsplit((
        p.scheme.lower(),
        p.netloc.lower(),
        p.path.rstrip("/") or "/",
        p.query,
        "",
    ))


def get_or_create_shortcode(url: str, min_length: int = 8) -> tuple[str, bool]:
    """
    Return (shortcode, created). The same URL always maps to the same code.
    If a different URL already owns the code (hash-prefix collision),
    use a longer prefix of the hash until a free slot is found.
    """
    db = get_db()
    digest = full_hash(url)

    for length in range(min_length, len(digest) + 1):
        code = digest[:length]
        row = db.execute(
            "SELECT original_url FROM urls WHERE short_code = ?", (code,)
        ).fetchone()

        if row is None:
            db.execute(
                "INSERT INTO urls (original_url, short_code) VALUES (?, ?)",
                (url, code),
            )
            db.commit()
            return code, True
        if row["original_url"] == url:
            return code, False

    raise RuntimeError("Could not allocate a short code")

def get_or_create_custom_shortcode(url:str, code: str) -> tuple[str, bool]:
    db = get_db()

    row = db.execute(
        "SELECT original_url FROM urls WHERE short_code = ?", (code,)
    ).fetchone()
    if row is None:
        db.execute(
            "INSERT INTO urls (original_url, short_code) VALUES (?, ?)",
            (url, code),
        )
        db.commit()
        return code, True
    if row["original_url"] == url:
        return code, False
    raise RuntimeError("Could not allocate a short code (already in use)")



# ROUTES

@bp.route("/")
def root_page():
    return "Hello world"


@bp.route("/shorten", methods=["POST"])
def shorten_url():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "No data provided"}), 400

    url_to_short = data.get("url")
    if not url_to_short or not isinstance(url_to_short, str):
        return jsonify({"error": "No url provided"}), 400

    try:
        url_to_short = normalize_url(url_to_short)
        parts = urlsplit(url_to_short)
    except ValueError:
        return jsonify({"error": "Invalid url"}), 400

    if parts.scheme not in ("http", "https") or not parts.netloc:
        return jsonify({"error": "Invalid url"}), 400

    try:
        shortcode, created = get_or_create_shortcode(url_to_short)
    except RuntimeError:
        return jsonify({"error": "could not allocate shortcode for url"}), 400
    short_url = url_for("main.shortcode_redirect", shortcode=shortcode, _external=True)
    return jsonify({"url": short_url}), (201 if created else 200)

@bp.route("/custom", methods=["POST"])
def shorten_url_custom():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "No data provided"}), 400

    url_to_short = data.get("url")
    
    if not url_to_short or not isinstance(url_to_short, str):
        return jsonify({"error": "No url provided"}), 400

    shortcode = data.get("shortcode")
    if not shortcode:
        return jsonify({"error": "No url custome shortcode provided"}), 400

    try:
        url_to_short = normalize_url(url_to_short)
        parts = urlsplit(url_to_short)
    except ValueError:
        return jsonify({"error": "Invalid url"}), 400

    if parts.scheme not in ("http", "https") or not parts.netloc:
        return jsonify({"error": "Invalid url"}), 400

    try:
        shortcode, created = get_or_create_custom_shortcode(url_to_short, shortcode)
    except RuntimeError:
        return jsonify({"error": "could not allocate shortcode for url"}), 400
    short_url = url_for("main.shortcode_redirect", shortcode=shortcode, _external=True)
    return jsonify({"url": short_url}), (201 if created else 200)


@bp.route("/stats/<shortcode>", methods=["GET"])
def shortcode_stats(shortcode: str):
    db = get_db()
    row = db.execute(
        "SELECT id, original_url, short_code, created_at, click_count "
        "FROM urls WHERE short_code = ?",
        (shortcode,),
    ).fetchone()
    if row is None:
        return jsonify({"error": "Not found"}), 404

    recent = db.execute(
        "SELECT timestamp, ip_address, user_agent, referrer "
        "FROM clicks WHERE url_id = ? ORDER BY id DESC LIMIT 20",
        (row["id"],),
    ).fetchall()

    return jsonify({
        "short_code": row["short_code"],
        "original_url": row["original_url"],
        "created_at": row["created_at"],
        "click_count": row["click_count"],
        "recent_clicks": [dict(c) for c in recent],
    })


@bp.route("/<shortcode>", methods=["GET"])
def shortcode_redirect(shortcode: str):
    db = get_db()
    row = db.execute(
        "SELECT id, original_url FROM urls WHERE short_code = ?", (shortcode,)
    ).fetchone()
    if row is None:
        return jsonify({"error": "Not found"}), 404

    db.execute(
        "INSERT INTO clicks (url_id, ip_address, user_agent, referrer) "
        "VALUES (?, ?, ?, ?)",
        (
            row["id"],
            request.remote_addr,
            request.headers.get("User-Agent"),
            request.referrer,
        ),
    )
    db.execute(
        "UPDATE urls SET click_count = click_count + 1 WHERE id = ?", (row["id"],)
    )
    db.commit()

    return redirect(row["original_url"], code=302)

@bp.route("/<shortcode>", methods=["DELETE"])
def shortcode_delete(shortcode: str):
    db = get_db()
    row = db.execute(
        "SELECT id, original_url FROM urls WHERE short_code = ?", (shortcode,)
    ).fetchone()
    if row is None:
        return jsonify({"error": "Not found"}), 404
        
    db.execute(
        "DELETE FROM urls WHERE id = ?", (row["id"],)
    )
    db.commit()

    return jsonify({"message": "URL deleted successfully"}), 200

def create_app(config_object = None):
    """Create a Flask application using the app factory pattern."""

    app = Flask(__name__)

    load_config(app, config_object)

    init_db()

    app.register_blueprint(bp)

    return app

def load_config(app, config_object=None):
    """Load configuration without requiring a .env file in Docker."""
    from dotenv import load_dotenv

    base_dir = os.path.dirname(os.path.abspath(__file__))
    dotenv_path = os.path.join(base_dir, ".env")

    # Load local development settings if available.
    # In Docker, environment variables can be supplied directly.
    if os.path.exists(dotenv_path):
        load_dotenv(dotenv_path)

    app.config["DATABASE"] = os.getenv(
        "DATABASE",
        os.path.join(base_dir, "urls.db"),
    )

    if config_object is not None:
        app.config.from_object(config_object)

    #app.config.from_object(config_object)

if __name__ == "__main__":
    app = create_app()
    app.run()