from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import cv2
import numpy as np


BASE_DIR = Path(__file__).resolve().parents[1]
INPUT_PATH = BASE_DIR / "static" / "videos" / "highlight.mp4"
TEMP_PATH = BASE_DIR / "static" / "videos" / "density_heatmap_temp.mp4"
OUTPUT_PATH = BASE_DIR / "static" / "videos" / "density_heatmap.mp4"


def main() -> None:
    if not INPUT_PATH.exists():
        raise FileNotFoundError(
            f"원본 영상이 없습니다: {INPUT_PATH}"
        )

    capture = cv2.VideoCapture(str(INPUT_PATH))

    if not capture.isOpened():
        raise RuntimeError(
            "static/videos/highlight.mp4를 열 수 없습니다."
        )

    fps = capture.get(cv2.CAP_PROP_FPS) or 25.0
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))

    if width <= 0 or height <= 0:
        raise RuntimeError("영상 해상도를 읽지 못했습니다.")

    TEMP_PATH.parent.mkdir(parents=True, exist_ok=True)

    writer = cv2.VideoWriter(
        str(TEMP_PATH),
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        (width, height),
    )

    if not writer.isOpened():
        raise RuntimeError("임시 히트맵 영상을 만들 수 없습니다.")

    subtractor = cv2.createBackgroundSubtractorMOG2(
        history=max(120, int(fps * 4)),
        varThreshold=38,
        detectShadows=True,
    )

    accumulated = np.zeros(
        (height, width),
        dtype=np.float32,
    )

    open_kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE,
        (5, 5),
    )

    close_kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE,
        (15, 15),
    )

    processed_frames = 0

    while True:
        ok, frame = capture.read()

        if not ok:
            break

        foreground = subtractor.apply(frame)

        # 그림자와 약한 노이즈 제거
        foreground[foreground < 220] = 0

        foreground = cv2.morphologyEx(
            foreground,
            cv2.MORPH_OPEN,
            open_kernel,
        )

        foreground = cv2.morphologyEx(
            foreground,
            cv2.MORPH_CLOSE,
            close_kernel,
        )

        contours, _ = cv2.findContours(
            foreground,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )

        clean_mask = np.zeros_like(foreground)

        minimum_area = max(180, int(width * height * 0.00012))
        maximum_area = int(width * height * 0.07)

        for contour in contours:
            area = cv2.contourArea(contour)

            if minimum_area <= area <= maximum_area:
                cv2.drawContours(
                    clean_mask,
                    [contour],
                    -1,
                    255,
                    thickness=-1,
                )

        clean_mask = cv2.GaussianBlur(
            clean_mask,
            (45, 45),
            0,
        )

        # 과거 위치는 빠르게 사라지고 최근 움직임 중심으로 표시
        accumulated *= 0.84
        accumulated += (
            clean_mask.astype(np.float32) * 0.34
        )

        maximum = float(accumulated.max())

        if maximum > 0:
            normalized = np.clip(
                accumulated / maximum * 255.0,
                0,
                255,
            ).astype(np.uint8)
        else:
            normalized = np.zeros_like(clean_mask)

        alpha = normalized.copy()

        # 움직임이 약한 배경은 투명하게 유지
        alpha[alpha < 92] = 0

        heatmap = cv2.applyColorMap(
            normalized,
            cv2.COLORMAP_TURBO,
        )

        alpha_float = (
            alpha.astype(np.float32) / 255.0 * 0.67
        )[:, :, None]

        output = (
            frame.astype(np.float32)
            * (1.0 - alpha_float)
            + heatmap.astype(np.float32)
            * alpha_float
        )

        output = np.clip(
            output,
            0,
            255,
        ).astype(np.uint8)

        # 상단 분석 상태 배지
        badge_width = min(width - 36, 360)

        overlay = output.copy()

        cv2.rectangle(
            overlay,
            (18, 18),
            (18 + badge_width, 64),
            (5, 20, 15),
            thickness=-1,
        )

        cv2.addWeighted(
            overlay,
            0.76,
            output,
            0.24,
            0,
            output,
        )

        cv2.circle(
            output,
            (37, 41),
            5,
            (92, 235, 166),
            thickness=-1,
        )

        cv2.putText(
            output,
            "FRAME-SYNCED MOTION HEATMAP",
            (52, 47),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )

        # 우측 하단 색상 범례
        legend_x1 = max(20, width - 235)
        legend_y1 = max(20, height - 48)
        legend_x2 = width - 20
        legend_y2 = height - 20

        cv2.rectangle(
            output,
            (legend_x1, legend_y1),
            (legend_x2, legend_y2),
            (9, 22, 17),
            thickness=-1,
        )

        gradient_width = max(1, legend_x2 - legend_x1 - 82)
        gradient = np.linspace(
            0,
            255,
            gradient_width,
            dtype=np.uint8,
        ).reshape(1, -1)

        gradient = np.repeat(gradient, 7, axis=0)
        gradient = cv2.applyColorMap(
            gradient,
            cv2.COLORMAP_TURBO,
        )

        gx1 = legend_x1 + 10
        gy1 = legend_y1 + 10
        gx2 = gx1 + gradient_width
        gy2 = gy1 + 7

        output[gy1:gy2, gx1:gx2] = gradient

        cv2.putText(
            output,
            "LOW",
            (gx1, legend_y2 - 4),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.28,
            (230, 235, 232),
            1,
            cv2.LINE_AA,
        )

        cv2.putText(
            output,
            "HIGH",
            (legend_x2 - 38, legend_y2 - 4),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.28,
            (230, 235, 232),
            1,
            cv2.LINE_AA,
        )

        writer.write(output)
        processed_frames += 1

    capture.release()
    writer.release()

    if processed_frames == 0:
        raise RuntimeError("처리된 영상 프레임이 없습니다.")

    ffmpeg = shutil.which("ffmpeg")

    if not ffmpeg:
        raise RuntimeError(
            "ffmpeg가 없습니다. 터미널에서 "
            "'brew install ffmpeg'를 먼저 실행하세요."
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
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    TEMP_PATH.unlink(missing_ok=True)

    print("히트맵 영상 생성 완료")
    print("출력 파일:", OUTPUT_PATH)
    print("처리 프레임:", processed_frames)


if __name__ == "__main__":
    main()
