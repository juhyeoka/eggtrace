import cv2
import math
import numpy as np

class EventEngine:
    def __init__(self, rois, cfg):
        self.cfg = cfg
        self.prev_gray = None
        self.last_fire = 0.0

        self.motion_threshold = float(cfg.get("motion_threshold", 0.01))
        self.cooldown_sec = float(cfg.get("cooldown_sec", 3))

        self.roi_mode = str(cfg.get("roi_mode", "grid"))
        self.grid_rows = int(cfg.get("grid_rows", 2))
        self.grid_cols = int(cfg.get("grid_cols", 2))
        self.roi_activity_threshold = float(cfg.get("roi_activity_threshold", 0.02))

        # heatmap
        self.heatmap_decay = float(cfg.get("heatmap_decay", 0.95))
        self.acc = None  # float32 accumulator

        # optical flow
        self.enable_flow = bool(cfg.get("enable_optical_flow", True))
        self.flow_downscale = float(cfg.get("flow_downscale", 0.5))

        # compactness
        self.enable_compactness = bool(cfg.get("enable_compactness", True))
        self.compactness_min_area = int(cfg.get("compactness_min_area", 80))

    def _grid_rois(self, h, w):
        rois = {}
        rh = h / self.grid_rows
        rw = w / self.grid_cols
        idx = 0
        for r in range(self.grid_rows):
            for c in range(self.grid_cols):
                y1 = int(round(r * rh))
                y2 = int(round((r + 1) * rh))
                x1 = int(round(c * rw))
                x2 = int(round((c + 1) * rw))
                rois[f"zone{idx}"] = (x1, y1, x2, y2)
                idx += 1
        return rois

    def _make_heatmap_image(self):
        if self.acc is None:
            return None
        acc_norm = cv2.normalize(self.acc, None, 0, 255, cv2.NORM_MINMAX).astype("uint8")
        heat = cv2.applyColorMap(acc_norm, cv2.COLORMAP_JET)
        return heat

    def _angle_to_dir(self, angle_deg: float) -> str:
        a = angle_deg % 360.0
        if (a >= 315) or (a < 45):
            return "→"
        if 45 <= a < 135:
            return "↓"
        if 135 <= a < 225:
            return "←"
        return "↑"

    def _flow_stats(self, prev_gray, gray, rois):
        if not self.enable_flow:
            return None

        scale = self.flow_downscale
        if not (0.1 <= scale <= 1.0):
            scale = 0.5

        if scale < 1.0:
            prev_s = cv2.resize(prev_gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
            gray_s = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        else:
            prev_s, gray_s = prev_gray, gray

        flow = cv2.calcOpticalFlowFarneback(
            prev_s, gray_s, None,
            pyr_scale=0.5, levels=3, winsize=15,
            iterations=3, poly_n=5, poly_sigma=1.2, flags=0
        )
        vx = flow[..., 0]
        vy = flow[..., 1]
        mag = np.sqrt(vx * vx + vy * vy)

        mvx = float(np.mean(vx))
        mvy = float(np.mean(vy))
        mean_mag = float(np.mean(mag))
        mean_angle = (math.degrees(math.atan2(mvy, mvx)) + 360.0) % 360.0
        mean_dir = self._angle_to_dir(mean_angle)

        roi_flow = {}
        for name, (x1, y1, x2, y2) in rois.items():
            xs1 = int(round(x1 * scale))
            ys1 = int(round(y1 * scale))
            xs2 = int(round(x2 * scale))
            ys2 = int(round(y2 * scale))
            xs1 = max(0, xs1); ys1 = max(0, ys1)
            xs2 = max(xs1 + 1, xs2); ys2 = max(ys1 + 1, ys2)

            rvx = vx[ys1:ys2, xs1:xs2]
            rvy = vy[ys1:ys2, xs1:xs2]
            rmag = mag[ys1:ys2, xs1:xs2]

            rmvx = float(np.mean(rvx))
            rmvy = float(np.mean(rvy))
            rmean_mag = float(np.mean(rmag))
            rmean_angle = (math.degrees(math.atan2(rmvy, rmvx)) + 360.0) % 360.0

            roi_flow[name] = {
                "mag": round(rmean_mag, 4),
                "angle": round(rmean_angle, 1),
                "dir": self._angle_to_dir(rmean_angle),
            }

        return {
            "flow_mean_mag": round(mean_mag, 4),
            "flow_mean_angle": round(mean_angle, 1),
            "flow_direction": mean_dir,
            "roi_flow": roi_flow,
        }

    def _compactness_stats(self, th_mask):
        """
        motion mask(th_mask)에서 connected components 기반
        - blob_count
        - blob_total_area
        - blob_max_area_ratio
        - compactness (0~1): 한 덩어리로 뭉칠수록 1에 가까움
        """
        if not self.enable_compactness:
            return None

        # morphology로 노이즈 정리
        kernel = np.ones((3, 3), np.uint8)
        m = cv2.morphologyEx(th_mask, cv2.MORPH_OPEN, kernel, iterations=1)
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, kernel, iterations=1)

        num, labels, stats, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
        # stats: [label, x, y, w, h, area]
        areas = []
        for i in range(1, num):  # 0은 background
            area = int(stats[i, cv2.CC_STAT_AREA])
            if area >= self.compactness_min_area:
                areas.append(area)

        if not areas:
            return {
                "blob_count": 0,
                "blob_total_area": 0,
                "blob_max_area_ratio": 0.0,
                "cluster_compactness": 0.0,
                "cluster_state": "none",
            }

        total = int(sum(areas))
        mx = int(max(areas))
        max_ratio = float(mx / total) if total > 0 else 0.0

        # compactness: 최대 덩어리가 전체 중 차지하는 비율을 기본으로,
        # blob 개수가 많을수록 감점
        blob_count = len(areas)
        compactness = max_ratio * (1.0 / (1.0 + 0.15 * (blob_count - 1)))
        compactness = float(max(0.0, min(1.0, compactness)))

        if compactness >= 0.65:
            state = "compact"
        elif compactness >= 0.35:
            state = "mixed"
        else:
            state = "spread"

        return {
            "blob_count": blob_count,
            "blob_total_area": total,
            "blob_max_area_ratio": round(max_ratio, 3),
            "cluster_compactness": round(compactness, 3),
            "cluster_state": state,
        }

    def update(self, ts, frame):
        events = []

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (7, 7), 0)

        if self.prev_gray is None:
            self.prev_gray = gray
            h, w = gray.shape[:2]
            self.acc = np.zeros((h, w), dtype=np.float32)
            return events

        prev_gray = self.prev_gray
        diff = cv2.absdiff(prev_gray, gray)
        self.prev_gray = gray

        _, th = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
        motion_ratio = float((th > 0).mean())

        # heatmap 누적
        self.acc *= self.heatmap_decay
        self.acc += (th.astype("float32") / 255.0)

        h, w = th.shape[:2]
        rois = self._grid_rois(h, w) if self.roi_mode == "grid" else {}

        roi_activity = {}
        for name, (x1, y1, x2, y2) in rois.items():
            roi = th[y1:y2, x1:x2]
            roi_activity[name] = float((roi > 0).mean())

        top2 = sorted(roi_activity.items(), key=lambda kv: kv[1], reverse=True)[:2]
        top_zones = [k for k, v in top2 if v is not None]

        if (ts - self.last_fire) < self.cooldown_sec:
            return events

        roi_peak = max(roi_activity.values()) if roi_activity else 0.0
        triggered = (motion_ratio >= self.motion_threshold) or (roi_peak >= self.roi_activity_threshold)

        if triggered:
            self.last_fire = ts
            heat_img = self._make_heatmap_image()

            flow_stats = self._flow_stats(prev_gray, gray, rois)
            comp_stats = self._compactness_stats(th)

            evt = {
                "time": ts,
                "event_type": "activity_detected",
                "motion_ratio": motion_ratio,
                "roi_activity": roi_activity,
                "roi_peak": float(roi_peak),
                "active_zones_top2": top_zones,
                "confidence": 1.0,
                "_heatmap_img": heat_img,
            }
            if flow_stats:
                evt.update(flow_stats)
            if comp_stats:
                evt.update(comp_stats)

            events.append(evt)

        return events
