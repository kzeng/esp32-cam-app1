import os
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import cv2
import numpy as np

TEST_DATA = tempfile.TemporaryDirectory()
os.environ.update({
    "CAMERA_URL": "http://127.0.0.1:9",
    "CAMERA_KEY": "a" * 64,
    "APP_PASSWORD": "test-password-long",
    "SECRET_KEY": "s" * 64,
    "MOTION_ENABLED": "0",
    "DATA_DIR": TEST_DATA.name,
})

import app as application  # noqa: E402


def make_jpeg(value=90):
    image = np.full((240, 320, 3), value, dtype=np.uint8)
    ok, encoded = cv2.imencode(".jpg", image)
    if not ok:
        raise RuntimeError("test JPEG encoding failed")
    return encoded.tobytes()


JPEG = make_jpeg()


class AppRouteTests(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        TEST_DATA.cleanup()

    def setUp(self):
        application.app.config.update(TESTING=True)
        self.client = application.app.test_client()
        with self.client.session_transaction() as browser_session:
            browser_session["authenticated"] = True
            browser_session["csrf"] = "test-csrf"

    def test_private_pages_render(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/events").status_code, 200)
        self.assertEqual(self.client.get("/motion").status_code, 200)

    def test_motion_settings_require_csrf_and_validate_bounds(self):
        payload = {
            "roi_x": 0.1, "roi_y": 0.2, "roi_w": 0.7, "roi_h": 0.6,
            "pixel_threshold": 30, "area_ratio": 0.02,
        }
        self.assertEqual(self.client.post("/api/motion-settings", json=payload).status_code, 403)
        response = self.client.post("/api/motion-settings", json=payload,
                                    headers={"X-CSRF-Token": "test-csrf"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["roi_x"], 0.1)
        payload["roi_w"] = 0.95
        self.assertEqual(self.client.post("/api/motion-settings", json=payload,
                                         headers={"X-CSRF-Token": "test-csrf"}).status_code, 400)

    def test_event_image_is_authenticated_and_deletion_removes_it(self):
        event_id = application.event_store.begin_motion(
            datetime.now(timezone.utc), JPEG, JPEG, 0.2
        )
        image = self.client.get(f"/api/events/{event_id}/image/peak")
        self.assertEqual(image.status_code, 200)
        self.assertEqual(image.mimetype, "image/jpeg")
        image.close()
        deleted = self.client.post(f"/api/events/{event_id}/delete",
                                   headers={"X-CSRF-Token": "test-csrf"})
        self.assertEqual(deleted.status_code, 302)
        self.assertEqual(self.client.get(f"/api/events/{event_id}/image/peak").status_code, 404)

        anonymous = application.app.test_client()
        self.assertEqual(anonymous.get("/api/motion-settings").status_code, 401)

    def test_snapshot_download_has_timestamp_watermark(self):
        captured_at = datetime(2026, 10, 30, 5, 2, 31, tzinfo=timezone.utc)
        with patch.object(application.camera, "snapshot", return_value=(JPEG, captured_at)):
            response = self.client.get("/api/snapshot")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "image/jpeg")
        self.assertIn("pet-20261030-050231.jpg", response.headers["Content-Disposition"])
        decoded = cv2.imdecode(np.frombuffer(response.data, dtype=np.uint8), cv2.IMREAD_COLOR)
        self.assertIsNotNone(decoded)
        self.assertEqual(decoded.shape[:2], (240, 320))

    def test_cache_policy_and_versioned_static_assets(self):
        page = self.client.get("/events")
        self.assertEqual(page.headers["Cache-Control"], "no-store")
        self.assertIn(b"style.css?v=", page.data)
        static = self.client.get("/static/style.css")
        self.assertIn("immutable", static.headers["Cache-Control"])
        static.close()

        event_id = application.event_store.begin_motion(
            datetime.now(timezone.utc), JPEG, JPEG, 0.2
        )
        image = self.client.get(f"/api/events/{event_id}/image/thumb")
        self.assertEqual(image.status_code, 200)
        self.assertIn("private", image.headers["Cache-Control"])
        image.close()

    def test_batch_actions_are_bounded_and_idempotent(self):
        first = application.event_store.begin_motion(datetime.now(timezone.utc), JPEG, JPEG, 0.2)
        second = application.event_store.begin_motion(datetime.now(timezone.utc), JPEG, JPEG, 0.2)
        headers = {"X-CSRF-Token": "test-csrf"}
        viewed = self.client.post("/api/events/batch", json={"action": "viewed", "ids": [first, second]},
                                  headers=headers)
        self.assertEqual(viewed.status_code, 200)
        self.assertEqual(set(viewed.get_json()["updated"]), {first, second})

        deleted = self.client.post("/api/events/batch", json={"action": "delete", "ids": [first, second]},
                                   headers=headers)
        self.assertEqual(deleted.status_code, 200)
        retry = self.client.post("/api/events/batch", json={"action": "delete", "ids": [first, second]},
                                 headers=headers)
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(set(retry.get_json()["missing"]), {first, second})

        invalid = self.client.post("/api/events/batch", json={"action": "delete", "ids": list(range(101))},
                                   headers=headers)
        self.assertEqual(invalid.status_code, 400)


if __name__ == "__main__":
    unittest.main()
