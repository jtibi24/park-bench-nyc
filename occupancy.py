# occupancy.py — Brick 3: which parking spots are free?
#
# The key idea: we do NOT ask AI to find parking spots. Spots don't move,
# so we draw each one once (the boxes below, in pixels) and then just ask:
# "is there a car inside this box right now?"
#
# How a spot is judged occupied: take the center point of the hand-drawn
# spot box. If that point falls inside any detected vehicle box, the spot
# is occupied. The boxes are meant to be small (one per stall, even when
# stalls are stacked tight) — the test is just "is this stall's middle
# inside a car?" Simple, visual, and easy to sanity-check on the photo.
#
# The SPOTS below are eyeball estimates from the Lincolnville ferry lot
# camera (1024x829). If the camera moves, these must be redrawn.
# Tune them by looking at annotated-<time>.jpg that this script saves.

from pathlib import Path
import sys
from PIL import Image, ImageDraw

# Make sibling imports work no matter which folder you launch from.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from detector import load_model, find_vehicles, latest_snapshot

# Each camera has its own map file: spots-<camera-id>.json, drawn once
# with draw_spots.py. (Before per-camera files existed, a single
# spots.json served the ferry lot — still honored for that camera.)
def spots_file(camera_id):
    return Path(__file__).resolve().parent / f"spots-{camera_id}.json"


def load_spots(camera_id="lincolnville-ferry"):
    """The parking-spot map for one camera, as a list of dicts."""
    import json
    paths = [spots_file(camera_id)]
    if camera_id == "lincolnville-ferry":
        paths.append(Path(__file__).resolve().parent / "spots.json")  # legacy
    for path in paths:
        if path.exists():
            spots = [{"id": s["id"], "box": tuple(s["box"])}
                     for s in json.loads(path.read_text())]
            print(f"Using {len(spots)} spots from {path.name}.")
            return spots
    print(f"No spot map for {camera_id!r} yet — draw one with draw_spots.py.")
    return []


# The ferry lot map, for the scripts that haven't learned camera ids yet
# (monitor.py, app.py — brick 3 teaches them).
SPOTS = load_spots("lincolnville-ferry")


def spot_occupied(spot, vehicles):
    """The vehicle parked in the spot, or None if it's free.

    Takes the center of the hand-drawn spot box; if that point is inside
    any vehicle's box, the spot is occupied.
    """
    x1, y1, x2, y2 = spot["box"]
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2  # center of the drawn spot
    for v in vehicles:
        vx1, vy1, vx2, vy2 = v["box"]
        if vx1 <= cx <= vx2 and vy1 <= cy <= vy2:
            return v
    return None


def draw_debug(image_path, spots, results, out_path):
    """Save a copy of the photo with spots drawn on it.

    Green = free, red = occupied.
    This is how you check whether the spot boxes are drawn right.
    """
    img = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(img)
    for spot, taken_by in zip(spots, results):
        color = "red" if taken_by else "green"
        draw.rectangle(spot["box"], outline=color, width=3)
        draw.text((spot["box"][0] + 4, spot["box"][1] + 4), spot["id"], fill=color)
    img.save(out_path)


if __name__ == "__main__":
    import sys
    camera_id = sys.argv[1] if len(sys.argv) > 1 else "lincolnville-ferry"
    spots = load_spots(camera_id)
    latest = latest_snapshot(camera_id)
    print(f"Checking spots on {latest.name}...")

    model = load_model()
    vehicles = find_vehicles(latest, model)

    results = []
    for spot in spots:
        taken_by = spot_occupied(spot, vehicles)
        results.append(taken_by)
        if taken_by:
            print(f"  {spot['id']}: OCCUPIED ({taken_by['label']}, "
                  f"sure {taken_by['confidence']:.0%})")
        else:
            print(f"  {spot['id']}: free")

    free = sum(1 for r in results if r is None)
    print(f"\n{free} of {len(spots)} spots free.")

    out = Path(__file__).resolve().parent / "snapshots" / (
        "annotated-" + latest.stem + ".jpg")
    draw_debug(latest, spots, results, out)
    print(f"Debug image: {out.name} (green=free, red=occupied)")
