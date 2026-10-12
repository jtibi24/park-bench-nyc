# app.py — Brick 5: the web page.
#
# Run:  python app.py
# Then open http://127.0.0.1:5000 in your browser.
#
# One row per camera: green dot = at least one spot free,
# red dot = full. The "Alert me" form starts a time-limited watch:
# one text when a spot opens, then the watch ends quietly.

import sqlite3
import time
from pathlib import Path

from flask import Flask, redirect, render_template_string, request, send_file

DB_PATH = Path(__file__).parent / "parking.db"
SNAP_DIR = Path(__file__).parent / "snapshots"
CAMERA_NAME = "Lincolnville Ferry Lot"  # our one demo camera (for now)
APP_NAME = "Park Bench NYC"

app = Flask(__name__)

PAGE = """<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="120">
<title>{{ app_name }}</title>
<style>
body { font-family: sans-serif; max-width: 480px; margin: 2em auto; padding: 0 1em; }
.row { display: flex; align-items: center; gap: .6em; font-size: 1.2em; }
.dot { width: 18px; height: 18px; border-radius: 50%; display: inline-block; }
.green { background: #22c55e; }
.red { background: #ef4444; }
form { margin-top: 2em; display: grid; gap: .6em; }
input, select, button { font-size: 1em; padding: .5em; }
button { cursor: pointer; }
</style>
</head>
<body>
<h1>🪑 {{ app_name }}</h1>
<div class="row">
  <span class="dot {{ 'green' if free else 'red' }}"></span>
  <strong>{{ camera }}</strong>&nbsp;— {{ free }} of {{ total }} spots free
</div>
<img src="/snapshot" alt="Live camera view" style="width:100%; border-radius:8px; margin-top:1em;">
<p><small>Live view — refreshes every 2 minutes.</small></p>
<form action="/watch" method="post">
  <h3>Get a text when a spot opens</h3>
  <input name="phone" type="tel" placeholder="Phone number" required>
  <select name="duration">
    <option value="30">Watch for 30 minutes</option>
    <option value="60" selected>Watch for 1 hour</option>
    <option value="120">Watch for 2 hours</option>
  </select>
  <button type="submit">Alert me</button>
</form>
<p><small>One text when a spot opens, then the watch ends. Silence if nothing opens.</small></p>
</body>
</html>
"""


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_watchers():
    """Create the watchers table if it doesn't exist yet."""
    conn = get_db()
    conn.execute("""CREATE TABLE IF NOT EXISTS watchers (
                        id INTEGER PRIMARY KEY,
                        phone TEXT NOT NULL,
                        expires_at REAL NOT NULL,
                        active INTEGER NOT NULL DEFAULT 1)""")
    conn.commit()
    conn.close()


def camera_status():
    """Return (free_count, total_count) from the latest confirmed states."""
    conn = get_db()
    rows = conn.execute("SELECT confirmed FROM spot_state").fetchall()
    conn.close()
    total = len(rows)
    free = sum(1 for r in rows if r["confirmed"] == 0)
    return free, total


@app.route("/")
def index():
    free, total = camera_status()
    return render_template_string(PAGE, app_name=APP_NAME, camera=CAMERA_NAME,
                                  free=free, total=total)


@app.route("/snapshot")
def snapshot():
    """Serve the annotated live view (falls back to the raw snapshot)."""
    annotated = SNAP_DIR / "latest-annotated.jpg"
    if annotated.exists():
        return send_file(annotated, mimetype="image/jpeg")
    snaps = sorted(SNAP_DIR.glob("snapshot-*.jpg"))
    if not snaps:
        return "No snapshots yet — run monitor.py first.", 404
    return send_file(snaps[-1], mimetype="image/jpeg")


@app.route("/watch", methods=["POST"])
def watch():
    phone = request.form.get("phone", "").strip()
    try:
        minutes = int(request.form.get("duration", "60"))
    except ValueError:
        minutes = 60
    minutes = min(max(minutes, 5), 240)  # clamp: 5 minutes to 4 hours
    expires_at = time.time() + minutes * 60

    conn = get_db()
    conn.execute("INSERT INTO watchers (phone, expires_at, active) "
                 "VALUES (?, ?, 1)", (phone, expires_at))
    conn.commit()
    conn.close()
    return redirect("/")


if __name__ == "__main__":
    ensure_watchers()
    app.run(debug=True)
