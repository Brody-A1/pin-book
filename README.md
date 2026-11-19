# Pin Book — standalone web app

A kid-safe digital pin book: a public web app with user logins, in the
style of a small Pro Flipper IQ-style site. Any number of users can
register; each user browses Hidden Disney chasers by year, park, and
set, and checks off the pins they own. Each user's collection is saved
and shown back on login, with per-set progress (e.g. 2 of 3 chasers
owned).

**Kid-safe by design:** no chat, no stranger contact, no in-app buying,
and no links to sellers or marketplaces anywhere in the app.

**Phone shortcut:** once this is hosted at a public URL, anyone can open
that URL on a phone and save it to their home screen (Share → Add to
Home Screen on iPhone, or Add to Home screen on Android). That shortcut
is just a bookmark to the website — no App Store involved.

## What is in v1

- User accounts: register / log in / log out. Passwords are stored
  hashed (Werkzeug/scrypt — never plaintext).
- Browse chasers by year → sets → set page, with photos, chaser vs
  super chaser badges, and PinPics / Pin & Pop catalog numbers.
- Per-user owned pins: tap "I own this pin" to check a pin off, tap
  again to remove it. "My Collection" shows everything owned, grouped
  by set, with per-set progress.
- Seeded data: 78 verified Hidden Disney chaser/super chaser pins
  (2022, 2024, 2025, 2026; WDW + DLR) from `data/chasers.json`. There is
  no 2023-original wave (2023 pouches carried the 2022 Series 2
  designs); none is invented here.

## What is NOT in v1

- **Set commons.** The dataset covers chasers only. Set pages list a
  set's verified chasers and clearly mark commons as "coming soon".
  Nothing is invented to fill a set. Adding commons later is a data
  job: add rows to `pins` with the same `set_id` (see "Adding set
  commons" below) and re-run nothing — the pages pick them up.
- **Payments / subscriptions.** No billing, no paywall. The `users`
  table has a `plan` column (default `'free'`) so a subscription layer
  can be added later — see "Adding payments later" below.
- **Self-hosted images.** Photos are hotlinked from the dataset
  `image_url` values (PinPics thumbnails, Pin & Pop CDN). If a source
  moves or blocks hotlinking, those photos break. Self-hosting the
  images (download them into `static/pins/` and rewrite `image_url`) is
  a future improvement.
- **Password reset, email, and admin tools.** None yet. A user who
  forgets a password currently needs an admin to reset it directly in
  the database.

## Run it locally

Requirements: Python 3.10+.

```bash
cd pin-book-standalone
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python seed.py        # loads data/chasers.json into pinbook.db
python app.py         # serves on http://127.0.0.1:5000
```

Open http://127.0.0.1:5000, sign up, and start checking off pins.
Re-running `python seed.py` is safe: it saves every collection first
(matched by year/park/wave/set/pin name), rebuilds the pin tables, and
re-attaches ownership. Users are never touched; only ownership rows for
pins removed from the dataset are dropped.

## Deploy it on a cheap host

### Option A: small VPS (e.g. a $5/month droplet/VPS) — most control

1. Point a domain (or subdomain, e.g. `pinbook.yourdomain.com`) at the
   server's IP address.
2. Install Python 3.10+, then copy this folder to the server.
3. Create the venv, install requirements, and seed:
   `pip install -r requirements.txt && python seed.py`.
4. Set a real secret key: `export PINBOOK_SECRET_KEY="$(openssl rand -hex 32)"`.
5. Run it with gunicorn behind a reverse proxy, e.g.:
   `gunicorn -w 2 -b 127.0.0.1:8000 app:app`
   and point nginx at port 8000 with HTTPS enabled (Certbot can issue
   a free certificate: `certbot --nginx -d pinbook.yourdomain.com`).
6. Keep the app running after logout with systemd (a small service
   file running the gunicorn command) or a process manager.

### Option B: Render (PaaS) — least server work

1. Push this folder to a private GitHub repo.
2. In Render, create a **Web Service** from the repo with:
   - Build command: `pip install -r requirements.txt && python seed.py`
   - Start command: `gunicorn app:app`
   - Environment variable: `PINBOOK_SECRET_KEY` = a long random value.
3. Render gives you a public `https://….onrender.com` URL. Add a
   custom domain later if you want one.
4. Note: on Render's free tier the service sleeps when idle, so the
   first visit after a pause is slow; a paid instance ($7/month
   class) stays awake. The SQLite file lives on the instance's disk —
   on a paid instance with a persistent disk attached, user accounts
   survive restarts; on a free/ephemeral instance they may not, so for
   a real product use a paid instance with a disk, or move the
   database to Render Postgres later (the SQL is plain and portable).

In both cases, serve over **HTTPS** once public: browsers warn about
login forms on plain HTTP, and passwords must never travel unencrypted.

## Adding set commons later

1. Research a set's common pins from a verifiable source (PinPics set
   pages). Only add pins you can verify — same rule as the chaser data.
2. Add them to `data/chasers.json` (or a second JSON file) with the
   set's year/park/wave/set values and `tier` set to `"common"`.
3. Re-run `python seed.py`. Set pages and progress counts pick the new
   pins up automatically. Consider adding a `tier` badge style for
   commons in `static/style.css` (the template already renders any
   tier value; only `super_chaser` gets the gold badge today).

## Adding payments later

The accounts are already structured for it:

1. The `users.plan` column records each account's plan (`'free'` by
   default; e.g. `'paid'` after checkout).
2. Add a `require_plan` check on the routes that should be gated
   (e.g. wrap `collection` and `toggle`, or the whole app behind
   login + plan), redirecting free accounts to a pricing page.
3. Plug in a billing provider (Stripe Checkout is the usual choice):
   create a Checkout session for the plan price, and on the webhook
   that confirms payment, set that user's `plan` to `'paid'`.
4. Keep the free/paid distinction in one place (the `plan` column) so
   a refund or cancellation is just flipping it back.

No billing code is included in v1 — this is only the hook it hangs on.

## File layout

```
pin-book-standalone/
├── app.py                 # Flask app: routes, auth, collections
├── seed.py                # loads data/chasers.json into pinbook.db
├── data/chasers.json      # 78 verified chaser entries (seed source)
├── pinbook.db             # SQLite database (created by seed.py)
├── requirements.txt       # Flask + gunicorn
├── static/style.css       # phone-first styles
└── templates/             # pages: home, year browse, set, collection,
                           # login, register
```

## License / data note

The pin data (names, sets, catalog numbers, photo URLs) comes from
public collector databases (PinPics, Pin & Pop) as compiled in
`data/chasers.json`. Photos are hotlinked to those sources, not
re-hosted. This project is not affiliated with Disney, PinPics, or
Pin & Pop.
