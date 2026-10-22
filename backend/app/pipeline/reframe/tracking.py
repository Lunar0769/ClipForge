"""Speaker tracking for the 9:16 "Speaker Track" layout.

Samples the clip a few times per second, finds faces (MediaPipe, CPU), splits the clip into camera
shots, picks the speaker to follow in each shot, smooths the camera path (deadzone + easing, hard
cuts at shot changes) and turns it into per-frame crop positions that ffmpeg applies via `sendcmd`.
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from pydantic import BaseModel

from app.pipeline.errors import StageCancelled

logger = logging.getLogger(__name__)

MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/face_detector/"
             "blaze_face_full_range/float16/latest/blaze_face_full_range.tflite")
MODEL_NAME = "blaze_face_full_range.tflite"

SAMPLE_FPS = 5.0         # face detection rate
DETECT_WIDTH = 960       # frames are downscaled to this width for detection
MIN_SCORE = 0.5          # ignore weaker detections (small false positives)
CUT_THRESHOLD = 0.55     # colour-histogram correlation below this = new camera shot
DEADZONE = 0.05          # ignore speaker movement smaller than this (fraction of frame width)
EASING = 0.3             # per-sample fraction of the remaining distance the camera moves
MIN_FACE_COVERAGE = 0.2  # below this share of samples with a face, the layout falls back to fit_blur
OUTPUT_FPS = 30


@dataclass(frozen=True)
class Face:
    cx: float     # centre x, 0-1 of frame width
    cy: float     # centre y, 0-1 of frame height
    w: float      # width, 0-1 of frame width
    score: float


@dataclass
class Sample:
    t: float                  # seconds from clip start
    faces: list[Face]
    hist: np.ndarray | None = field(default=None, repr=False)


class TrackPlan(BaseModel):
    """Everything the renderer needs: crop size and the crop's x position over time (pixels)."""

    src_w: int
    src_h: int
    crop_w: int
    crop_h: int
    y: int
    keyframes: list[tuple[float, int]]  # (seconds from clip start, crop x)
    face_coverage: float

    @property
    def usable(self) -> bool:
        return self.face_coverage >= MIN_FACE_COVERAGE and bool(self.keyframes)


Detector = Callable[[np.ndarray], list[Face]]  # RGB frame -> faces


# ── detection ─────────────────────────────────────────────────────────────────

def ensure_model(models_dir: Path) -> Path:
    path = models_dir / "mediapipe" / MODEL_NAME
    if not path.exists():
        import httpx

        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".part")
        tmp.write_bytes(httpx.get(MODEL_URL, follow_redirects=True, timeout=120).raise_for_status().content)
        os.replace(tmp, path)
    return path


def mediapipe_detector(model_path: Path) -> tuple[Detector, Callable[[], None]]:
    """A MediaPipe face detector (IMAGE mode) plus its close function."""
    os.environ.setdefault("GLOG_minloglevel", "2")
    import mediapipe as mp
    from mediapipe.tasks import python as mpt
    from mediapipe.tasks.python import vision

    options = vision.FaceDetectorOptions(
        base_options=mpt.BaseOptions(model_asset_path=str(model_path)),
        running_mode=vision.RunningMode.IMAGE,
        min_detection_confidence=MIN_SCORE,
    )
    detector = vision.FaceDetector.create_from_options(options)

    def detect(rgb: np.ndarray) -> list[Face]:
        h, w = rgb.shape[:2]
        result = detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb)))
        faces = []
        for d in result.detections:
            b = d.bounding_box
            faces.append(Face(cx=(b.origin_x + b.width / 2) / w, cy=(b.origin_y + b.height / 2) / h,
                              w=b.width / w, score=float(d.categories[0].score)))
        return faces

    return detect, detector.close


def sample_clip(src: Path, start_s: float, end_s: float, detect: Detector, *,
                sample_fps: float = SAMPLE_FPS, detect_width: int = DETECT_WIDTH,
                cancel: threading.Event | None = None) -> tuple[list[Sample], int, int]:
    """Decode the clip once, detecting faces on every n-th frame. Returns (samples, width, height)."""
    import cv2

    cap = cv2.VideoCapture(str(src))
    if not cap.isOpened():
        raise RuntimeError(f"OpenCV couldn't open {src.name}")
    try:
        src_w, src_h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        step = max(1, round(fps / sample_fps))
        cap.set(cv2.CAP_PROP_POS_MSEC, start_s * 1000.0)
        samples: list[Sample] = []
        index = 0
        while True:
            if cancel is not None and cancel.is_set():
                raise StageCancelled()
            if not cap.grab():
                break
            t = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
            if t > end_s:
                break
            if index % step == 0 and t >= start_s - 0.05:
                ok, frame = cap.retrieve()
                if ok:
                    small = cv2.resize(frame, (detect_width, max(1, round(detect_width * src_h / src_w))))
                    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
                    hist = cv2.calcHist([hsv], [0, 1], None, [16, 16], [0, 180, 0, 256])
                    cv2.normalize(hist, hist)
                    faces = detect(cv2.cvtColor(small, cv2.COLOR_BGR2RGB))
                    samples.append(Sample(t=max(0.0, t - start_s), faces=faces, hist=hist))
            index += 1
        return samples, src_w, src_h
    finally:
        cap.release()


