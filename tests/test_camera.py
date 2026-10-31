import socket
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from camera import Camera


class CaptureComplete(Exception):
    pass


class CameraMdnsTests(unittest.TestCase):
    def test_capture_recovers_after_hostname_address_changes(self):
        """Exercise real HTTP pools and DNS lookup, without requiring multicast."""
        jpeg = b"\xff\xd8test\xff\xd9"
        requests_seen = []

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self):
                requests_seen.append((self.server.server_address[0], self.path,
                                      self.headers.get("X-Camera-Key")))
                # The old address stops serving valid frames after the first one.
                failed = len(requests_seen) == 2
                # Consume a complete invalid JPEG before failing, so Requests
                # returns the socket to its pool. Recovery must clear that pool.
                body = b"invalid-jpeg" if failed else jpeg
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        old = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.addCleanup(old.server_close)
        new = ThreadingHTTPServer(("127.0.0.2", old.server_port), Handler)
        self.addCleanup(new.server_close)
        for server in (old, new):
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(thread.join, 2)
            self.addCleanup(server.shutdown)

        camera = Camera(f"http://pet-camera.local:{old.server_port}", "test-key", 6)
        camera.viewers = 1
        address = "127.0.0.1"
        lookups = []
        getaddrinfo = socket.getaddrinfo
        cycles = 0

        def resolve(host, port, *args, **kwargs):
            self.assertEqual(host, "pet-camera.local")
            lookups.append(address)
            return getaddrinfo(address, port, *args, **kwargs)

        def next_cycle(delay):
            nonlocal cycles, address
            cycles += 1
            if cycles == 1:
                self.assertEqual(camera.sequence, 1)
                address = "127.0.0.2"
            elif cycles == 2:
                self.assertIsNone(camera.frame)
                self.assertIsNotNone(camera.last_error)
                self.assertEqual(delay, 1.5)
            else:
                raise CaptureComplete

        with patch("socket.getaddrinfo", side_effect=resolve), \
                patch("camera.time.sleep", side_effect=next_cycle), \
                patch.dict("os.environ", {"HTTP_PROXY": "http://127.0.0.1:1",
                                          "NO_PROXY": ""}):
            with self.assertRaises(CaptureComplete):
                camera._run()

        self.assertEqual(lookups, ["127.0.0.1", "127.0.0.2"])
        self.assertEqual([item[0] for item in requests_seen],
                         ["127.0.0.1", "127.0.0.1", "127.0.0.2"])
        self.assertTrue(all(item[1:] == ("/capture", "test-key") for item in requests_seen))
        self.assertEqual(camera.sequence, 2)
        self.assertEqual(camera.frame, jpeg)
        self.assertIsNone(camera.last_error)


if __name__ == "__main__":
    unittest.main()