# vision/roi_tool.py
import json
from pathlib import Path
import cv2

# ROI를 찍을 순서
ROI_ORDER = ["feed", "water", "door"]

def main():
    base = Path(__file__).resolve().parents[1]
    video_path = base / "data" / "sample.mp4"
    out_path = base / "configs" / "roi.json"

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")

    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise RuntimeError("Failed to read first frame from video.")

    h, w = frame.shape[:2]
    camera_id = "farm1_cam1"

    state = {
        "camera_id": camera_id,
        "width": w,
        "height": h,
        "rois": {name: [] for name in ROI_ORDER}
    }

    roi_idx = 0
    current_pts = []
    win = "ROI Tool | Left: add point | Right: undo | Enter: save ROI | S: save & exit"
    disp = frame.copy()

    def to_np(pts):
        import numpy as np
        return np.array(pts, dtype="int32").reshape((-1, 1, 2))

    def redraw():
        nonlocal disp
        disp = frame.copy()

        # 이미 저장된 ROI들
        for name, pts in state["rois"].items():
            if len(pts) >= 3:
                cv2.polylines(disp, [to_np(pts)], True, (0, 255, 0), 2)
                cv2.putText(disp, name, tuple(pts[0]),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

        # 현재 그리고 있는 ROI
        if current_pts:
            for p in current_pts:
                cv2.circle(disp, tuple(p), 4, (0, 0, 255), -1)
            if len(current_pts) >= 2:
                cv2.polylines(disp, [to_np(current_pts)], False, (0, 0, 255), 2)

        name = ROI_ORDER[roi_idx]
        cv2.putText(
            disp,
            f"Current ROI: {name} | points: {len(current_pts)}",
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.9,
            (255, 255, 255),
            2
        )

    def on_mouse(event, x, y, flags, param):
        nonlocal current_pts
        if event == cv2.EVENT_LBUTTONDOWN:
            current_pts.append([x, y])
            redraw()
        elif event == cv2.EVENT_RBUTTONDOWN:
            if current_pts:
                current_pts.pop()
                redraw()

    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(win, on_mouse)
    redraw()

    while True:
        cv2.imshow(win, disp)
        key = cv2.waitKey(20) & 0xFF

        if key == 27:  # ESC
            print("Exit without saving.")
            break

        if key == 13:  # Enter
            name = ROI_ORDER[roi_idx]
            if len(current_pts) < 3:
                print(f"[{name}] Need at least 3 points.")
                continue
            state["rois"][name] = current_pts.copy()
            print(f"Saved ROI '{name}'")
            current_pts = []
            if roi_idx < len(ROI_ORDER) - 1:
                roi_idx += 1
            redraw()

        if key in (ord("s"), ord("S")):
            out_path.write_text(
                json.dumps(
                    {"camera_id": state["camera_id"], "rois": state["rois"]},
                    ensure_ascii=False,
                    indent=2
                ),
                encoding="utf-8"
            )
            print(f"Saved -> {out_path}")
            break

    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
