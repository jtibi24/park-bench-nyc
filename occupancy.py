# occupancy.py — Brick 3: which parking spots are free?
#
# The key idea: we do NOT ask AI to find parking spots. Spots don't move,
# so we draw each one once (the boxes below, in pixels) and then just ask:
# "is there a car inside this box right now?"
#
# How a spot is judged occupied: if a detected vehicle's box covers at
# least a quarter of the spot's box, the spot is occupied. (An earlier
# version checked only the vehicle's center point, but that was too
# strict — a slightly misdrawn box made parked cars read as free.)
# Simple, visual, and easy to sanity-check on the photo.
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

# Each spot: an id and a rectangle (left, top, right, bottom) in pixels.
SPOTS = [
    # A row — along the grass on the left
    {"id": "A1", "box": (0, 410, 110, 600)},
    {"id": "A2", "box": (0, 415, 145, 545)},
    {"id": "A3", "box": (55, 365, 215, 495)},
    # B row — foreground, along the stone wall
    {"id": "B1", "box": (225, 335, 440, 485)},
    {"id": "B2", "box": (440, 435, 585, 565)},   # looked empty
    {"id": "B3", "box": (580, 455, 725, 595)},
    {"id": "B4", "box": (715, 370, 875, 510)},
    {"id": "B5", "box": (860, 340, 1000, 495)},
    # C row — background, by the white building
    {"id": "C1", "box": (615, 295, 785, 405)},
    {"id": "C2", "box": (795, 295, 945, 415)},
]

# If you've drawn your own boxes with draw_spots.py, spots.json takes
# over automatically — no need to edit the list above by hand.
_spots_file = Path(__file__).resolve().parent / "spots.json"
if _spots_file.exists():
    import json
    SPOTS = [{"id": s["id"], "box": tuple(s["box"])}
             for s in json.loads(_spots_file.read_text())]
    print(f"Using {len(SPOTS)} spots from spots.json.")


def spot_occupied(spot, vehicles, min_overlap=0.25):
    """The vehicle covering most of the spot, or None if it's free.

    A spot is occupied when some vehicle's box overlaps at least
    min_overlap (default 25%) of the spot's own area.
    """
    x1, y1, x2, y2 = spot["box"]
    spot_area = max(0, x2 - x1) * max(0, y2 - y1)
    if spot_area == 0:
        return None
    for v in vehicles:
        vx1, vy1, vx2, vy2 = v["box"]
        ix1, iy1 = max(x1, vx1), max(y1, vy1)
        ix2, iy2 = min(x2, vx2), min(y2, vy2)
        overlap = max(0, ix2 - ix1) * max(0, iy2 - iy1)
        if overlap / spot_area >= min_overlap:
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
    latest = latest_snapshot()
    print(f"Checking spots on {latest.name}...")

    model = load_model()
    vehicles = find_vehicles(latest, model)

    results = []
    for spot in SPOTS:
        taken_by = spot_occupied(spot, vehicles)
        results.append(taken_by)
        if taken_by:
            print(f"  {spot['id']}: OCCUPIED ({taken_by['label']}, "
                  f"sure {taken_by['confidence']:.0%})")
        else:
            print(f"  {spot['id']}: free")

    free = sum(1 for r in results if r is None)
    print(f"\n{free} of {len(SPOTS)} spots free.")

    out = Path(__file__).resolve().parent / "snapshots" / (
        "annotated-" + latest.stem.replace("snapshot-", "") + ".jpg")
    draw_debug(latest, SPOTS, results, out)
    print(f"Debug image: {out.name} (green=free, red=occupied)")
