import unittest
from datetime import datetime, timedelta, timezone

import cv2
import numpy as np

from watermark import timestamp_text, watermark_jpeg


class TimestampWatermarkTests(unittest.TestCase):
    def setUp(self):
        self.image = np.full((240, 320, 3), 100, dtype=np.uint8)
        ok, encoded = cv2.imencode(".jpg", self.image)
        if not ok:
            raise RuntimeError("test JPEG encoding failed")
        self.jpeg = encoded.tobytes()
        self.captured_at = datetime(2026, 10, 30, 5, 2, 31, tzinfo=timezone.utc)

    def test_formats_in_camera_local_timezone(self):
        self.assertEqual(timestamp_text(self.captured_at), "2026-10-30 13:02:31")
        offset = timezone(timedelta(hours=8))
        self.assertEqual(timestamp_text(self.captured_at.astimezone(offset)), "2026-10-30 13:02:31")

    def test_rejects_naive_datetime(self):
        with self.assertRaises(ValueError):
            timestamp_text(datetime(2026, 10, 30, 13, 2, 31))

    def test_watermark_preserves_dimensions_and_adds_contrast(self):
        watermarked = watermark_jpeg(self.jpeg, self.captured_at)
        decoded = cv2.imdecode(np.frombuffer(watermarked, dtype=np.uint8), cv2.IMREAD_COLOR)
        self.assertIsNotNone(decoded)
        self.assertEqual(decoded.shape, self.image.shape)
        top_band = decoded[:60]
        self.assertLess(int(top_band.min()), 40)
        self.assertGreater(int(top_band.max()), 220)


if __name__ == "__main__":
    unittest.main()
