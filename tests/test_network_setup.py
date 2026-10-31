"""Host behavior tests; no ESP32 toolchain, hardware or Python dependencies.

Run: python -m unittest discover -s tests -p test_network_setup.py -v
Each scenario is a fresh process so production file-static state is never reset
by test-only hooks. Restart tests transfer only the fake Preferences contents.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class NetworkSetupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("g++")
        if compiler is None:
            raise RuntimeError("g++ is required for firmware behavior tests")
        cls.temp = tempfile.TemporaryDirectory(prefix="network-setup-tests-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.binary = Path(cls.temp.name) / "network_setup"
        result = subprocess.run([
            compiler, "-std=c++17", "-Wall", "-Wextra", "-Wpedantic", "-Werror",
            "-Wno-class-memaccess",  # Production clears its POD-like config with memset.
            "-O0", "-g", "-I", str(ROOT / "tests/firmware_fakes"),
            "-I", str(ROOT / "firmware/include"),
            str(ROOT / "firmware/src/network_setup.cpp"),
            str(ROOT / "tests/network_setup_harness.cpp"), "-o", str(cls.binary),
        ], capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise AssertionError(f"Host compilation failed:\n{result.stdout}{result.stderr}")

    def run_scenario(self, scenario, snapshot=None):
        args = [str(self.binary), scenario]
        if snapshot is not None:
            args.append(str(snapshot))
        result = subprocess.run(args, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f"PASS {scenario}", result.stdout)

    def test_behavior_scenarios(self):
        for scenario in (
            "validation", "first", "reconnect", "http-validation", "security", "scan",
            "trial-failure", "timeout", "cancel", "serial-cancel", "forget",
            "forget-failure", "open-failure", "password-failure",
        ):
            with self.subTest(scenario=scenario):
                self.run_scenario(scenario)

    def test_success_survives_process_restart(self):
        for scenario in ("first-save", "save"):
            with self.subTest(scenario=scenario):
                snapshot = Path(self.temp.name) / f"{scenario}.nvs"
                self.run_scenario(scenario, snapshot)
                self.run_scenario("restore", snapshot)

    def test_setup_password_change_survives_restart(self):
        snapshot = Path(self.temp.name) / "ap-password.nvs"
        self.run_scenario("ap-password", snapshot)
        self.run_scenario("ap-password-restore", snapshot)

    def test_storage_failures_preserve_old_config_on_restart(self):
        for scenario in ("write-failure", "commit-failure", "verify-failure"):
            with self.subTest(scenario=scenario):
                snapshot = Path(self.temp.name) / f"{scenario}.nvs"
                self.run_scenario(scenario, snapshot)
                self.run_scenario("restore-old", snapshot)


if __name__ == "__main__":
    unittest.main()
