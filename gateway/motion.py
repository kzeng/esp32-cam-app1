"""Background motion analysis and event lifecycle."""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from datetime import datetime, timezone

import cv2
import numpy as np

from camera import CameraError


log = logging.getLogger(__name__)


class MotionAnalyzer:
    def __init__(self):
        self.background = None
        self.lock = threading.Lock()

    def reset(self):
        with self.lock:
            self.background = None

    def analyze(self, jpeg, settings):
        encoded = np.frombuffer(jpeg, dtype=np.uint8)
        image = cv2.imdecode(encoded, cv2.IMREAD_GRAYSCALE)
        if image is None:
            raise ValueError("JPEG decode failed")
        frame = cv2.resize(image, (160, 120), interpolation=cv2.INTER_AREA)
        frame = cv2.GaussianBlur(frame, (5, 5), 0)
        with self.lock:
            return self._analyze_frame(frame, settings)

    def _analyze_frame(self, frame, settings):
        if self.background is None:
            self.background = frame.astype(np.float32)
            return 0.0, False

        x = min(max(settings["roi_x"], 0.0), 0.99)
        y = min(max(settings["roi_y"], 0.0), 0.99)
        w = min(max(settings["roi_w"], 0.01), 1.0 - x)
        h = min(max(settings["roi_h"], 0.01), 1.0 - y)
        x1, y1 = int(x * 160), int(y * 120)
        x2, y2 = max(x1 + 1, int((x + w) * 160)), max(y1 + 1, int((y + h) * 120))
        background = cv2.convertScaleAbs(self.background)
        delta = cv2.absdiff(frame, background)
        roi_delta = delta[y1:y2, x1:x2]

        # A nearly uniform whole-frame change is usually a light switching on/off.
        global_ratio = float(np.count_nonzero(delta >= settings["pixel_threshold"]) / delta.size)
        uniform_light_change = global_ratio > 0.7 and float(delta.std()) < 24.0
        if uniform_light_change:
            cv2.accumulateWeighted(frame, self.background, 0.35)
            return 0.0, False

        mask = cv2.threshold(roi_delta, settings["pixel_threshold"], 255, cv2.THRESH_BINARY)[1]
        kernel = np.ones((3, 3), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.dilate(mask, kernel, iterations=1)
        changed = float(np.count_nonzero(mask) / mask.size)
        moving = changed >= settings["area_ratio"]
        cv2.accumulateWeighted(frame, self.background, 0.008 if moving else 0.035)
        return changed, moving


class MotionService:
    def __init__(self, camera, store, background_fps=2.0, quiet_seconds=15.0):
        self.camera = camera
        self.store = store
        self.background_fps = background_fps
        self.quiet_seconds = quiet_seconds
        self.stop_event = threading.Event()
        self.thread = None
        self.analyzer = MotionAnalyzer()
        self.history = deque(maxlen=max(3, int(background_fps * 3)))
        self.hits = deque(maxlen=3)
        self.event_id = None
        self.event_peak = 0.0
        self.last_motion_monotonic = None
        self.offline_since = None
        self.offline_recorded = False
        self.lock = threading.Lock()
        self.last_score = 0.0
        self.last_error = None

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.camera.enable_monitoring(self.background_fps)
        self.thread = threading.Thread(target=self._run, name="motion-detector", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.camera.disable_monitoring()

    def reset_background(self):
        self.analyzer.reset()
        self.hits.clear()
        self.history.clear()

    def status(self):
        with self.lock:
            return {
                "enabled": True,
                "active_event": self.event_id,
                "score": round(self.last_score, 4),
                "error": self.last_error,
            }

    def _record_camera_ok(self):
        if self.offline_recorded:
            self.store.record_state("camera_recovered")
        self.offline_since = None
        self.offline_recorded = False

    def _record_camera_failure(self):
        now = time.monotonic()
        if self.offline_since is None:
            self.offline_since = now
        elif not self.offline_recorded and now - self.offline_since >= 30:
            self.store.record_state("camera_offline")
            self.offline_recorded = True

    def _begin_event(self, jpeg, captured_at, score):
        pre_jpeg, pre_captured_at = self.history[0] if self.history else (jpeg, captured_at)
        self.event_id = self.store.begin_motion(
            captured_at, pre_jpeg, jpeg, score,
            pre_captured_at=pre_captured_at, trigger_captured_at=captured_at,
        )
        self.event_peak = score
        self.last_motion_monotonic = time.monotonic()

    def _finish_event(self):
        if self.event_id is not None:
            self.store.finish_motion(self.event_id, datetime.now(timezone.utc))
            self.store.cleanup()
        self.event_id = None
        self.event_peak = 0.0
        self.last_motion_monotonic = None

    def _run(self):
        sequence = -1
        while not self.stop_event.is_set():
            try:
                sequence, jpeg, captured_at = self.camera.next_frame(sequence, timeout=10)
                self._record_camera_ok()
                settings = self.store.settings()
                score, moving = self.analyzer.analyze(jpeg, settings)
                self.hits.append(moving)
                confirmed = len(self.hits) == 3 and sum(self.hits) >= 2
                with self.lock:
                    self.last_score = score
                    self.last_error = None
                if confirmed:
                    if self.event_id is None:
                        self._begin_event(jpeg, captured_at, score)
                    else:
                        self.last_motion_monotonic = time.monotonic()
                        if score > self.event_peak:
                            self.event_peak = score
                            self.store.update_peak(self.event_id, jpeg, score, captured_at)
                if (self.event_id is not None and self.last_motion_monotonic is not None and
                        time.monotonic() - self.last_motion_monotonic >= self.quiet_seconds):
                    self._finish_event()
                self.history.append((jpeg, captured_at))
            except CameraError as error:
                self._record_camera_failure()
                if (self.event_id is not None and self.last_motion_monotonic is not None and
                        time.monotonic() - self.last_motion_monotonic >= self.quiet_seconds):
                    self._finish_event()
                with self.lock:
                    self.last_error = str(error)
                time.sleep(1)
            except Exception as error:  # Keep monitoring alive; details go to the service log.
                log.exception("Motion detector failed")
                with self.lock:
                    self.last_error = str(error)
                time.sleep(2)
        self._finish_event()
