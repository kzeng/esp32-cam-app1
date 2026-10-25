import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from events import EventStore


JPEG = b"\xff\xd8test-image\xff\xd9"


class EventStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = EventStore(self.temp.name, retention_days=30, quota_bytes=1024 * 1024)

    def tearDown(self):
        self.temp.cleanup()

    def test_motion_event_lifecycle(self):
        started = datetime.now(timezone.utc) - timedelta(seconds=4)
        event_id = self.store.begin_motion(started, JPEG, JPEG, 0.12)
        self.store.update_peak(event_id, JPEG + b"peak", 0.25)
        self.store.finish_motion(event_id, datetime.now(timezone.utc))

        events = self.store.list_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["kind"], "motion")
        self.assertGreaterEqual(events[0]["duration_s"], 3.9)
        self.assertAlmostEqual(events[0]["peak_score"], 0.25)
        for role in ("pre", "trigger", "peak"):
            self.assertTrue(self.store.image_path(event_id, role).is_file())

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


if __name__ == "__main__":
    unittest.main()
