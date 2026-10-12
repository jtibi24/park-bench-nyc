# grabber.py — Brick 1: download one snapshot from a public street camera.
#
# This is the first piece of the parking app. Later bricks will:
#   Brick 2: run car detection (YOLO) on the saved image
#   Brick 3: check each hand-drawn parking spot box for a car
#   Brick 4: log free/occupied spots to a database over time
#   Brick 5: show it all on a web page
#
# Cameras live in cameras.json (the "rolodex"). To add a camera, add an
# entry there — nothing else changes.

import json
import requests
from datetime import datetime
from pathlib import Path

# The rolodex: every camera the app watches.
# Each entry: id (short, no spaces), name (shown on the web page),
# url (the snapshot feed).
CAMERAS_FILE = Path(__file__).resolve().parent / "cameras.json"


def load_cameras():
    """The full rolodex, as a list of dicts."""
    return json.loads(CAMERAS_FILE.read_text())


def get_camera(camera_id):
    """One camera's entry, by id. Crashes loudly on an unknown id."""
    for cam in load_cameras():
        if cam["id"] == camera_id:
            return cam
    raise ValueError(f"Unknown camera id: {camera_id!r}")


# Folder where snapshots land, next to this script.
SAVE_DIR = Path(__file__).resolve().parent / "snapshots"
SAVE_DIR.mkdir(exist_ok=True)

# Ask the camera for one JPEG. The User-Agent header matters:
# some camera servers ignore requests that don't look like a browser.
def grab_snapshot(camera_id="lincolnville-ferry"):
    """Download one snapshot for a camera; return the Path of the saved file."""
    cam = get_camera(camera_id)
    response = requests.get(
        cam["url"],
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=25,
    )
    response.raise_for_status()  # crash loudly instead of saving an error page

    # Name the file with the camera and capture time so every snapshot is unique.
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = SAVE_DIR / f"{camera_id}-{stamp}.jpg"
    path.write_bytes(response.content)
    return path


if __name__ == "__main__":
    import sys
    camera_id = sys.argv[1] if len(sys.argv) > 1 else "lincolnville-ferry"
    path = grab_snapshot(camera_id)
    print(f"Saved {path} ({path.stat().st_size} bytes)")
