#!/usr/bin/env python3
"""Pin Book — standalone multi-user pin-collection web app.

A kid-safe digital pin book: users register, log in, browse Hidden Disney
chasers by year / park / set, and check off the pins they own. Each user's
collection is saved in SQLite and shown back on login.

Run:
    pip install -r requirements.txt
    python seed.py          # loads data/chasers.json into pinbook.db
    python app.py           # serves on http://127.0.0.1:5000

Production: set the PINBOOK_SECRET_KEY environment variable to a long
random value, serve behind HTTPS, and run with gunicorn (see README.md).
There is no payment/subscription layer in v1; the users.plan column exists
so one can be added later (see README.md "Adding payments later").
"""
import os
import secrets
import sqlite3
from functools import wraps

from flask import (
    Flask, abort, flash, g, redirect, render_template, request,
    session, url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get(
    "PINBOOK_SECRET_KEY", "dev-only-change-me-in-production")
DB_PATH = os.environ.get("PINBOOK_DB",
                         os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      "pinbook.db"))


# ---------------------------------------------------------------- DB ----
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_schema():
    db = get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            plan TEXT NOT NULL DEFAULT 'free',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS sets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            year INTEGER NOT NULL,
            park TEXT NOT NULL,
            wave TEXT NOT NULL,
            set_name TEXT NOT NULL,
            UNIQUE (year, park, wave, set_name)
        );
        CREATE TABLE IF NOT EXISTS pins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            set_id INTEGER NOT NULL REFERENCES sets(id),
            pin_name TEXT NOT NULL,
            tier TEXT NOT NULL,
            pinpics_id TEXT,
            pinpop_id TEXT,
            image_url TEXT,
            source_notes TEXT
        );
        CREATE TABLE IF NOT EXISTS ownership (
            user_id INTEGER NOT NULL REFERENCES users(id),
            pin_id INTEGER NOT NULL REFERENCES pins(id),
            PRIMARY KEY (user_id, pin_id)
        );
    """)
    db.commit()


with app.app_context():
    init_schema()


# ------------------------------------------------------------- helpers ----
def current_user():
    if "user_id" not in session:
        return None
    return get_db().execute("SELECT * FROM users WHERE id = ?",
                            (session["user_id"],)).fetchone()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            flash("Log in to see your collection.")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(16)
    return session["csrf_token"]


@app.context_processor
def inject_globals():
    return {"current_user": current_user(), "csrf_token": csrf_token()}


def check_csrf():
    if request.form.get("csrf_token") != session.get("csrf_token"):
        abort(400)


# -------------------------------------------------------------- routes ----
@app.route("/")
def index():
    db = get_db()
    years = db.execute("""
        SELECT s.year, COUNT(p.id) AS pins, COUNT(DISTINCT s.id) AS sets
        FROM sets s JOIN pins p ON p.set_id = s.id
        GROUP BY s.year ORDER BY s.year DESC
    """).fetchall()
    owned = 0
    if "user_id" in session:
        owned = db.execute("SELECT COUNT(*) FROM ownership WHERE user_id = ?",
                           (session["user_id"],)).fetchone()[0]
    total = db.execute("SELECT COUNT(*) FROM pins").fetchone()[0]
    return render_template("index.html", years=years, owned=owned,
                           total=total)


@app.route("/browse/<int:year>")
def browse_year(year):
    db = get_db()
    sets = db.execute("""
        SELECT s.*, COUNT(p.id) AS pins,
               COALESCE(SUM(CASE WHEN o.user_id = ? THEN 1 ELSE 0 END), 0)
                   AS owned
        FROM sets s
        JOIN pins p ON p.set_id = s.id
        LEFT JOIN ownership o ON o.pin_id = p.id
        WHERE s.year = ?
        GROUP BY s.id ORDER BY s.park, s.wave, s.set_name
    """, (session.get("user_id", -1), year)).fetchall()
    if not sets:
        abort(404)
    return render_template("browse.html", year=year, sets=sets)


@app.route("/set/<int:set_id>")
def set_page(set_id):
    db = get_db()
    s = db.execute("SELECT * FROM sets WHERE id = ?", (set_id,)).fetchone()
    if s is None:
        abort(404)
    pins = db.execute("""
        SELECT p.*,
               CASE WHEN o.user_id IS NOT NULL THEN 1 ELSE 0 END AS owned
        FROM pins p
        LEFT JOIN ownership o
               ON o.pin_id = p.id AND o.user_id = ?
        WHERE p.set_id = ? ORDER BY p.pin_name
    """, (session.get("user_id", -1), set_id)).fetchall()
    owned = sum(p["owned"] for p in pins)
    return render_template("set.html", s=s, pins=pins, owned=owned)


@app.route("/toggle", methods=["POST"])
@login_required
def toggle():
    check_csrf()
    pin_id = request.form.get("pin_id", type=int)
    set_id = request.form.get("set_id", type=int)
    db = get_db()
    pin = db.execute("SELECT id FROM pins WHERE id = ?", (pin_id,)).fetchone()
    if pin is None:
        abort(404)
    row = db.execute("SELECT 1 FROM ownership WHERE user_id = ? AND pin_id = ?",
                     (session["user_id"], pin_id)).fetchone()
    if row:
        db.execute("DELETE FROM ownership WHERE user_id = ? AND pin_id = ?",
                   (session["user_id"], pin_id))
    else:
        db.execute("INSERT INTO ownership (user_id, pin_id) VALUES (?, ?)",
                   (session["user_id"], pin_id))
    db.commit()
    return redirect(url_for("set_page", set_id=set_id))


@app.route("/collection")
@login_required
def collection():
    db = get_db()
    rows = db.execute("""
        SELECT s.year, s.park, s.wave, s.set_name, s.id AS set_id,
               p.id AS pin_id, p.pin_name, p.tier, p.image_url,
               p.pinpics_id, p.pinpop_id
        FROM ownership o
        JOIN pins p ON p.id = o.pin_id
        JOIN sets s ON s.id = p.set_id
        WHERE o.user_id = ?
        ORDER BY s.year DESC, s.park, s.wave, s.set_name, p.pin_name
    """, (session["user_id"],)).fetchall()
    groups = {}
    for r in rows:
        groups.setdefault((r["year"], r["park"], r["wave"], r["set_name"],
                           r["set_id"]), []).append(r)
    progress = []
    for (year, park, wave, set_name, set_id), pins in groups.items():
        total = db.execute("SELECT COUNT(*) FROM pins WHERE set_id = ?",
                           (set_id,)).fetchone()[0]
        progress.append({"year": year, "park": park, "wave": wave,
                         "set_name": set_name, "set_id": set_id,
                         "pins": pins, "owned": len(pins), "total": total})
    total_owned = len(rows)
    return render_template("collection.html", progress=progress,
                           total_owned=total_owned)


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        check_csrf()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        db = get_db()
        if len(username) < 3 or len(username) > 32:
            flash("Username must be 3–32 characters.")
        elif len(password) < 6:
            flash("Password must be at least 6 characters.")
        elif db.execute("SELECT 1 FROM users WHERE username = ?",
                        (username,)).fetchone():
            flash("That username is taken.")
        else:
            db.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (username, generate_password_hash(password)))
            db.commit()
            user = db.execute("SELECT id FROM users WHERE username = ?",
                              (username,)).fetchone()
            session["user_id"] = user["id"]
            session["username"] = username
            return redirect(url_for("index"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        check_csrf()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE username = ?",
                          (username,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            return redirect(request.args.get("next") or url_for("index"))
        flash("Wrong username or password.")
    return render_template("login.html")


@app.route("/logout", methods=["POST"])
def logout():
    check_csrf()
    session.clear()
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
