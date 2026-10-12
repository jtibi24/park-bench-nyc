# detector.py — Brick 2: find vehicles in the latest snapshot.
#
# Uses YOLO, a pre-trained object detector. It already knows what a
# car, truck, and bus look like — no training needed on our part.
# We point it at our snapshot and ask "what vehicles do you see?"
#
# Later bricks will:
#   Brick 3: check each hand-drawn parking spot box for a car
#   Brick 4: log free/occupied spots to a database over time
#   Brick 5: show it all on a web page

from pathlib import Path
from ultralytics import YOLO

SNAPSHOT_DIR = Path(__file__).resolve().parent / "snapshots"

# YOLO knows 80 everyday things; we only care about vehicles.
VEHICLES = {"car", "truck", "bus", "motorcycle"}


def load_model():
    # The nano model: smallest and fastest, plenty for parked cars.
    # Downloads itself on first run (~6 MB), then lives on disk after that.
    # Anchor to the script's folder: launching from another folder must not
    # trigger a re-download.
    model_path = Path(__file__).resolve().parent / "yolov8n.pt"
    return YOLO(str(model_path))


def find_vehicles(image_path, model):
    """Run detection on one image.

    Returns a list of dicts: {"label": "car", "confidence": 0.91,
    "box": (x1, y1, x2, y2)} — box corners in pixels.
    """
    # results[0] is our one image; .boxes holds what was found.
    results = model(str(image_path), verbose=False)
    boxes = results[0].boxes

    found = []
    for box in boxes:
        label = model.names[int(box.cls[0])]   # the word, e.g. "car"
        confidence = float(box.conf[0])        # 0.0–1.0, how sure the model is
        if label in VEHICLES and confidence >= 0.4:
            x1, y1, x2, y2 = (int(v) for v in box.xyxy[0])
            found.append({"label": label, "confidence": confidence,
                          "box": (x1, y1, x2, y2)})
    return found


def latest_snapshot():
    """Newest snapshot saved by grabber.py."""
    return max(SNAPSHOT_DIR.glob("snapshot-*.jpg"), key=lambda p: p.stat().st_mtime)


if __name__ == "__main__":
    model = load_model()
    latest = latest_snapshot()
    print(f"Scanning {latest.name}...")
    vehicles = find_vehicles(latest, model)
    for v in vehicles:
        x1, y1, x2, y2 = v["box"]
        print(f"  {v['label']:10s} sure {v['confidence']:.0%}   at ({x1},{y1})-({x2},{y2})")
    print(f"\n{len(vehicles)} vehicles detected.")
