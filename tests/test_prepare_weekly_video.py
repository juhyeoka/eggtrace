"""Regression checks for weekly publication safety and motion measurements."""

import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np


SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "prepare_weekly_video.py"
SPEC = importlib.util.spec_from_file_location("prepare_weekly_video", SCRIPT)
weekly = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = weekly
SPEC.loader.exec_module(weekly)


class WeeklyVideoTests(unittest.TestCase):
    def test_camera_translation_is_not_reported_as_bird_motion(self):
        random = np.random.default_rng(12)
        background = random.integers(30, 200, (200, 300), dtype=np.uint8)
        background = cv2.GaussianBlur(background, (5, 5), 0)
        shifted = cv2.warpAffine(background, np.float32([[1, 0, 6], [0, 1, 4]]), (300, 200), borderMode=cv2.BORDER_REPLICATE)
        shifted = np.clip(shifted.astype(np.int16) + 7, 0, 255).astype(np.uint8)
        measurement, mask, _ = weekly.measure_motion(background, shifted)
        self.assertTrue(measurement["cameraCompensated"])
        self.assertLess(measurement["motionPercent"], 0.5)
        self.assertLess(np.count_nonzero(mask), mask.size * 0.005)

    def test_portrait_zone_uses_actual_lower_right_of_image(self):
        random = np.random.default_rng(14)
        before = cv2.GaussianBlur(random.integers(20, 150, (480, 270), dtype=np.uint8), (5, 5), 0)
        after = before.copy()
        after[350:430, 195:250] = 250
        measurement, _, _ = weekly.measure_motion(before, after)
        self.assertEqual(measurement["dominantZone"], "우측 하단")
        self.assertGreater(measurement["motionPercent"], 1)

    def test_failed_preparation_never_replaces_active_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source = directory / "private-input.mp4"
            source.write_bytes(b"source")
            manifest = directory / "active.json"
            original = b'{"version":"previous-valid-release"}\n'
            manifest.write_bytes(original)
            info = weekly.VideoInfo(1080, 1920, 22, 30)
            with patch.object(weekly, "probe_video", return_value=info), patch.object(weekly, "encode_original", side_effect=RuntimeError("encoder unavailable")):
                with self.assertRaisesRegex(RuntimeError, "encoder unavailable"):
                    weekly.prepare_video(source, week="2026-11-09", output_root=directory / "weekly", manifest_path=manifest)
            self.assertEqual(manifest.read_bytes(), original)
            self.assertEqual(list((directory / "weekly").iterdir()), [])
            self.assertEqual(list(directory.glob(".weekly-staging-*")), [])

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg tools are required")
    def test_portrait_release_has_one_timeline_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source = directory / "private-owner-name.mp4"
            writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*"mp4v"), 24, (96, 160))
            self.assertTrue(writer.isOpened())
            random = np.random.default_rng(19)
            background = random.integers(30, 140, (160, 96, 3), dtype=np.uint8)
            for index in range(48):
                frame = background.copy()
                cv2.rectangle(frame, (20 + index // 4, 80), (40 + index // 4, 110), (240, 240, 240), -1)
                writer.write(frame)
            writer.release()
            active = directory / "active.json"
            manifest = weekly.prepare_video(source, week="2026-11-09", output_root=directory / "weekly", manifest_path=active, observation="닭들이 지내는 모습을 담았어요.")
            self.assertEqual((manifest["width"], manifest["height"]), (96, 160))
            self.assertAlmostEqual(manifest["duration"], 2, places=2)
            self.assertNotIn(source.name, json.dumps(manifest))
            release = directory / "weekly" / manifest["version"]
            analysis = json.loads((release / "analysis.json").read_text())
            self.assertFalse(analysis["frames"][0]["measured"])
            measured = [frame for frame in analysis["frames"] if frame["measured"]]
            self.assertEqual(analysis["summary"]["measuredCount"], len(measured))
            self.assertAlmostEqual(analysis["summary"]["averageMotionPercent"], round(float(np.mean([frame["motionPercent"] for frame in measured])), 2))
            for mode in weekly.MODES:
                info = weekly.probe_video(release / f"{mode}.mp4")
                self.assertEqual((info.width, info.height), (96, 160))
                self.assertAlmostEqual(info.duration, manifest["duration"], places=2)
            with patch.object(weekly, "encode_original", side_effect=AssertionError("immutable release should be reused")):
                again = weekly.prepare_video(source, week="2026-11-09", output_root=directory / "weekly", manifest_path=active, max_duration=30.0, observation="닭들이 지내는 모습을 담았어요.")
            self.assertEqual(again, manifest)
            self.assertEqual(json.loads(active.read_text()), manifest)
            # A failed retry must not activate a corrupted cached analysis bundle.
            active.write_text('{"version":"still-active"}\n')
            (release / "analysis.json").write_text('{"frames":[]}' )
            with self.assertRaisesRegex(ValueError, "prepared analysis"):
                weekly.prepare_video(source, week="2026-11-09", output_root=directory / "weekly", manifest_path=active, observation="닭들이 지내는 모습을 담았어요.")
            self.assertEqual(json.loads(active.read_text()), {"version": "still-active"})

    def test_zero_motion_has_finite_measurements(self):
        frame = np.zeros((240, 135), dtype=np.uint8)
        record, mask, flow = weekly.measure_motion(frame, frame)
        self.assertEqual(record["motionPercent"], 0)
        self.assertEqual(record["zones"], [0] * 9)
        self.assertTrue(np.isfinite(flow).all())
        self.assertFalse(mask.any())


if __name__ == "__main__":
    unittest.main()
