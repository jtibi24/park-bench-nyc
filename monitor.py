# monitor.py — Brick 4: watch the cameras over time, alert when a spot opens.
#
# Every CHECK_INTERVAL seconds it runs the whole pipeline for EACH camera
# in cameras.json:
#   snapshot (brick 1) → detect cars (brick 2) → check spots (brick 3)
# then compares the fresh states against the database.
#
# A spot only counts as "changed" after 2 readings in a row agree.
# One odd frame (a passing truck blocking the view) can't fake a
# "spot freed!" alert.
#
# Tables in parking.db (every row tagged with its camera):
#   readings   — every check: when, which camera, which spot, occupied/free
#   spot_state — per camera+spot: last confirmed state + pending unconfirmed
#   events     — every confirmed change: when, which camera+spot, freed/taken
#   watchers   — text-alert subscriptions, one per camera

import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

# Make sibling imports work no matter which folder you launch from.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from grabber import grab_snapshot, load_cameras
from detector import load_model, find_vehicles
from occupancy import load_spots, spot_occupied, draw_debug

DB_PATH = Path(__file__).resolve().parent / "parking.db"
CHECK_INTERVAL = 120  # seconds between checks


def _ensure_column(conn, table, column, ddl):
    """Add a column to a table if it's missing (for old databases)."""
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def migrate_db(conn=None):
    """Bring an old parking.db up to the multi-camera schema."""
    close = False
    if conn is None:
        conn = sqlite3.connect(DB_PATH)
        close = True
    for table in ("readings", "events", "watchers"):
        _ensure_column(conn, table, "camera_id", "TEXT")
    # spot_state's key grows from spot_id to (camera_id, spot_id),
    # because two cameras can both have a spot called "S1".
    cols = [r[1] for r in conn.execute("PRAGMA table_info(spot_state)").fetchall()]
    if "camera_id" not in cols:
        conn.execute("""CREATE TABLE spot_state_new (
                            camera_id TEXT, spot_id TEXT,
                            confirmed INTEGER, pending INTEGER,
                            PRIMARY KEY (camera_id, spot_id))""")
        conn.execute("""INSERT INTO spot_state_new
                            (camera_id, spot_id, confirmed, pending)
                        SELECT 'lincolnville-ferry', spot_id, confirmed, pending
                        FROM spot_state""")
        conn.execute("DROP TABLE spot_state")
        conn.execute("ALTER TABLE spot_state_new RENAME TO spot_state")
    # Old rows without a camera get the ferry lot (the only camera back then).
    for table in ("readings", "events", "watchers"):
        conn.execute(f"UPDATE {table} SET camera_id = 'lincolnville-ferry' "
                     "WHERE camera_id IS NULL")
    conn.commit()
    if close:
        conn.close()


def init_db(conn=None):
    """Create the tables if they don't exist yet, then migrate old ones."""
    close = False
    if conn is None:
        conn = sqlite3.connect(DB_PATH)
        close = True
    conn.execute("""CREATE TABLE IF NOT EXISTS readings (
                        ts TEXT, camera_id TEXT, spot_id TEXT,
                        occupied INTEGER)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS spot_state (
                        camera_id TEXT, spot_id TEXT,
                        confirmed INTEGER, pending INTEGER,
                        PRIMARY KEY (camera_id, spot_id))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS events (
                        ts TEXT, camera_id TEXT, spot_id TEXT, event TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS watchers (
                        id INTEGER PRIMARY KEY, camera_id TEXT,
                        phone TEXT NOT NULL,
                        expires_at REAL NOT NULL,
                        active INTEGER NOT NULL DEFAULT 1)""")
    conn.commit()
    migrate_db(conn)
    if close:
        conn.close()


def confirm_changes(conn, states, camera_id):
    """Compare fresh states vs. confirmed ones. Return [(spot_id, event)].

    states: {spot_id: True if occupied}. A change confirms only after
    2 consecutive readings show the new state.
    """
    events = []
    for sid, occupied in states.items():
        row = conn.execute(
            "SELECT confirmed, pending FROM spot_state "
            "WHERE camera_id = ? AND spot_id = ?",
            (camera_id, sid)).fetchone()

        if row is None:
            # First reading ever: adopt it, nothing to compare against.
            conn.execute("INSERT INTO spot_state VALUES (?, ?, ?, NULL)",
                         (camera_id, sid, int(occupied)))
            continue

        confirmed, pending = row
        if occupied == confirmed:
            # Matches what we believe: clear any pending doubt.
            if pending is not None:
                conn.execute("UPDATE spot_state SET pending = NULL "
                             "WHERE camera_id = ? AND spot_id = ?",
                             (camera_id, sid))
        elif pending == int(occupied):
            # Second reading in a row with the new state: it's real.
            conn.execute("UPDATE spot_state SET confirmed = ?, pending = NULL "
                         "WHERE camera_id = ? AND spot_id = ?",
                         (int(occupied), camera_id, sid))
            event = "freed" if not occupied else "taken"
            events.append((sid, event))
            conn.execute("INSERT INTO events VALUES (?, ?, ?, ?)",
                         (datetime.now().isoformat(timespec="seconds"),
                          camera_id, sid, event))
        else:
            # First sighting of a possible change: note it, wait for backup.
            conn.execute("UPDATE spot_state SET pending = ? "
                         "WHERE camera_id = ? AND spot_id = ?",
                         (int(occupied), camera_id, sid))
    conn.commit()
    return events


