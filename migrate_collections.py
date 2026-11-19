#!/usr/bin/env python3
"""Create Brody + Lexi accounts and attach their collections.

Usage:
    python migrate_collections.py <brody_password> <lexi_password>

Reads migration-ownership.json (username -> list of pin natural keys:
[year, park, wave, set_name, pin_name]), creates the users if they
don't exist, and inserts ownership rows by matching each natural key
to a pin id. Idempotent: safe to re-run.

Run on the server AFTER seed.py has rebuilt the catalog, so every
pin in the ownership map exists.
"""
import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.path.join(HERE, "pinbook.db")
MAP_PATH = os.path.join(HERE, "migration-ownership.json")


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: python migrate_collections.py "
                         "<brody_password> <lexi_password>")
    passwords = {"brody": sys.argv[1], "lexi": sys.argv[2]}
    db_path = os.environ.get("PINBOOK_DB", DEFAULT_DB)
    with open(MAP_PATH, encoding="utf-8") as fh:
        ownership_map = json.load(fh)

    # Import here so the script also works from a plain checkout.
    from werkzeug.security import generate_password_hash

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    cur = conn.cursor()
    for username, password in passwords.items():
        user = cur.execute("SELECT id FROM users WHERE username = ?",
                           (username,)).fetchone()
        if user:
            print(f"user {username} already exists (id {user[0]})")
        else:
            cur.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (username, generate_password_hash(password)))
            print(f"created user {username} (id {cur.lastrowid})")
    conn.commit()

    for username, keys in ownership_map.items():
        user = cur.execute("SELECT id FROM users WHERE username = ?",
                           (username,)).fetchone()
        if not user:
            print(f"SKIP {username}: no user row")
            continue
        uid = user[0]
        attached, missing = 0, 0
        for (year, park, wave, set_name, pin_name) in keys:
            pin = cur.execute("""
                SELECT p.id FROM pins p JOIN sets s ON s.id = p.set_id
                WHERE s.year = ? AND s.park = ? AND s.wave = ? AND
                      s.set_name = ? AND p.pin_name = ?""",
                (year, park, wave, set_name, pin_name)).fetchone()
            if not pin:
                print(f"  MISSING pin for {username}: {year} {park} | "
                      f"{set_name} | {pin_name}")
                missing += 1
                continue
            cur.execute("INSERT OR IGNORE INTO ownership VALUES (?, ?)",
                        (uid, pin[0]))
            attached += 1
        conn.commit()
        total = cur.execute("SELECT COUNT(*) FROM ownership WHERE user_id = ?",
                            (uid,)).fetchone()[0]
        print(f"{username}: attached {attached}, missing {missing}, "
              f"total owned now {total}")
    conn.close()


if __name__ == "__main__":
    main()
