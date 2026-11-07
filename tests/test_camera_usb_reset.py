import importlib.util
import struct
import tempfile
import termios
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).parents[1] / "scripts" / "camera_usb_reset.py"
SPEC = importlib.util.spec_from_file_location("camera_usb_reset", SCRIPT)
camera_usb_reset = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(camera_usb_reset)


class CameraUsbResetTests(unittest.TestCase):
    def test_reads_identity_from_sysfs_parents(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sys_class = root / "sys" / "class" / "tty"
            usb = root / "devices" / "usb1" / "1-2.4"
            tty = usb / "1-2.4:1.0" / "ttyUSB0"
            tty.mkdir(parents=True)
            (usb / "idVendor").write_text("1A86\n", encoding="ascii")
            (usb / "idProduct").write_text("7523\n", encoding="ascii")
            class_tty = sys_class / "ttyUSB0"
            class_tty.mkdir(parents=True)
            (class_tty / "device").symlink_to(tty, target_is_directory=True)

            identity = camera_usb_reset.usb_identity(Path("/dev/ttyUSB0"), sys_class)

        self.assertEqual(identity, ("1a86", "7523", "1-2.4"))

    def test_pulse_releases_gpio0_and_resets_through_rts(self):
        calls = []

        def ioctl(fd, operation, payload):
            calls.append((fd, operation, struct.unpack("I", payload)[0]))

        closer = mock.Mock()
        sleeps = []
        port = camera_usb_reset.pulse_reset(
            Path("/dev/ttyUSB0"), "1a86", "7523", "1-2.4",
            identity_lookup=lambda _device: ("1a86", "7523", "1-2.4"),
            opener=lambda *_args: 9, closer=closer, ioctl=ioctl,
            sleep=sleeps.append,
        )

        self.assertEqual(port, "1-2.4")
        self.assertEqual(calls, [
            (9, termios.TIOCMBIC, termios.TIOCM_DTR | termios.TIOCM_RTS),
            (9, termios.TIOCMBIS, termios.TIOCM_RTS),
            (9, termios.TIOCMBIC, termios.TIOCM_DTR | termios.TIOCM_RTS),
        ])
        self.assertEqual(sleeps, [0.05, 0.15, 0.05])
        closer.assert_called_once_with(9)

    def test_refuses_wrong_adapter_before_opening_it(self):
        opener = mock.Mock()
        with self.assertRaises(camera_usb_reset.CameraUsbError):
            camera_usb_reset.pulse_reset(
                Path("/dev/ttyUSB0"), "1a86", "7523", "1-2.4",
                identity_lookup=lambda _device: ("10c4", "ea60", "1-2.4"),
                opener=opener,
            )
        opener.assert_not_called()

    def test_refuses_wrong_physical_usb_port(self):
        with self.assertRaises(camera_usb_reset.CameraUsbError):
            camera_usb_reset.pulse_reset(
                Path("/dev/ttyUSB0"), "1a86", "7523", "1-2.4",
                identity_lookup=lambda _device: ("1a86", "7523", "1-3"),
            )

    def test_watch_resets_once_per_reconnect(self):
        states = iter([False, True, True, False, True])
        reset = mock.Mock(return_value="1-2.4")
        with redirect_stdout(StringIO()):
            camera_usb_reset.watch(
                Path("/dev/ttyUSB0"), "1a86", "7523", "1-2.4", 0.5, 2,
                exists=lambda: next(states), reset=reset, sleep=lambda _seconds: None,
                max_cycles=5,
            )
        self.assertEqual(reset.call_count, 2)

    def test_rejects_too_fast_polling(self):
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            camera_usb_reset.parse_args(["--poll-seconds", "0"])


if __name__ == "__main__":
    unittest.main()