# ── planning (pure) ───────────────────────────────────────────────────────────

def shot_starts(samples: list[Sample], threshold: float = CUT_THRESHOLD) -> list[int]:
    """Indices of samples that begin a new camera shot (always includes 0)."""
    import cv2

    starts = [0] if samples else []
    for i in range(1, len(samples)):
        a, b = samples[i - 1].hist, samples[i].hist
        if a is not None and b is not None and cv2.compareHist(a, b, cv2.HISTCMP_CORREL) < threshold:
            starts.append(i)
    return starts


def choose_targets(samples: list[Sample], starts: list[int]) -> list[float | None]:
    """Per sample, the x of the person to follow: stick with the current speaker within a shot."""
    targets: list[float | None] = [None] * len(samples)
    bounds = starts + [len(samples)]
    for a, b in zip(bounds, bounds[1:]):
        current: float | None = None
        for i in range(a, b):
            faces = samples[i].faces
            if not faces:
                continue
            biggest = max(f.w for f in faces)
            candidates = [f for f in faces if f.w >= 0.5 * biggest]  # ignore background/audience faces
            if current is None:
                pick = max(candidates, key=lambda f: f.w * f.score)
            else:
                pick = min(candidates, key=lambda f: abs(f.cx - current))
                if abs(pick.cx - current) > 0.25:  # someone else is now the main face: switch to them
                    pick = max(candidates, key=lambda f: f.w * f.score)
            current = pick.cx
            targets[i] = current
    return targets


def smooth_path(targets: list[float | None], starts: list[int], *, deadzone: float = DEADZONE,
                easing: float = EASING) -> list[float]:
    """Camera centre per sample: holds still inside the deadzone, eases toward the speaker, cuts at shots."""
    path: list[float] = [0.5] * len(targets)
    bounds = starts + [len(targets)]
    for a, b in zip(bounds, bounds[1:]):
        known = [t for t in targets[a:b] if t is not None]
        if not known:
            continue  # no face in this shot: keep the centre
        filled: list[float] = []
        last = known[0]
        for t in targets[a:b]:
            last = t if t is not None else last
            filled.append(last)
        position = filled[0]  # hard cut: start each shot already on the speaker
        moving = False
        for offset, target in enumerate(filled):
            gap = target - position
            # Hysteresis: small head movements inside the deadzone don't move the camera, but once
            # the speaker leaves it the camera re-centres fully instead of stopping at the edge.
            if abs(gap) > deadzone:
                moving = True
            if moving:
                position += easing * gap
                if abs(target - position) < 0.01:
                    moving = False
            path[a + offset] = position
    return path


def crop_keyframes(times: list[float], path: list[float], starts: list[int], *, src_w: int, crop_w: int,
                   duration_s: float, fps: int = OUTPUT_FPS) -> list[tuple[float, int]]:
    """Per output frame crop x (pixels); linear between samples, stepping at shot cuts."""
    if not times:
        return []
    max_x = src_w - crop_w

    def to_px(centre: float) -> int:
        x = int(round(centre * src_w - crop_w / 2))
        return max(0, min(max_x, x - x % 2))

    cut_times = {times[i] for i in starts}
    frames: list[tuple[float, int]] = []
    j = 0
    for k in range(int(duration_s * fps) + 1):
        t = k / fps
        while j + 1 < len(times) and times[j + 1] <= t:
            j += 1
        if j + 1 < len(times) and times[j + 1] not in cut_times and times[j + 1] > times[j]:
            frac = (t - times[j]) / (times[j + 1] - times[j])
            centre = path[j] + (path[j + 1] - path[j]) * min(1.0, max(0.0, frac))
        else:
            centre = path[j]
        x = to_px(centre)
        if not frames or frames[-1][1] != x:
            frames.append((round(t, 3), x))
    return frames


def plan_track(samples: list[Sample], src_w: int, src_h: int, duration_s: float) -> TrackPlan:
    crop_h = src_h - src_h % 2
    crop_w = min(src_w, int(crop_h * 9 / 16))
    crop_w -= crop_w % 2
    starts = shot_starts(samples)
    targets = choose_targets(samples, starts)
    path = smooth_path(targets, starts)
    coverage = sum(1 for t in targets if t is not None) / len(samples) if samples else 0.0
    keyframes = crop_keyframes([s.t for s in samples], path, starts, src_w=src_w, crop_w=crop_w,
                               duration_s=duration_s)
    return TrackPlan(src_w=src_w, src_h=src_h, crop_w=crop_w, crop_h=crop_h, y=(src_h - crop_h) // 2,
                     keyframes=keyframes, face_coverage=round(coverage, 3))


def compute_track(src: Path, start_s: float, end_s: float, *, models_dir: Path,
                  cancel: threading.Event | None = None) -> TrackPlan:
    detect, close = mediapipe_detector(ensure_model(models_dir))
    try:
        samples, src_w, src_h = sample_clip(src, start_s, end_s, detect, cancel=cancel)
    finally:
        close()
    return plan_track(samples, src_w, src_h, end_s - start_s)


def write_sendcmd(plan: TrackPlan, path: Path) -> None:
    path.write_text("".join(f"{t:.3f} crop x {x};\n" for t, x in plan.keyframes), encoding="utf-8")
