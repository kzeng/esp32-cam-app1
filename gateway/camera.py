"""One capture loop shared by viewers and the background motion detector."""
import threading
import time

import requests


class CameraError(Exception):
    pass


class Camera:
    MAX_VIEWERS = 6
    MAX_JPEG = 2 * 1024 * 1024
    FRESH_SECONDS = 4

    def __init__(self, url, key, fps):
        self.url = url.rstrip("/")
        self.headers = {"X-Camera-Key": key}
        self.fps = fps
        self.condition = threading.Condition()
        self.io_lock = threading.Lock()
        self.viewers = 0
        self.monitor_fps = 0.0
        self.frame = None
        self.sequence = 0
        self.updated = None
        self.last_error = None
        self.resolution = None  # Unknown until explicitly applied.
        self.worker = None

    def subscribe(self):
        with self.condition:
            if self.viewers >= self.MAX_VIEWERS:
                raise CameraError("同时观看的人数过多，请关闭其他监控页面。")
            self.viewers += 1
            if self.worker is None:
                self.worker = threading.Thread(target=self._run, name="camera-capture", daemon=True)
                self.worker.start()
            self.condition.notify_all()

    def unsubscribe(self):
        with self.condition:
            self.viewers = max(0, self.viewers - 1)
            self.condition.notify_all()

    def enable_monitoring(self, fps):
        """Keep capture active for motion detection without counting a viewer."""
        if not 0.2 <= fps <= self.fps:
            raise ValueError("Background capture FPS is outside the supported range.")
        with self.condition:
            self.monitor_fps = fps
            if self.worker is None:
                self.worker = threading.Thread(target=self._run, name="camera-capture", daemon=True)
                self.worker.start()
            self.condition.notify_all()

    def disable_monitoring(self):
        with self.condition:
            self.monitor_fps = 0.0
            self.condition.notify_all()

    @staticmethod
    def _message(error):
        if isinstance(error, requests.Timeout):
            return "摄像头响应超时，请检查供电和 Wi-Fi。"
        if isinstance(error, requests.HTTPError):
            code = error.response.status_code
            if code == 401:
                return "摄像头密钥不匹配，请检查电脑与固件配置。"
            return f"摄像头返回错误（{code}）。"
        if isinstance(error, requests.RequestException):
            return "无法连接摄像头，请检查地址、供电和 Wi-Fi。"
        return str(error)

    def _run(self):
        # Never use HTTP(S)_PROXY from the host for local camera traffic.
        with requests.Session() as client:
            client.trust_env = False
            client.headers.update(self.headers)
            while True:
                with self.condition:
                    self.condition.wait_for(lambda: self.viewers > 0 or self.monitor_fps > 0)
                    target_fps = self.fps if self.viewers > 0 else self.monitor_fps
                started = time.monotonic()
                failed = False
                try:
                    with self.io_lock:
                        with client.get(self.url + "/capture", timeout=(2, 4),
                                        allow_redirects=False, stream=True) as response:
                            response.raise_for_status()
                            if response.status_code != 200 or not response.headers.get(
                                    "Content-Type", "").startswith("image/jpeg"):
                                raise CameraError("摄像头没有返回 JPEG 图片，请确认固件版本。")
                            data = bytearray()
                            deadline = time.monotonic() + 6
                            for chunk in response.iter_content(16384):
                                data.extend(chunk)
                                if len(data) > self.MAX_JPEG or time.monotonic() > deadline:
                                    raise CameraError("摄像头图片过大或传输过慢。")
                            if not data.startswith(b"\xff\xd8") or not data.endswith(b"\xff\xd9"):
                                raise CameraError("收到不完整图片，正在重新连接。")
                        with self.condition:
                            self.frame = bytes(data)
                            self.sequence += 1
                            self.updated = time.monotonic()
                            self.last_error = None
                            self.condition.notify_all()
                except (requests.RequestException, CameraError) as error:
                    failed = True
                    with self.condition:
                        self.last_error = self._message(error)
                        # Never keep presenting a pre-disconnection frame as live.
                        self.frame = None
                        self.updated = None
                        self.condition.notify_all()
                delay = 1.5 if failed else max(0, 1 / target_fps - (time.monotonic() - started))
                time.sleep(delay)

    def next_frame(self, after, timeout=10):
        deadline = time.monotonic() + timeout
        with self.condition:
            while True:
                if (self.frame and self.sequence > after and self.updated is not None
                        and time.monotonic() - self.updated <= self.FRESH_SECONDS):
                    return self.sequence, self.frame
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise CameraError(self.last_error or "尚未收到画面，请检查摄像头。")
                self.condition.wait(remaining)

    def snapshot(self):
        self.subscribe()
        try:
            with self.condition:
                after = self.sequence  # Require a newly received image.
            return self.next_frame(after)[1]
        finally:
            self.unsubscribe()

    def set_resolution(self, resolution):
        if resolution not in {"low", "standard", "high"}:
            raise ValueError("请选择有效的画质。")
        try:
            with self.io_lock:
                with requests.Session() as client:
                    client.trust_env = False
                    with client.post(self.url + "/control", params={"resolution": resolution},
                                     headers=self.headers, timeout=(2, 6),
                                     allow_redirects=False) as response:
                        response.raise_for_status()
                        if response.status_code != 200 or response.json().get("ok") is not True:
                            raise CameraError("摄像头未确认画质设置。")
                with self.condition:
                    self.resolution = resolution
                    self.frame = None
                    self.updated = None
                    self.condition.notify_all()
        except (requests.RequestException, ValueError) as error:
            raise CameraError(self._message(error)) from error

    def flash(self, state=None):
        if state is not None and not isinstance(state, bool):
            raise ValueError("补灯状态无效。")
        try:
            with requests.Session() as client:
                client.trust_env = False
                with client.request("GET" if state is None else "POST", self.url + "/flash",
                                    params=None if state is None else {"state": "on" if state else "off"},
                                    headers=self.headers, timeout=(2, 5), allow_redirects=False) as response:
                    response.raise_for_status()
                    if response.status_code != 200:
                        raise CameraError("摄像头未确认补灯状态。")
                    result = response.json()
                    if not isinstance(result, dict) or not isinstance(result.get("on"), bool):
                        raise CameraError("摄像头补灯响应无效。")
                    return result["on"]
        except (requests.RequestException, ValueError) as error:
            raise CameraError(self._message(error)) from error

    def status(self):
        with self.condition:
            age = None if self.updated is None else time.monotonic() - self.updated
            return {
                "state": ("idle" if self.viewers == 0 and self.monitor_fps == 0 else
                          "live" if age is not None and age <= self.FRESH_SECONDS else
                          "offline" if self.last_error else "connecting"),
                "frame_age_s": round(age, 1) if age is not None else None,
                "sequence": self.sequence,
                "viewers": self.viewers,
                "monitoring": self.monitor_fps > 0,
                "resolution": self.resolution,
                "error": self.last_error,
            }
