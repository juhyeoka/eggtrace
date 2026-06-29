from pathlib import Path

import cv2
import numpy as np

BASE_DIR = Path(__file__).resolve().parents[1]
INPUT_PATH = BASE_DIR / "static" / "videos" / "highlight.mp4"
OUTPUT_PATH = BASE_DIR / "static" / "videos" / "density_heatmap.mp4"


def main():
    if not INPUT_PATH.exists():
        raise FileNotFoundError(f"원본 영상 없음: {INPUT_PATH}")

    cap = cv2.VideoCapture(str(INPUT_PATH))

    if not cap.isOpened():
        raise RuntimeError("highlight.mp4를 열 수 없습니다.")

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    temp_path = OUTPUT_PATH.with_name("density_heatmap_temp.mp4")

    writer = cv2.VideoWriter(
        str(temp_path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        (width, height),
    )

    if not writer.isOpened():
        raise RuntimeError("히트맵 출력 영상을 만들 수 없습니다.")

    subtractor = cv2.createBackgroundSubtractorMOG2(
        history=max(100, int(fps * 4)),
        varThreshold=45,
        detectShadows=True,
    )

    accumulated = np.zeros((height, width), dtype=np.float32)

    open_kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE,
        (5, 5),
    )

    close_kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE,
        (13, 13),
    )

    count = 0

    while True:
        ok, frame = cap.read()

        if not ok:
            break

        foreground = subtractor.apply(frame)
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

        clean = np.zeros_like(foreground)

        for contour in contours:
            area = cv2.contourArea(contour)

            if 250 <= area <= width * height * 0.04:
                cv2.drawContours(
                    clean,
                    [contour],
                    -1,
                    255,
                    -1,
                )

        clean = cv2.GaussianBlur(clean, (35, 35), 0)

        accumulated *= 0.86
        accumulated += clean.astype(np.float32) * 0.28

        maximum = float(accumulated.max())

        if maximum > 0:
            normalized = np.clip(
                accumulated / maximum * 255,
                0,
                255,
            ).astype(np.uint8)
        else:
            normalized = np.zeros_like(clean)

        alpha = normalized.copy()
        alpha[alpha < 95] = 0

        heatmap = cv2.applyColorMap(
            normalized,
            cv2.COLORMAP_TURBO,
        )

        alpha_float = (
            alpha.astype(np.float32) / 255.0 * 0.55
        )[:, :, None]

        output = (
            frame.astype(np.float32) * (1.0 - alpha_float)
            + heatmap.astype(np.float32) * alpha_float
        )

        output = np.clip(output, 0, 255).astype(np.uint8)

        writer.write(output)
        count += 1

    cap.release()
    writer.release()

    if count == 0 or not temp_path.exists():
        raise RuntimeError("히트맵 영상 생성 실패")

    temp_path.replace(OUTPUT_PATH)

    print("생성 완료:", OUTPUT_PATH)
    print("처리 프레임:", count)


if __name__ == "__main__":
    main()
