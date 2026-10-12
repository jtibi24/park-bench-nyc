# grabber.py — Brick 1: download one snapshot from a public street camera.
#
# This is the first piece of the parking app. Later bricks will:
#   Brick 2: run car detection (YOLO) on the saved image
#   Brick 3: check each hand-drawn parking spot box for a car
#   Brick 4: log free/occupied spots to a database over time
#   Brick 5: show it all on a web page
#
# The camera URL is the only part tied to one specific camera.
# When the 511NY key arrives, we swap this URL — nothing else changes.

import requests
from datetime import datetime
from pathlib import Path

# Lincolnville ferry port parking lot, Maine — verified live, daylight,
# clear view of parked cars. Perfect for the parking-spot bricks.
# (Any snapshot URL works here: Utah, Caltrans, London, ...)
CAMERA_URL = "https://newengland511.org/map/Cctv/2224"

# Folder where snapshots land, next to this script.
SAVE_DIR = Path(__file__).resolve().parent / "snapshots"
SAVE_DIR.mkdir(exist_ok=True)

# Ask the camera for one JPEG. The User-Agent header matters:
# some camera servers ignore requests that don't look like a browser.
def grab_snapshot():
    """Download one snapshot; return the Path of the saved file."""
    response = requests.get(
        CAMERA_URL,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=25,
    )
    response.raise_for_status()  # crash loudly instead of saving an error page

    # Name the file with the capture time so every snapshot is unique.
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = SAVE_DIR / f"snapshot-{stamp}.jpg"
    path.write_bytes(response.content)
    return path


if __name__ == "__main__":
    path = grab_snapshot()
    print(f"Saved {path} ({path.stat().st_size} bytes)")