def notify_watchers(conn, spot_id, camera_id):
    """Text every live watcher of this camera about the open spot, once each.

    A watch is live if it's still active and hasn't expired yet.
    One alert per subscription — after firing, the watch retires.
    Expired watches simply never fire.
    """
    now = time.time()
    rows = conn.execute(
        "SELECT id, phone FROM watchers "
        "WHERE camera_id = ? AND active = 1 AND expires_at > ?",
        (camera_id, now)).fetchall()
    for wid, phone in rows:
        # TODO: send a real SMS (Twilio). For now, print what we'd send.
        print(f"  TEXT to {phone}: spot {spot_id} just opened up!")
        conn.execute("UPDATE watchers SET active = 0 WHERE id = ?", (wid,))
    conn.commit()


def do_check(model, camera):
    """One full pass for one camera: snapshot → detect → spots → compare."""
    cid = camera["id"]
    snap = grab_snapshot(cid)
    vehicles = find_vehicles(snap, model)
    spots = load_spots(cid)
    states = {s["id"]: spot_occupied(s, vehicles) is not None for s in spots}

    # Save the "what the app sees" view for the web page.
    results = [spot_occupied(s, vehicles) for s in spots]
    draw_debug(snap, spots, results,
               Path(__file__).resolve().parent / "snapshots" / f"{cid}-latest-annotated.jpg")

    conn = sqlite3.connect(DB_PATH)
    # Retire spot IDs that are no longer on the map (e.g. after redrawing
    # in draw_spots.py). Without this, dead spots pile up in the database
    # and the web page keeps counting them.
    if states:
        placeholders = ",".join("?" * len(states))
        conn.execute(
            f"DELETE FROM spot_state WHERE camera_id = ? "
            f"AND spot_id NOT IN ({placeholders})",
            [cid] + list(states),
        )
    ts = datetime.now().isoformat(timespec="seconds")
    for sid, occupied in states.items():
        conn.execute("INSERT INTO readings VALUES (?, ?, ?, ?)",
                     (ts, cid, sid, int(occupied)))
    events = confirm_changes(conn, states, cid)

    free = sum(1 for occupied in states.values() if not occupied)
    print(f"[{ts}] {camera['name']}: {free} of {len(states)} spots free.")
    for sid, event in events:
        if event == "freed":
            print(f"  ALERT: spot {sid} just opened up!")
            notify_watchers(conn, sid, cid)
        else:
            print(f"  note: spot {sid} was taken.")
    conn.close()
    return events


def selftest():
    """Prove the 2-reading rule works, using fake states (no camera)."""
    conn = sqlite3.connect(":memory:")
    init_db(conn)
    # Spot B2: occupied, occupied, free, free → alert fires on 2nd free.
    seq = [True, True, False, False]
    fired_on = None
    for i, occupied in enumerate(seq):
        events = confirm_changes(conn, {"B2": occupied}, "test-cam")
        if events:
            fired_on = i + 1
    assert fired_on == 4, f"expected alert on reading 4, got {fired_on}"
    # A lone blip (occupied, free, occupied) must NOT alert.
    conn2 = sqlite3.connect(":memory:")
    init_db(conn2)
    blips = []
    for occupied in [True, False, True]:
        blips += confirm_changes(conn2, {"B2": occupied}, "test-cam")
    assert blips == [], f"false alarm on a blip: {blips}"
    # Two cameras must not share spot state.
    conn3 = sqlite3.connect(":memory:")
    init_db(conn3)
    confirm_changes(conn3, {"S1": True}, "cam-a")
    confirm_changes(conn3, {"S1": True}, "cam-a")
    events = confirm_changes(conn3, {"S1": False}, "cam-b")
    assert events == [], "cameras leaked into each other's state!"
    print("selftest OK: 2-reading rule holds, cameras stay separate.")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        init_db()
        model = load_model()
        cameras = load_cameras()
        print(f"Watching {len(cameras)} cameras. Ctrl+C to stop.")
        while True:
            for camera in cameras:
                do_check(model, camera)
            if "--once" in sys.argv:
                break
            time.sleep(CHECK_INTERVAL)
