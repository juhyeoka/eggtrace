import cv2

class EventEngine:
    def __init__(self, rois, cfg):
        self.cfg = cfg
        self.prev_gray = None
        self.last_fire = 0.0

        self.motion_threshold = float(cfg.get("motion_threshold", 0.01))
        self.cooldown_sec = float(cfg.get("cooldown_sec", 2))

    def update(self, ts, frame):
        events = []

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (7, 7), 0)

        if self.prev_gray is None:
            self.prev_gray = gray
            return events

        diff = cv2.absdiff(self.prev_gray, gray)
        _, th = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
        motion_ratio = float((th > 0).mean())

        self.prev_gray = gray

        if (ts - self.last_fire) < self.cooldown_sec:
            return events

        if motion_ratio >= self.motion_threshold:
            self.last_fire = ts
            events.append({
                "time": ts,
                "event_type": "motion_detected",
                "motion_ratio": motion_ratio,
            })

        return events
