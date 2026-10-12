# draw_spots.py — draw parking spot boxes with your mouse.
#
# Run:  python draw_spots.py
#   Your existing spots load automatically — drag rectangles over the
#   missing spaces only. Boxes save to spots.json the instant you draw
#   them, so your work is never lost. U = undo | C = clear | Q = quit.
#
# occupancy.py automatically uses spots.json when it exists.

import json
import sys
from pathlib import Path

# Make sibling imports work no matter which folder you launch from.
sys.path.insert(0, str(Path(__file__).parent))

try:
    import cv2
except ImportError:
    print("This tool needs OpenCV:  pip install opencv-python")
    sys.exit(1)

from detector import latest_snapshot
from occupancy import SPOTS  # your current map, so you only draw what's missing

# Each spot is [id, (x1, y1, x2, y2)]. Start with the existing map loaded —
# draw only the new/missing spaces, or press C to clear and start fresh.
spots = [[s["id"], tuple(s["box"])] for s in SPOTS]
print(f"Loaded {len(spots)} existing spots. Draw more, or press C to start over.")
drawing = False
start = None
display = None


def redraw():
    """Repaint the photo with all boxes drawn on it."""
    global display
    display = img.copy()
    for sid, (x1, y1, x2, y2) in spots:
        cv2.rectangle(display, (x1, y1), (x2, y2), (0, 0, 255), 2)
        cv2.putText(display, sid, (x1 + 4, y1 + 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)


def on_mouse(event, x, y, flags, param):
    """Called by OpenCV on every mouse movement/click."""
    global drawing, start, display
    if event == cv2.EVENT_LBUTTONDOWN:
        drawing = True
        start = (x, y)
    elif event == cv2.EVENT_MOUSEMOVE and drawing:
        # Live preview of the box while dragging.
        display = img.copy()
        for sid, (bx1, by1, bx2, by2) in spots:
            cv2.rectangle(display, (bx1, by1), (bx2, by2), (0, 0, 255), 2)
        cv2.rectangle(display, start, (x, y), (0, 255, 0), 2)
    elif event == cv2.EVENT_LBUTTONUP:
        drawing = False
        x1, y1 = start
        x2, y2 = x, y
        # Store as (left, top, right, bottom) regardless of drag direction.
        new_id = f"S{len(spots) + 1}"
        spots.append([new_id, (min(x1, x2), min(y1, y2),
                               max(x1, x2), max(y1, y2))])
        redraw()
        save()  # auto-save: your work is never lost, even if you X the window


def save():
    out = Path(__file__).parent / "spots.json"
    data = [{"id": sid, "box": list(b)} for sid, b in spots]
    out.write_text(json.dumps(data, indent=1))
    print(f"Saved {len(spots)} spots to {out.name}.")


latest = latest_snapshot()
img = cv2.imread(str(latest))
if img is None:
    print(f"Couldn't read {latest}")
    sys.exit(1)

redraw()
cv2.namedWindow("draw spots - drag boxes, S=save, Q=quit")
cv2.setMouseCallback("draw spots - drag boxes, S=save, Q=quit", on_mouse)
print("Drag a box over each real parking space.")
print("Keys: U undo | C clear | S save | Q quit")

while True:
    cv2.imshow("draw spots - drag boxes, S=save, Q=quit", display)
    key = cv2.waitKey(30) & 0xFF
    if key == ord("q"):
        break
    elif key == ord("u") and spots:
        spots.pop()
        redraw()
        save()  # keep the file in sync
    elif key == ord("c"):
        spots.clear()
        redraw()
        save()  # keep the file in sync
    elif key == ord("s"):
        save()

cv2.destroyAllWindows()
