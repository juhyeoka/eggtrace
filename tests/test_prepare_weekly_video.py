"""Regression checks for weekly publication safety and motion measurements."""

import importlib.util
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import cv2
import numpy as np


SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "prepare_weekly_video.py"
SPEC = importlib.util.spec_from_file_location("prepare_weekly_video", SCRIPT)
weekly = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = weekly
SPEC.loader.exec_module(weekly)


class TestSubjects:
    """Deterministic foreground for encoding tests, never a production fallback."""
    metadata = {"enabled": True, "model": "test-segmenter", "modelSha256": "a" * 64,
                "className": "bird", "classId": 14, "maskMethod": "instance-segmentation", "confidence": 0.4}

    def detect(self, frame):
        return weekly.DetectedSubjects(np.full(frame.shape[:2], 255, np.uint8), 1)


class WeeklyVideoTests(unittest.TestCase):
    def test_default_framing_keeps_every_source_edge(self):
        for width, height in ((1080, 1920), (1920, 1080), (2560, 1080), (96, 160), (641, 481)):
            info = weekly.VideoInfo(width, height, 30, 24)
            plan = weekly.build_framing(info)
            self.assertEqual(plan.mode, "source")
            self.assertEqual((plan.x, plan.y, plan.crop_width, plan.crop_height), (0, 0, width, height))
            frame = np.random.default_rng(14).integers(0, 255, (height, width, 3), dtype=np.uint8)
            np.testing.assert_array_equal(plan.apply(frame), frame)

    def test_command_line_without_framing_keeps_source_for_folder_updates(self):
        with patch.object(sys, "argv", ["prepare_weekly_video.py", "--input", "weekly.mp4", "--json"]), \
                patch.object(weekly, "prepare_video", return_value={"version": "test"}) as prepare, \
                redirect_stdout(StringIO()):
            self.assertEqual(weekly.main(), 0)
        self.assertEqual(prepare.call_args.kwargs["framing"], "source")

    def test_landscape_framing_is_inside_source_and_has_exact_aspect(self):
        portrait = weekly.build_framing(weekly.VideoInfo(1080, 1920, 67, 30), framing="landscape")
        self.assertEqual((portrait.x, portrait.y, portrait.crop_width, portrait.crop_height), (12, 902, 1056, 594))
        self.assertEqual((portrait.width, portrait.height), (960, 540))
        for width, height in ((1080, 1920), (1920, 1080), (2560, 1080), (96, 160), (641, 481)):
            info = weekly.VideoInfo(width, height, 30, 24)
            for anchor in (0, 0.68, 1):
                plan = weekly.build_framing(info, framing="landscape", crop_y=anchor)
                self.assertGreaterEqual(plan.x, 0); self.assertGreaterEqual(plan.y, 0)
                self.assertLessEqual(plan.x + plan.crop_width, width)
                self.assertLessEqual(plan.y + plan.crop_height, height)
                self.assertEqual(plan.crop_width * 9, plan.crop_height * 16)
                self.assertEqual(plan.width * 9, plan.height * 16)
                self.assertTrue(all(value % 2 == 0 for value in (plan.x, plan.y, plan.crop_width, plan.crop_height, plan.width, plan.height)))
        native = weekly.build_framing(weekly.VideoInfo(1920, 1080, 30, 24), framing="landscape")
        self.assertEqual((native.x, native.y, native.crop_width, native.crop_height), (0, 0, 1920, 1080))
        source = weekly.build_framing(weekly.VideoInfo(1080, 1920, 30, 24), framing="source")
        self.assertEqual((source.x, source.y, source.crop_width, source.crop_height), (0, 0, 1080, 1920))
        self.assertEqual((source.width, source.height), (540, 960))
        for invalid in (-0.1, 1.1, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                weekly.build_framing(weekly.VideoInfo(1080, 1920, 30, 24), crop_y=invalid)

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

    def test_automatic_excerpt_scores_only_the_visible_crop(self):
        info = weekly.VideoInfo(96, 160, 6, 24)
        plan = weekly.build_framing(info, framing="landscape")
        full = np.full((160, 96, 3), 240, np.uint8)
        full[plan.y:plan.y + plan.crop_height, plan.x:plan.x + plan.crop_width] = 70
        capture = SimpleNamespace(set=lambda *args: None, read=lambda: (True, full.copy()), release=lambda: None)
        seen = []
        class RecordingSubjects(TestSubjects):
            def detect(self, frame):
                seen.append(frame.copy())
                return super().detect(frame)
        with patch.object(weekly.cv2, "VideoCapture", return_value=capture):
            weekly.choose_clip_start(Path('source.mp4'), info, 2, RecordingSubjects(), plan)
        self.assertEqual(len(seen), 3)
        self.assertTrue(all(frame.shape == (54, 96, 3) and np.all(frame == 70) for frame in seen))

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
                    weekly.prepare_video(source, week="2026-11-09", output_root=directory / "weekly", manifest_path=manifest, detector=TestSubjects())
            self.assertEqual(manifest.read_bytes(), original)
            self.assertEqual(list((directory / "weekly").iterdir()), [])
            self.assertEqual(list(directory.glob(".weekly-staging-*")), [])

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg tools are required")
    def test_default_full_source_release_has_one_timeline_and_is_idempotent(self):
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
            manifest = weekly.prepare_video(source, week="2026-11-09", output_root=directory / "weekly", manifest_path=active, observation="닭들이 지내는 모습을 담았어요.", detector=TestSubjects())
            self.assertEqual((manifest["width"], manifest["height"]), (96, 160))
            self.assertEqual(manifest["editing"]["framing"], "source")
            self.assertEqual(manifest["editing"]["outputAspectRatio"], "3:5")
            self.assertEqual(manifest["editing"]["crop"], {"x": 0, "y": 0, "width": 96, "height": 160, "sourceWidth": 96, "sourceHeight": 160})
            self.assertAlmostEqual(manifest["duration"], 2, places=2)
            self.assertNotIn(source.name, json.dumps(manifest))
            release = directory / "weekly" / manifest["version"]
            analysis = json.loads((release / "analysis.json").read_text())
            self.assertFalse(analysis["frames"][0]["measured"])
            self.assertTrue(analysis["detection"]["enabled"])
            measured = [frame for frame in analysis["frames"] if frame["measured"]]
            self.assertEqual(analysis["summary"]["measuredCount"], len(measured))
            self.assertAlmostEqual(analysis["summary"]["averageMotionPercent"], round(float(np.mean([frame["motionPercent"] for frame in measured])), 2))
            for mode in weekly.MODES:
                info = weekly.probe_video(release / f"{mode}.mp4")
                self.assertEqual((info.width, info.height), (96, 160))
                self.assertAlmostEqual(info.duration, manifest["duration"], places=2)
            with patch.object(weekly, "encode_original", side_effect=AssertionError("immutable release should be reused")):
                again = weekly.prepare_video(source, week="2026-11-09", output_root=directory / "weekly", manifest_path=active, max_duration=30.0, observation="닭들이 지내는 모습을 담았어요.", detector=TestSubjects())
            self.assertEqual(again, manifest)
            self.assertEqual(json.loads(active.read_text()), manifest)
            # A different mask model/options or reviewed start cannot reuse the
            # previous immutable release, even when the source is identical.
            changed = TestSubjects()
            changed.metadata = {**changed.metadata, "confidence": 0.5, "modelSha256": "b" * 64}
            for options in [{"detector": changed}, {"detector": TestSubjects(), "start_time": 0.5},
                            {"detector": TestSubjects(), "framing": "landscape"}, {"detector": TestSubjects(), "crop_y": 0.2}]:
                with patch.object(weekly, "encode_original", side_effect=RuntimeError("new release required")):
                    with self.assertRaisesRegex(RuntimeError, "new release required"):
                        weekly.prepare_video(source, week="2026-11-09", output_root=directory / "weekly", manifest_path=active, observation="닭들이 지내는 모습을 담았어요.", **options)
                self.assertEqual(json.loads(active.read_text()), manifest)
            # A failed retry must not activate a corrupted cached analysis bundle.
            active.write_text('{"version":"still-active"}\n')
            (release / "analysis.json").write_text('{"frames":[]}' )
            with self.assertRaisesRegex(ValueError, "prepared analysis"):
                weekly.prepare_video(source, week="2026-11-09", output_root=directory / "weekly", manifest_path=active, observation="닭들이 지내는 모습을 담았어요.", detector=TestSubjects())
            self.assertEqual(json.loads(active.read_text()), {"version": "still-active"})

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg tools are required")
    def test_real_crop_keeps_square_shape_and_source_option_preserves_portrait(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source = directory / "portrait.mp4"
            writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*"mp4v"), 24, (320, 480))
            self.assertTrue(writer.isOpened())
            for _ in range(24):
                frame = np.full((480, 320, 3), 70, np.uint8)
                frame[300:348, 100:148] = 245
                writer.write(frame)
            writer.release()
            info = weekly.probe_video(source)
            for mode, expected in (("landscape", (320, 180)), ("source", (320, 480))):
                plan = weekly.build_framing(info, framing=mode)
                output = directory / f"{mode}.mp4"
                weekly.encode_original(source, output, plan.width, plan.height, 0, 1, plan)
                result = weekly.probe_video(output)
                self.assertEqual((result.width, result.height), expected)
                capture = cv2.VideoCapture(str(output)); ok, frame = capture.read(); capture.release()
                self.assertTrue(ok)
                white_y, white_x = np.where(np.all(frame > 215, axis=2))
                self.assertGreater(white_x.size, 2000)
                # A real crop preserves a square. Stretching the complete
                # portrait source into a landscape frame would flatten it.
                self.assertLessEqual(abs((white_x.max() - white_x.min()) - (white_y.max() - white_y.min())), 1)
                if mode == "landscape":
                    self.assertEqual(white_y.min(), 300 - plan.y)
                    self.assertEqual(white_x.min(), 100 - plan.x)

    def test_zero_motion_has_finite_measurements(self):
        frame = np.zeros((240, 135), dtype=np.uint8)
        record, mask, flow = weekly.measure_motion(frame, frame)
        self.assertEqual(record["motionPercent"], 0)
        self.assertEqual(record["zones"], [0] * 9)
        self.assertTrue(np.isfinite(flow).all())
        self.assertFalse(mask.any())

    def test_background_motion_is_excluded_and_bird_motion_normalized_to_mask(self):
        random = np.random.default_rng(72)
        before = cv2.GaussianBlur(random.integers(20, 150, (200, 300), dtype=np.uint8), (5, 5), 0)
        subject = np.zeros_like(before); subject[120:180, 200:270] = 255
        after = before.copy(); after[20:80, 20:100] = 250
        record, mask, flow = weekly.measure_motion(before, after, subject, subject)
        self.assertLess(record["motionPercent"], 0.5)
        self.assertFalse(mask[subject == 0].any())
        self.assertFalse(flow[subject == 0].any())
        after[130:170, 210:260] = 250
        record, mask, _ = weekly.measure_motion(before, after, subject, subject)
        self.assertGreater(record["motionPercent"], 25)
        self.assertLessEqual(record["motionPercent"], 100)
        self.assertFalse(mask[subject == 0].any())

    def test_missing_detection_never_falls_back_to_whole_scene(self):
        before = np.zeros((200, 300), dtype=np.uint8)
        after = np.full_like(before, 200)
        empty = np.zeros_like(before)
        record, mask, flow = weekly.measure_motion(before, after, empty, empty)
        self.assertFalse(record["measured"])
        self.assertEqual(record["motionPercent"], 0)
        self.assertFalse(mask.any()); self.assertFalse(flow.any())

    def test_only_border_detection_outside_alignment_is_unmeasured(self):
        random = np.random.default_rng(81)
        before = cv2.GaussianBlur(random.integers(20, 180, (200, 300), dtype=np.uint8), (5, 5), 0)
        after = cv2.warpAffine(before, np.float32([[1, 0, 0], [0, 1, 8]]), (300, 200), borderMode=cv2.BORDER_REPLICATE)
        subject = np.zeros_like(before); subject[:2, 100:200] = 255
        record, mask, flow = weekly.measure_motion(before, after, subject, subject)
        self.assertTrue(record["cameraCompensated"])
        self.assertFalse(record["measured"])
        self.assertEqual(record["motionPercent"], 0)
        self.assertFalse(mask.any()); self.assertFalse(flow.any())

    def test_segmenter_filters_non_birds_and_has_no_other_class_fallback(self):
        bird = np.array([[5, 5], [15, 5], [15, 15], [5, 15]], np.float32)
        person = bird + 20
        detector = weekly.ChickenMaskDetector.__new__(weekly.ChickenMaskDetector)
        detector.confidence = 0.4
        result = SimpleNamespace(masks=SimpleNamespace(xy=[bird, person]),
            boxes=SimpleNamespace(cls=np.array([14, 0]), conf=np.array([0.7, 0.9])))
        detector.model = SimpleNamespace(predict=lambda *args, **kwargs: [result])
        found = detector.detect(np.zeros((50, 50, 3), np.uint8))
        self.assertEqual(found.count, 1)
        self.assertTrue(found.mask[10, 10]); self.assertFalse(found.mask[30, 30])
        result.boxes.cls = np.array([0, 0])
        found = detector.detect(np.zeros((50, 50, 3), np.uint8))
        self.assertEqual(found.count, 0); self.assertFalse(found.mask.any())

    def test_missing_or_changed_weights_fail_before_replacing_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); source = root / "source.mp4"; source.write_bytes(b"source")
            active = root / "active.json"; active.write_text('{"version":"previous"}')
            with self.assertRaisesRegex(RuntimeError, "weights are missing"):
                weekly.prepare_video(source, model_path=root / "missing.pt", manifest_path=active)
            weights = root / "changed.pt"; weights.write_bytes(b"not-the-official-checkpoint")
            with self.assertRaisesRegex(RuntimeError, "checksum"):
                weekly.prepare_video(source, model_path=weights, manifest_path=active)
            self.assertEqual(json.loads(active.read_text()), {"version":"previous"})


if __name__ == "__main__":
    unittest.main()
