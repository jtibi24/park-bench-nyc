# monitor.py — Brick 4: watch the lot over time, alert when a spot opens.
#
# Every CHECK_INTERVAL seconds it runs the whole pipeline:
#   snapshot (brick 1) → detect cars (brick 2) → check spots (brick 3)
# then compares the fresh states against the database.
#
# A spot only counts as "changed" after 2 readings in a row agree.
# One odd frame (a passing truck blocking the view) can't fake a
# "spot freed!" alert.
#
# Tables in parking.db:
#   readings   — every check: when, which spot, occupied (1) or free (0)
#   spot_state — per spot: last confirmed state + a pending unconfirmed one
#   events     — every confirmed change: when, which spot, freed or taken

import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

# Make sibling imports work no matter which folder you launch from.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from grabber import grab_snapshot
from detector import load_model, find_vehicles
from occupancy import SPOTS, spot_occupied, draw_debug

DB_PATH = Path(__file__).resolve().parent / "parking.db"
CHECK_INTERVAL = 120  # seconds between checks


def init_db(conn=None):
    """Create the tables if they don't exist yet."""
    close = False
    if conn is None:
        conn = sqlite3.connect(DB_PATH)
        close = True
    conn.execute("""CREATE TABLE IF NOT EXISTS readings (
                        ts TEXT, spot_id TEXT, occupied INTEGER)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS spot_state (
                        spot_id TEXT PRIMARY KEY,
                        confirmed INTEGER, pending INTEGER)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS events (
                        ts TEXT, spot_id TEXT, event TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS watchers (
                        id INTEGER PRIMARY KEY,
                        phone TEXT NOT NULL,
                        expires_at REAL NOT NULL,
                        active INTEGER NOT NULL DEFAULT 1)""")
    conn.commit()
    if close:
        conn.close()


def confirm_changes(conn, states):
    """Compare fresh states vs. confirmed ones. Return [(spot_id, event)].

    states: {spot_id: True if occupied}. A change confirms only after
    2 consecutive readings show the new state.
    """
    events = []
    for sid, occupied in states.items():
        row = conn.execute(
            "SELECT confirmed, pending FROM spot_state WHERE spot_id = ?",
            (sid,)).fetchone()

        if row is None:
            # First reading ever: adopt it, nothing to compare against.
            conn.execute("INSERT INTO spot_state VALUES (?, ?, NULL)",
                         (sid, int(occupied)))
            continue

        confirmed, pending = row
        if occupied == confirmed:
            # Matches what we believe: clear any pending doubt.
            if pending is not None:
                conn.execute("UPDATE spot_state SET pending = NULL "
                             "WHERE spot_id = ?", (sid,))
        elif pending == int(occupied):
            # Second reading in a row with the new state: it's real.
            conn.execute("UPDATE spot_state SET confirmed = ?, pending = NULL "
                         "WHERE spot_id = ?", (int(occupied), sid))
            event = "freed" if not occupied else "taken"
            events.append((sid, event))
            conn.execute("INSERT INTO events VALUES (?, ?, ?)",
                         (datetime.now().isoformat(timespec="seconds"),
                          sid, event))
        else:
            # First sighting of a possible change: note it, wait for backup.
            conn.execute("UPDATE spot_state SET pending = ? WHERE spot_id = ?",
                         (int(occupied), sid))
    conn.commit()
    return events


def notify_watchers(conn, spot_id):
    """Text every live watcher about the newly opened spot, once each.

    A watch is live if it's still active and hasn't expired yet.
    One alert per subscription — after firing, the watch retires.
    Expired watches simply never fire.
    """
    now = time.time()
    rows = conn.execute(
        "SELECT id, phone FROM watchers WHERE active = 1 AND expires_at > ?",
        (now,)).fetchall()
    for wid, phone in rows:
        # TODO: send a real SMS (Twilio). For now, print what we'd send.
        print(f"  TEXT to {phone}: spot {spot_id} just opened up!")
        conn.execute("UPDATE watchers SET active = 0 WHERE id = ?", (wid,))
    conn.commit()


def do_check(model):
    """One full pass: snapshot → detect → spots → compare → alert."""
    snap = grab_snapshot()
    vehicles = find_vehicles(snap, model)
    states = {s["id"]: spot_occupied(s, vehicles) is not None for s in SPOTS}

    # Save the "what the app sees" view for the web page.
    results = [spot_occupied(s, vehicles) for s in SPOTS]
    draw_debug(snap, SPOTS, vehicles, results,
               Path(__file__).resolve().parent / "snapshots" / "latest-annotated.jpg")

    conn = sqlite3.connect(DB_PATH)
    # Retire spot IDs that are no longer on the map (e.g. after redrawing
    # in draw_spots.py). Without this, dead spots pile up in the database
    # and the web page keeps counting them.
    if states:
        conn.execute(
            "DELETE FROM spot_state WHERE spot_id NOT IN (%s)"
            % ",".join("?" * len(states)),
            list(states),
        )
    ts = datetime.now().isoformat(timespec="seconds")
    for sid, occupied in states.items():
        conn.execute("INSERT INTO readings VALUES (?, ?, ?)",
                     (ts, sid, int(occupied)))
    events = confirm_changes(conn, states)

    free = sum(1 for occupied in states.values() if not occupied)
    print(f"[{ts}] {free} of {len(states)} spots free.")
    for sid, event in events:
        if event == "freed":
            print(f"  ALERT: spot {sid} just opened up!")
            notify_watchers(conn, sid)
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
        events = confirm_changes(conn, {"B2": occupied})
        if events:
            fired_on = i + 1
    assert fired_on == 4, f"expected alert on reading 4, got {fired_on}"
    # A lone blip (occupied, free, occupied) must NOT alert.
    conn2 = sqlite3.connect(":memory:")
    init_db(conn2)
    blips = []
    for occupied in [True, False, True]:
        blips += confirm_changes(conn2, {"B2": occupied})
    assert blips == [], f"false alarm on a blip: {blips}"
    print("selftest OK: alert fires on 2nd confirming reading, blips ignored.")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        init_db()
        model = load_model()
        print("Watching the lot. Ctrl+C to stop.")
        while True:
            do_check(model)
            if "--once" in sys.argv:
                break
            time.sleep(CHECK_INTERVAL)
