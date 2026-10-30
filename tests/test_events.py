import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import cv2
import numpy as np

from events import EventStore


def make_jpeg(value=80):
    image = np.full((240, 320, 3), value, dtype=np.uint8)
    ok, encoded = cv2.imencode(".jpg", image)
    if not ok:
        raise RuntimeError("test JPEG encoding failed")
    return encoded.tobytes()


JPEG = make_jpeg()
PEAK_JPEG = make_jpeg(140)


class EventStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = EventStore(self.temp.name, retention_days=30, quota_bytes=1024 * 1024)

    def tearDown(self):
        self.temp.cleanup()

    def test_motion_event_lifecycle(self):
        started = datetime.now(timezone.utc) - timedelta(seconds=4)
        event_id = self.store.begin_motion(started, JPEG, JPEG, 0.12)
        self.store.update_peak(event_id, PEAK_JPEG, 0.25)
        self.store.finish_motion(event_id, datetime.now(timezone.utc))

        events = self.store.list_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["kind"], "motion")
        self.assertGreaterEqual(events[0]["duration_s"], 3.9)
        self.assertAlmostEqual(events[0]["peak_score"], 0.25)
        for role in ("pre", "trigger", "peak"):
            path = self.store.image_path(event_id, role)
            self.assertTrue(path.is_file())
            self.assertIsNotNone(cv2.imread(str(path)))

        self.assertTrue(self.store.mark_viewed(event_id))
        self.assertEqual(self.store.list_events(unseen=True), [])
        directory = self.store.image_path(event_id, "peak").parent
        self.assertTrue(self.store.delete_event(event_id))
        self.assertFalse(directory.exists())

    def test_settings_are_valid_and_persistent(self):
        settings = self.store.update_settings((0.1, 0.2, 0.7, 0.6), 31, 0.025)
        self.assertEqual(settings["roi_x"], 0.1)
        self.assertEqual(settings["pixel_threshold"], 31)
        reopened = EventStore(self.temp.name)
        self.assertEqual(reopened.settings()["area_ratio"], 0.025)

    def test_retention_removes_old_event_and_files(self):
        old = datetime.now(timezone.utc) - timedelta(days=31)
        event_id = self.store.begin_motion(old, JPEG, JPEG, 0.1)
        path = self.store.image_path(event_id, "peak")
        result = self.store.cleanup()
        self.assertEqual(result["expired"], 1)
        self.assertFalse(path.exists())
        self.assertEqual(self.store.list_events(), [])

    def test_state_events_have_no_image(self):
        event_id = self.store.record_state("camera_offline")
        self.assertIsNone(self.store.image_path(event_id, "peak"))
        self.assertEqual(self.store.list_events()[0]["kind"], "camera_offline")

    def test_pagination_and_batch_operations(self):
        ids = [self.store.record_state("camera_offline") for _ in range(4)]
        self.assertEqual(len(self.store.list_events(limit=2)), 2)
        self.assertEqual(len(self.store.list_events(limit=2, offset=2)), 2)

        viewed = self.store.mark_viewed_many([ids[0], ids[1], 999999])
        self.assertEqual(set(viewed["updated"]), {ids[0], ids[1]})
        self.assertEqual(viewed["missing"], [999999])

        deleted = self.store.delete_events([ids[0], ids[2], 999999])
        self.assertEqual(set(deleted["deleted"]), {ids[0], ids[2]})
        self.assertEqual(deleted["missing"], [999999])

    def test_thumbnail_is_available_and_removed_with_event(self):
        event_id = self.store.begin_motion(datetime.now(timezone.utc), JPEG, JPEG, 0.2)
        thumbnail = self.store.image_path(event_id, "thumb")
        self.assertTrue(thumbnail.is_file())
        event_directory = thumbnail.parent
        self.store.delete_events([event_id])
        self.assertFalse(event_directory.exists())


if __name__ == "__main__":
    unittest.main()
