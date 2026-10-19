"""Pet Watch gateway. Run one worker with multiple threads; see deployment docs."""
import hmac
import os
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv
from flask import Flask, Response, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from camera import Camera, CameraError

load_dotenv(Path(__file__).with_name(".env"))


def setting(name, minimum):
    value = os.environ.get(name, "")
    if len(value) < minimum or value.startswith("CHANGE_"):
        raise RuntimeError(f"Configure {name} in gateway/.env before starting.")
    return value


app = Flask(__name__)
app.config.update(
    SECRET_KEY=setting("SECRET_KEY", 32),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Strict",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "0") == "1",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
    MAX_CONTENT_LENGTH=4096,
)
password_hash = generate_password_hash(setting("APP_PASSWORD", 12))
camera_key = setting("CAMERA_KEY", 32)
if len(camera_key) > 128 or not camera_key.isascii() or not camera_key.isalnum():
    raise RuntimeError("CAMERA_KEY must be 32-128 ASCII letters/digits (random hex recommended).")
camera_url = os.environ.get("CAMERA_URL", "")
parsed_url = urlsplit(camera_url)
if (parsed_url.scheme != "http" or not parsed_url.hostname or parsed_url.username or
        parsed_url.password or parsed_url.query or parsed_url.fragment or parsed_url.path not in {"", "/"}):
    raise RuntimeError("CAMERA_URL must be an http:// camera address without a path or credentials.")
fps = float(os.environ.get("TARGET_FPS", "6"))
if not 1 <= fps <= 10:
    raise RuntimeError("TARGET_FPS must be between 1 and 10.")
camera = Camera(camera_url, camera_key, fps)
attempts = {}
attempt_lock = threading.Lock()


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(24)
    return session["csrf"]


app.jinja_env.globals["csrf_token"] = csrf_token


@app.before_request
def protect():
    if request.method == "POST":
        token = request.headers.get("X-CSRF-Token") or request.form.get("csrf", "")
        expected = session.get("csrf")
        if not expected or not token.isascii() or not hmac.compare_digest(expected, token):
            return jsonify(error="页面已过期，请刷新后重试。"), 403


@app.after_request
def headers(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' blob:; style-src 'self'; "
        "script-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
    )
    return response


def login_required(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        if not session.get("authenticated"):
            if request.path.startswith("/api/"):
                return jsonify(error="登录已过期，请重新登录。"), 401
            return redirect(url_for("login"))
        return function(*args, **kwargs)
    return wrapped


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    status_code = 200
    if request.method == "POST":
        address = request.remote_addr or "unknown"
        now = time.monotonic()
        with attempt_lock:
            for key in list(attempts):
                if now - attempts[key][0] > 60:
                    del attempts[key]
            first, count = attempts.get(address, (now, 0))
            # Bound memory; do not clear rate limits when too many sources appear.
            limited = count >= 5 or (address not in attempts and len(attempts) >= 1024)
            if not limited:
                attempts[address] = (first, count + 1)
        if limited:
            error, status_code = "尝试次数较多，请一分钟后重试。", 429
        elif check_password_hash(password_hash, request.form.get("password", "")):
            with attempt_lock:
                attempts.pop(address, None)
            session.clear()
            session["authenticated"] = True
            session.permanent = True
            csrf_token()
            return redirect(url_for("index"))
        else:
            error, status_code = "访问密码不正确。", 401
    return render_template("login.html", error=error), status_code


@app.post("/logout")
@login_required
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.get("/")
@login_required
def index():
    return render_template("index.html", camera_name=os.environ.get("CAMERA_NAME", "宠物的小窝"))


@app.get("/healthz")
def health():
    # Gateway liveness only, not an assertion that the physical camera is online.
    return jsonify(ok=True)


@app.get("/api/status")
@login_required
def status():
    return jsonify(camera.status())


@app.get("/api/stream")
@login_required
def stream():
    try:
        camera.subscribe()
    except CameraError as error:
        return jsonify(error=str(error)), 503

    def frames():
        sequence = -1
        try:
            while True:
                try:
                    sequence, jpeg = camera.next_frame(sequence)
                except CameraError:
                    break  # Browser status polling initiates reconnection.
                yield (b"--petframe\r\nContent-Type: image/jpeg\r\nContent-Length: " +
                       str(len(jpeg)).encode("ascii") + b"\r\n\r\n" + jpeg + b"\r\n")
        finally:
            camera.unsubscribe()

    response = Response(frames(), content_type="multipart/x-mixed-replace; boundary=petframe")
    response.headers["X-Accel-Buffering"] = "no"
    return response


@app.get("/api/snapshot")
@login_required
def snapshot():
    try:
        jpeg = camera.snapshot()
    except CameraError as error:
        return jsonify(error=str(error)), 503
    filename = datetime.now(timezone.utc).strftime("pet-%Y%m%d-%H%M%S.jpg")
    return Response(jpeg, content_type="image/jpeg", headers={
        "Content-Disposition": f'attachment; filename="{filename}"',
    })


@app.post("/api/quality")
@login_required
def quality():
    payload = request.get_json(silent=True)
    if (not isinstance(payload, dict) or not isinstance(payload.get("resolution"), str)
            or payload["resolution"] not in {"low", "standard", "high"}):
        return jsonify(error="请选择有效的画质。"), 400
    try:
        camera.set_resolution(payload["resolution"])
    except CameraError as error:
        return jsonify(error=str(error)), 503
    return jsonify(ok=True, resolution=payload["resolution"])


if __name__ == "__main__":
    # Local development only; Ubuntu deployment uses Gunicorn.
    app.run(host="127.0.0.1", port=8080, threaded=True, debug=False)
