#!/usr/bin/env python3
"""Seed pinbook.db from data/chasers.json.

Usage:
    python seed.py [path/to/chasers.json]

The script is idempotent and safe to re-run: it saves every ownership
row first (matched to pins by their natural key: year, park, wave, set,
pin name), rebuilds the sets/pins tables in a fixed deterministic order,
then re-attaches ownership to the matching pins. Users are never
touched; ownership rows survive as long as their pin still exists in
the dataset (rows for pins removed from the dataset are dropped and
reported).

Source data: Hidden Disney chaser/super chaser entries (2022/2024/2025/
2026). The file contains chasers only — no common pins. Set pages in the
app therefore list a set's chasers and mark commons as "coming soon";
this script invents no pins.
"""
import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_JSON = os.path.join(HERE, "data", "chasers.json")
DEFAULT_DB = os.path.join(HERE, "pinbook.db")


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_JSON
    db_path = os.environ.get("PINBOOK_DB", DEFAULT_DB)
    with open(src, encoding="utf-8") as fh:
        entries = json.load(fh)
    if not isinstance(entries, list):
        raise SystemExit("chasers.json must contain a JSON list of entries")

    entries.sort(key=lambda e: (e["year"], e["park"], e.get("wave") or "",
                                e["set"], e["pin_name"]))
    sets = {}
    for e in entries:
        key = (e["year"], e["park"], e.get("wave") or "", e["set"])
        sets.setdefault(key, [])

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    cur = conn.cursor()
    # Schema (same as app.py) so seed.py also works on a fresh checkout.
    cur.executescript("""
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
    # Save ownership by natural key so collections survive the rebuild.
    saved = cur.execute("""
        SELECT u.username, s.year, s.park, s.wave, s.set_name, p.pin_name
        FROM ownership o
        JOIN users u ON u.id = o.user_id
        JOIN pins p ON p.id = o.pin_id
        JOIN sets s ON s.id = p.set_id
    """).fetchall()
    cur.execute("DELETE FROM ownership")
    cur.execute("DELETE FROM pins")
    cur.execute("DELETE FROM sets")
    set_ids = {}
    for (year, park, wave, set_name) in sorted(sets):
        cur.execute(
            "INSERT INTO sets (year, park, wave, set_name) VALUES (?, ?, ?, ?)",
            (year, park, wave, set_name))
        set_ids[(year, park, wave, set_name)] = cur.lastrowid
    for e in entries:
        key = (e["year"], e["park"], e.get("wave") or "", e["set"])
        cur.execute(
            """INSERT INTO pins
               (set_id, pin_name, tier, pinpics_id, pinpop_id, image_url,
                source_notes)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (set_ids[key], e["pin_name"], e["tier"], e.get("pinpics_id"),
             e.get("pinpop_id"), e.get("image_url"), e.get("source_notes")))
    conn.commit()
    n_sets = cur.execute("SELECT COUNT(*) FROM sets").fetchone()[0]
    n_pins = cur.execute("SELECT COUNT(*) FROM pins").fetchone()[0]
    n_users = cur.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    # Re-attach saved ownership to the rebuilt pins by natural key.
    restored, dropped = 0, 0
    for (username, year, park, wave, set_name, pin_name) in saved:
        user = cur.execute("SELECT id FROM users WHERE username = ?",
                           (username,)).fetchone()
        pin = cur.execute("""
            SELECT p.id FROM pins p JOIN sets s ON s.id = p.set_id
            WHERE s.year = ? AND s.park = ? AND s.wave = ? AND
                  s.set_name = ? AND p.pin_name = ?""",
            (year, park, wave, set_name, pin_name)).fetchone()
        if user and pin:
            cur.execute("INSERT OR IGNORE INTO ownership VALUES (?, ?)",
                        (user[0], pin[0]))
            restored += 1
        else:
            dropped += 1
    conn.commit()
    conn.close()
    print(f"seeded {n_pins} pins in {n_sets} sets from {src}")
    print(f"database: {db_path} (users untouched: {n_users}; "
          f"ownership restored: {restored}, dropped: {dropped})")


if __name__ == "__main__":
    main()
