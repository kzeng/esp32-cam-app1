import unittest

import cv2
import numpy as np

from motion import MotionAnalyzer


SETTINGS = {
    "roi_x": 0.0, "roi_y": 0.0, "roi_w": 1.0, "roi_h": 1.0,
    "pixel_threshold": 25.0, "area_ratio": 0.015,
}


def jpeg(image):
    ok, encoded = cv2.imencode(".jpg", image)
    if not ok:
        raise RuntimeError("test JPEG encoding failed")
    return encoded.tobytes()


class MotionAnalyzerTests(unittest.TestCase):
    def test_detects_local_movement(self):
        analyzer = MotionAnalyzer()
        base = np.zeros((240, 320), dtype=np.uint8)
        moved = base.copy()
        moved[70:150, 90:190] = 255
        self.assertEqual(analyzer.analyze(jpeg(base), SETTINGS), (0.0, False))
        score, moving = analyzer.analyze(jpeg(moved), SETTINGS)
        self.assertTrue(moving)
        self.assertGreater(score, SETTINGS["area_ratio"])

    def test_ignores_uniform_light_change(self):
        analyzer = MotionAnalyzer()
        dark = np.full((240, 320), 20, dtype=np.uint8)
        light = np.full((240, 320), 180, dtype=np.uint8)
        analyzer.analyze(jpeg(dark), SETTINGS)
        score, moving = analyzer.analyze(jpeg(light), SETTINGS)
        self.assertFalse(moving)
        self.assertEqual(score, 0.0)

    def test_roi_excludes_motion_outside_area(self):
        analyzer = MotionAnalyzer()
        settings = {**SETTINGS, "roi_x": 0.5, "roi_w": 0.5}
        base = np.zeros((240, 320), dtype=np.uint8)
        moved = base.copy()
        moved[40:170, 10:100] = 255
        analyzer.analyze(jpeg(base), settings)
        score, moving = analyzer.analyze(jpeg(moved), settings)
        self.assertFalse(moving)
        self.assertEqual(score, 0.0)


if __name__ == "__main__":
    unittest.main()
