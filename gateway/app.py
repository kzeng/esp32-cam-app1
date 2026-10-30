"""Pet Watch gateway. Run one worker with multiple threads; see deployment docs."""
import hmac
import math
import os
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv
from flask import (Flask, Response, abort, jsonify, redirect, render_template, request,
                   send_file, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from camera import Camera, CameraError
from events import EventStore
from motion import MotionService
from watermark import watermark_jpeg

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
EVENT_PAGE_SIZE = 20
EVENT_BATCH_LIMIT = 100
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
data_dir = Path(os.environ.get("DATA_DIR", Path(__file__).with_name("data")))
retention_days = int(os.environ.get("EVENT_RETENTION_DAYS", "30"))
quota_mb = int(os.environ.get("EVENT_QUOTA_MB", "2048"))
background_fps = float(os.environ.get("MOTION_FPS", "2"))
quiet_seconds = float(os.environ.get("MOTION_QUIET_SECONDS", "15"))
if not 1 <= retention_days <= 3650 or not 100 <= quota_mb <= 102400:
    raise RuntimeError("Event retention must be 1-3650 days and quota 100-102400 MB.")
if not 0.2 <= background_fps <= fps or not 3 <= quiet_seconds <= 300:
    raise RuntimeError("MOTION_FPS or MOTION_QUIET_SECONDS is outside the supported range.")
event_store = EventStore(data_dir, retention_days, quota_mb * 1024 * 1024)
motion_enabled = os.environ.get("MOTION_ENABLED", "1") == "1"
motion_service = MotionService(camera, event_store, background_fps, quiet_seconds) if motion_enabled else None
if motion_service:
    motion_service.start()
attempts = {}
attempt_lock = threading.Lock()


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(24)
    return session["csrf"]


app.jinja_env.globals["csrf_token"] = csrf_token


@app.url_defaults
def version_static_assets(endpoint, values):
    if endpoint != "static" or "filename" not in values or "v" in values:
        return
    path = Path(app.static_folder) / values["filename"]
    try:
        values["v"] = path.stat().st_mtime_ns
    except OSError:
        pass


@app.before_request
def protect():
    if request.method == "POST":
        token = request.headers.get("X-CSRF-Token") or request.form.get("csrf", "")
        expected = session.get("csrf")
        if not expected or not token.isascii() or not hmac.compare_digest(expected, token):
            return jsonify(error="页面已过期，请刷新后重试。"), 403


@app.after_request
def headers(response):
    if request.endpoint == "static":
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    elif request.endpoint == "event_image":
        response.headers["Cache-Control"] = "private, max-age=300"
    else:
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
    return render_template("index.html", camera_name=os.environ.get("CAMERA_NAME", "仓鼠的小窝"),
                           event_summary=event_store.summary())


@app.get("/healthz")
def health():
    # Gateway liveness only, not an assertion that the physical camera is online.
    return jsonify(ok=True)


@app.get("/api/status")
@login_required
def status():
    result = camera.status()
    result["motion"] = motion_service.status() if motion_service else {"enabled": False}
    return jsonify(result)


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
                    sequence, jpeg, _ = camera.next_frame(sequence)
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
        jpeg, captured_at = camera.snapshot()
    except CameraError as error:
        return jsonify(error=str(error)), 503
    filename = captured_at.strftime("pet-%Y%m%d-%H%M%S.jpg")
    return Response(watermark_jpeg(jpeg, captured_at), content_type="image/jpeg", headers={
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


@app.route("/api/flash", methods=["GET", "POST"])
@login_required
def flash():
    state = None
    if request.method == "POST":
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or type(payload.get("on")) is not bool:
            return jsonify(error="请选择有效的补灯状态。"), 400
        state = payload["on"]
    try:
        return jsonify(on=camera.flash(state))
    except CameraError as error:
        return jsonify(error=str(error)), 503


@app.get("/events")
@login_required
def events_page():
    filter_name = request.args.get("filter", "all")
    local_midnight = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    options = {"all": {}, "today": {"since": local_midnight}, "week": {"days": 7},
               "unseen": {"unseen": True}}
    if filter_name not in options:
        filter_name = "all"
    try:
        page = min(max(int(request.args.get("page", "1")), 1), 10000)
    except ValueError:
        page = 1
    items = event_store.list_events(**options[filter_name], limit=EVENT_PAGE_SIZE + 1,
                                    offset=(page - 1) * EVENT_PAGE_SIZE)
    return render_template("events.html", events=items[:EVENT_PAGE_SIZE],
                           current_filter=filter_name, page=page,
                           has_next=len(items) > EVENT_PAGE_SIZE)


@app.get("/api/events/<int:event_id>/image/<role>")
@login_required
def event_image(event_id, role):
    path = event_store.image_path(event_id, role)
    if not path:
        abort(404)
    return send_file(path, mimetype="image/jpeg", conditional=True, max_age=300)


def json_action_requested():
    return request.is_json or "application/json" in request.headers.get("Accept", "")


@app.post("/api/events/<int:event_id>/viewed")
@login_required
def event_viewed(event_id):
    result = event_store.mark_viewed_many([event_id])
    if json_action_requested():
        return jsonify(ok=True, action="viewed", **result)
    return redirect(request.referrer if request.referrer and urlsplit(request.referrer).netloc == request.host else
                    url_for("events_page"))


@app.post("/api/events/<int:event_id>/delete")
@login_required
def event_delete(event_id):
    result = event_store.delete_events([event_id])
    if json_action_requested():
        return jsonify(ok=True, action="delete", **result)
    return redirect(url_for("events_page"))


@app.post("/api/events/batch")
@login_required
def event_batch():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or payload.get("action") not in {"viewed", "delete"}:
        return jsonify(error="请选择有效的批量操作。"), 400
    raw_ids = payload.get("ids")
    if (not isinstance(raw_ids, list) or not raw_ids or len(raw_ids) > EVENT_BATCH_LIMIT or
            any(type(event_id) is not int or event_id <= 0 for event_id in raw_ids)):
        return jsonify(error=f"请选择 1-{EVENT_BATCH_LIMIT} 个有效事件。"), 400
    ids = list(dict.fromkeys(raw_ids))
    if payload["action"] == "viewed":
        result = event_store.mark_viewed_many(ids)
    else:
        result = event_store.delete_events(ids)
    return jsonify(ok=True, action=payload["action"], **result)


@app.get("/motion")
@login_required
def motion_page():
    return render_template("motion.html", settings=event_store.settings(), enabled=motion_enabled)


@app.get("/api/motion-settings")
@login_required
def motion_settings_get():
    return jsonify(event_store.settings())


@app.post("/api/motion-settings")
@login_required
def motion_settings_update():
    payload = request.get_json(silent=True)
    try:
        roi = [float(payload[key]) for key in ("roi_x", "roi_y", "roi_w", "roi_h")]
        pixel_threshold = int(payload["pixel_threshold"])
        area_ratio = float(payload["area_ratio"])
    except (TypeError, KeyError, ValueError):
        return jsonify(error="检测区域或灵敏度参数无效。"), 400
    x, y, width, height = roi
    if (not all(math.isfinite(value) for value in (*roi, pixel_threshold, area_ratio)) or
            not 0 <= x < 1 or not 0 <= y < 1 or not 0.05 <= width <= 1 or
            not 0.05 <= height <= 1 or x + width > 1.000001 or y + height > 1.000001 or
            not 5 <= pixel_threshold <= 100 or not 0.002 <= area_ratio <= 0.5):
        return jsonify(error="检测区域超出画面，或阈值不在允许范围内。"), 400
    values = event_store.update_settings(roi, pixel_threshold, area_ratio)
    if motion_service:
        motion_service.reset_background()
    return jsonify(ok=True, **values)


if __name__ == "__main__":
    # Local development only; Ubuntu deployment uses Gunicorn.
    app.run(host="127.0.0.1", port=8080, threaded=True, debug=False)
