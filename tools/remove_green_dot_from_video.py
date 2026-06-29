from pathlib import Path
import shutil
import subprocess

import cv2
import numpy as np


BASE_DIR = Path(__file__).resolve().parents[1]

INPUT_PATH = (
    BASE_DIR
    / "static"
    / "videos"
    / "highlight-before-green-dot-fix.mp4"
)

TEMP_PATH = (
    BASE_DIR
    / "static"
    / "videos"
    / "highlight-clean-temp.mp4"
)

OUTPUT_PATH = (
    BASE_DIR
    / "static"
    / "videos"
    / "highlight.mp4"
)


def main():
    if not INPUT_PATH.exists():
        raise FileNotFoundError(
            f"백업 영상이 없습니다: {INPUT_PATH}"
        )

    cap = cv2.VideoCapture(str(INPUT_PATH))

    if not cap.isOpened():
        raise RuntimeError("원본 영상을 열 수 없습니다.")

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    writer = cv2.VideoWriter(
        str(TEMP_PATH),
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        (width, height),
    )

    if not writer.isOpened():
        raise RuntimeError("임시 영상을 만들 수 없습니다.")

    frame_count = 0
    removed_count = 0

    # 초록점이 있는 영상 좌측 상단 영역만 검사
    roi_width = int(width * 0.23)
    roi_height = int(height * 0.14)

    while True:
        ok, frame = cap.read()

        if not ok:
            break

        roi = frame[:roi_height, :roi_width]
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

        # 밝은 초록색만 탐지
        lower_green = np.array([38, 70, 70])
        upper_green = np.array([95, 255, 255])

        mask_roi = cv2.inRange(
            hsv,
            lower_green,
            upper_green,
        )

        count, labels, stats, _ = (
            cv2.connectedComponentsWithStats(
                mask_roi,
                connectivity=8,
            )
        )

        clean_roi_mask = np.zeros_like(mask_roi)

        for label in range(1, count):
            x, y, w, h, area = stats[label]

            # 작은 초록 점만 제거하고 배경은 건드리지 않음
            if (
                2 <= area <= 500
                and w <= 35
                and h <= 35
            ):
                clean_roi_mask[labels == label] = 255

        if cv2.countNonZero(clean_roi_mask) > 0:
            clean_roi_mask = cv2.dilate(
                clean_roi_mask,
                np.ones((7, 7), dtype=np.uint8),
                iterations=1,
            )

            full_mask = np.zeros(
                (height, width),
                dtype=np.uint8,
            )

            full_mask[
                :roi_height,
                :roi_width
            ] = clean_roi_mask

            frame = cv2.inpaint(
                frame,
                full_mask,
                5,
                cv2.INPAINT_TELEA,
            )

            removed_count += 1

        writer.write(frame)
        frame_count += 1

    cap.release()
    writer.release()

    if frame_count == 0:
        raise RuntimeError("처리된 프레임이 없습니다.")

    ffmpeg = shutil.which("ffmpeg")

    if not ffmpeg:
        raise RuntimeError(
            "ffmpeg가 없습니다. brew install ffmpeg 실행 필요"
        )

    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(TEMP_PATH),
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "19",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            "-an",
            str(OUTPUT_PATH),
        ],
        check=True,
    )

    TEMP_PATH.unlink(missing_ok=True)

    print("초록점 제거 완료")
    print("전체 프레임:", frame_count)
    print("초록점 제거 프레임:", removed_count)
    print("출력:", OUTPUT_PATH)


if __name__ == "__main__":
    main()
