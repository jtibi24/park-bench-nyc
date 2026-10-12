# app.py — Brick 5: the web pages.
#
# Run:  python app.py
# Then open http://127.0.0.1:5000 in your browser.
#
# "/" is the index: one row per camera from cameras.json —
# green dot = at least one spot free, red dot = full.
# Click a camera for its live view and text-alert signup.

import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from flask import Flask, redirect, render_template_string, request, send_file

from grabber import load_cameras

DB_PATH = Path(__file__).resolve().parent / "parking.db"
SNAP_DIR = Path(__file__).resolve().parent / "snapshots"
APP_NAME = "Park Bench NYC"

app = Flask(__name__)

STYLE = """
body { font-family: sans-serif; max-width: 480px; margin: 2em auto; padding: 0 1em; }
.row { display: flex; align-items: center; gap: .6em; font-size: 1.2em; }
.dot { width: 18px; height: 18px; border-radius: 50%; display: inline-block; flex: none; }
.green { background: #22c55e; }
.red { background: #ef4444; }
.gray { background: #9ca3af; }
.cam { display: block; padding: .8em 0; border-bottom: 1px solid #eee;
       text-decoration: none; color: inherit; }
.cam:hover { background: #f9fafb; }
form { margin-top: 2em; display: grid; gap: .6em; }
input, select, button { font-size: 1em; padding: .5em; }
button { cursor: pointer; }
.back { display: inline-block; margin-bottom: 1em; }
"""

INDEX_PAGE = """<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="120">
<title>{{ app_name }}</title>
<style>""" + STYLE + """</style>
</head>
<body>
<h1>🪑 {{ app_name }}</h1>
{% for cam in cameras %}
<a class="cam" href="/camera/{{ cam.id }}">
  <span class="row">
    <span class="dot {{ cam.dot }}"></span>
    <strong>{{ cam.name }}</strong>&nbsp;— {{ cam.text }}
  </span>
</a>
{% endfor %}
<p><small>Live views refresh every 2 minutes.</small></p>
</body>
</html>
"""

DETAIL_PAGE = """<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="120">
<title>{{ camera }} — {{ app_name }}</title>
<style>""" + STYLE + """</style>
</head>
<body>
<a class="back" href="/">← all cameras</a>
<h1>🪑 {{ app_name }}</h1>
<div class="row">
  <span class="dot {{ dot }}"></span>
  <strong>{{ camera }}</strong>&nbsp;— {{ free }} of {{ total }} spots free
</div>
<img src="/camera/{{ cam_id }}/snapshot" alt="Live camera view"
     style="width:100%; border-radius:8px; margin-top:1em;">
<p><small>Live view — refreshes every 2 minutes.</small></p>
<form action="/camera/{{ cam_id }}/watch" method="post">
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
    """Create the watchers table if it doesn't exist yet (new schema)."""
    conn = get_db()
    conn.execute("""CREATE TABLE IF NOT EXISTS watchers (
                        id INTEGER PRIMARY KEY, camera_id TEXT,
                        phone TEXT NOT NULL,
                        expires_at REAL NOT NULL,
                        active INTEGER NOT NULL DEFAULT 1)""")
    cols = [r[1] for r in conn.execute("PRAGMA table_info(watchers)").fetchall()]
    if "camera_id" not in cols:
        conn.execute("ALTER TABLE watchers ADD COLUMN camera_id TEXT")
    conn.commit()
    conn.close()


def camera_status(camera_id):
    """Return (free_count, total_count) for one camera, or (None, None)."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT confirmed FROM spot_state WHERE camera_id = ?",
            (camera_id,)).fetchall()
    except sqlite3.OperationalError:
        rows = []  # monitor hasn't run yet
    conn.close()
    if not rows:
        return None, None
    total = len(rows)
    free = sum(1 for r in rows if r["confirmed"] == 0)
    return free, total


def get_camera_or_404(camera_id):
    for cam in load_cameras():
        if cam["id"] == camera_id:
            return cam
    return None


@app.route("/")
def index():
    cameras = []
    for cam in load_cameras():
        free, total = camera_status(cam["id"])
        if free is None:
            dot, text = "gray", "no data yet — run monitor.py"
        else:
            dot = "green" if free else "red"
            text = f"{free} of {total} spots free"
        cameras.append({"id": cam["id"], "name": cam["name"],
                        "dot": dot, "text": text})
    return render_template_string(INDEX_PAGE, app_name=APP_NAME,
                                  cameras=cameras)


@app.route("/camera/<cam_id>")
def detail(cam_id):
    cam = get_camera_or_404(cam_id)
    if cam is None:
        return "Unknown camera.", 404
    free, total = camera_status(cam_id)
    if free is None:
        free, total, dot = 0, 0, "gray"
    else:
        dot = "green" if free else "red"
    return render_template_string(DETAIL_PAGE, app_name=APP_NAME,
                                  cam_id=cam_id, camera=cam["name"],
                                  free=free, total=total, dot=dot)


@app.route("/camera/<cam_id>/snapshot")
def snapshot(cam_id):
    """Serve the annotated live view (falls back to the raw snapshot)."""
    if get_camera_or_404(cam_id) is None:
        return "Unknown camera.", 404
    annotated = SNAP_DIR / f"{cam_id}-latest-annotated.jpg"
    if annotated.exists():
        return send_file(annotated, mimetype="image/jpeg")
    snaps = sorted(p for p in SNAP_DIR.glob(f"{cam_id}-*.jpg")
                   if not p.name.startswith(("annotated-", "latest-")))
    if not snaps:
        return "No snapshots yet — run monitor.py first.", 404
    return send_file(snaps[-1], mimetype="image/jpeg")


@app.route("/camera/<cam_id>/watch", methods=["POST"])
def watch(cam_id):
    if get_camera_or_404(cam_id) is None:
        return "Unknown camera.", 404
    phone = request.form.get("phone", "").strip()
    try:
        minutes = int(request.form.get("duration", "60"))
    except ValueError:
        minutes = 60
    minutes = min(max(minutes, 5), 240)  # clamp: 5 minutes to 4 hours
    expires_at = time.time() + minutes * 60

    conn = get_db()
    conn.execute("INSERT INTO watchers (camera_id, phone, expires_at, active) "
                 "VALUES (?, ?, ?, 1)", (cam_id, phone, expires_at))
    conn.commit()
    conn.close()
    return redirect(f"/camera/{cam_id}")


if __name__ == "__main__":
    ensure_watchers()
    app.run(debug=True)
