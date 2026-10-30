"""SQLite event index and private JPEG storage for Pet Watch."""
from __future__ import annotations

import os
import shutil
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import cv2
import numpy as np

from watermark import watermark_jpeg


IMAGE_ROLES = {"pre", "trigger", "peak"}


def utc_now():
    return datetime.now(timezone.utc)


def iso(value):
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds")


class EventStore:
    def __init__(self, root, retention_days=30, quota_bytes=2 * 1024**3):
        self.root = Path(root).resolve()
        self.image_root = self.root / "events"
        self.trash_root = self.root / ".trash"
        self.db_path = self.root / "events.sqlite3"
        self.retention_days = retention_days
        self.quota_bytes = quota_bytes
        self.lock = threading.RLock()
        self.root.mkdir(parents=True, exist_ok=True)
        self.image_root.mkdir(parents=True, exist_ok=True)
        self.trash_root.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize(self):
        with self.lock, self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL CHECK(kind IN ('motion','camera_offline','camera_recovered')),
                    started_at TEXT NOT NULL,
                    ended_at TEXT NOT NULL,
                    duration_s REAL NOT NULL DEFAULT 0,
                    peak_score REAL NOT NULL DEFAULT 0,
                    viewed INTEGER NOT NULL DEFAULT 0 CHECK(viewed IN (0,1)),
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS events_started_idx ON events(started_at DESC);
                CREATE INDEX IF NOT EXISTS events_viewed_idx ON events(viewed, started_at DESC);
                CREATE TABLE IF NOT EXISTS images (
                    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
                    role TEXT NOT NULL CHECK(role IN ('pre','trigger','peak')),
                    relative_path TEXT NOT NULL,
                    bytes INTEGER NOT NULL,
                    PRIMARY KEY(event_id, role)
                );
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
            """)
            defaults = {
                "roi_x": "0", "roi_y": "0", "roi_w": "1", "roi_h": "1",
                "pixel_threshold": "25", "area_ratio": "0.015",
            }
            db.executemany("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", defaults.items())

    def settings(self):
        with self.lock, self._connect() as db:
            values = {row["key"]: float(row["value"]) for row in db.execute("SELECT key,value FROM settings")}
        return values

    def update_settings(self, roi, pixel_threshold, area_ratio):
        values = {
            "roi_x": roi[0], "roi_y": roi[1], "roi_w": roi[2], "roi_h": roi[3],
            "pixel_threshold": pixel_threshold, "area_ratio": area_ratio,
        }
        with self.lock, self._connect() as db:
            db.executemany(
                "INSERT INTO settings(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                ((key, str(value)) for key, value in values.items()),
            )
        return self.settings()

    def _event_directory(self, event_id, started_at):
        local = started_at.astimezone()
        return self.image_root / local.strftime("%Y/%m/%d") / f"event-{event_id:08d}"

    @staticmethod
    def _atomic_write(path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        with open(temporary, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)

    @staticmethod
    def _thumbnail(jpeg, width=360):
        image = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None or image.shape[1] <= width:
            return jpeg
        height = max(1, round(image.shape[0] * width / image.shape[1]))
        image = cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)
        ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 76])
        return encoded.tobytes() if ok else jpeg

    def _write_thumbnail(self, directory, jpeg):
        self._atomic_write(directory / "thumb.jpg", self._thumbnail(jpeg))

    def begin_motion(self, started_at, pre_jpeg, trigger_jpeg, score,
                     pre_captured_at=None, trigger_captured_at=None):
        pre_captured_at = pre_captured_at or started_at
        trigger_captured_at = trigger_captured_at or started_at
        with self.lock, self._connect() as db:
            stamp = iso(started_at)
            cursor = db.execute(
                "INSERT INTO events(kind,started_at,ended_at,peak_score,created_at) VALUES('motion',?,?,?,?)",
                (stamp, stamp, score, iso(utc_now())),
            )
            event_id = cursor.lastrowid
            directory = self._event_directory(event_id, started_at)
            try:
                frames = (
                    ("pre", pre_jpeg, pre_captured_at),
                    ("trigger", trigger_jpeg, trigger_captured_at),
                    ("peak", trigger_jpeg, trigger_captured_at),
                )
                trigger_watermarked = None
                for role, jpeg, captured_at in frames:
                    watermarked = watermark_jpeg(jpeg, captured_at)
                    path = directory / f"{role}.jpg"
                    self._atomic_write(path, watermarked)
                    relative = path.relative_to(self.root).as_posix()
                    db.execute("INSERT INTO images(event_id,role,relative_path,bytes) VALUES(?,?,?,?)",
                               (event_id, role, relative, len(watermarked)))
                    if role == "trigger":
                        trigger_watermarked = watermarked
                self._write_thumbnail(directory, trigger_watermarked)
            except Exception:
                shutil.rmtree(directory, ignore_errors=True)
                raise
            return event_id

    def update_peak(self, event_id, jpeg, score, captured_at=None):
        watermarked = watermark_jpeg(jpeg, captured_at or utc_now())
        with self.lock, self._connect() as db:
            row = db.execute(
                "SELECT relative_path FROM images WHERE event_id=? AND role='peak'", (event_id,)
            ).fetchone()
            if not row:
                return
            path = (self.root / row["relative_path"]).resolve()
            if self.root not in path.parents:
                raise RuntimeError("Unsafe event image path")
            self._atomic_write(path, watermarked)
            self._write_thumbnail(path.parent, watermarked)
            db.execute("UPDATE images SET bytes=? WHERE event_id=? AND role='peak'",
                       (len(watermarked), event_id))
            db.execute("UPDATE events SET peak_score=? WHERE id=?", (score, event_id))

    def finish_motion(self, event_id, ended_at):
        with self.lock, self._connect() as db:
            row = db.execute("SELECT started_at FROM events WHERE id=?", (event_id,)).fetchone()
            if not row:
                return
            started = datetime.fromisoformat(row["started_at"])
            duration = max(0.0, (ended_at - started).total_seconds())
            db.execute("UPDATE events SET ended_at=?,duration_s=? WHERE id=?",
                       (iso(ended_at), round(duration, 1), event_id))

    def record_state(self, kind, when=None):
        if kind not in {"camera_offline", "camera_recovered"}:
            raise ValueError("Invalid state event")
        when = when or utc_now()
        stamp = iso(when)
        with self.lock, self._connect() as db:
            return db.execute(
                "INSERT INTO events(kind,started_at,ended_at,created_at) VALUES(?,?,?,?)",
                (kind, stamp, stamp, stamp),
            ).lastrowid

    def list_events(self, days=None, since=None, unseen=False, limit=100, offset=0):
        clauses, arguments = [], []
        if since:
            clauses.append("started_at >= ?")
            arguments.append(iso(since))
        elif days:
            clauses.append("started_at >= ?")
            arguments.append(iso(utc_now() - timedelta(days=days)))
        if unseen:
            clauses.append("viewed = 0")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        arguments.extend((min(max(int(limit), 1), 200), max(int(offset), 0)))
        with self.lock, self._connect() as db:
            rows = db.execute(
                "SELECT e.*, GROUP_CONCAT(i.role) AS image_roles FROM events e "
                "LEFT JOIN images i ON i.event_id=e.id" + where +
                " GROUP BY e.id ORDER BY e.started_at DESC LIMIT ? OFFSET ?", arguments,
            ).fetchall()
        return [dict(row) for row in rows]

    def summary(self):
        today = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
        with self.lock, self._connect() as db:
            count = db.execute(
                "SELECT COUNT(*) FROM events WHERE kind='motion' AND started_at>=?", (iso(today),)
            ).fetchone()[0]
            recent = db.execute(
                "SELECT started_at FROM events WHERE kind='motion' ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
        return {"today": count, "latest": recent[0] if recent else None}

    def mark_viewed(self, event_id):
        return event_id in self.mark_viewed_many([event_id])["updated"]

    def mark_viewed_many(self, event_ids):
        ids = list(dict.fromkeys(int(event_id) for event_id in event_ids))
        if not ids:
            return {"updated": [], "missing": []}
        placeholders = ",".join("?" for _ in ids)
        with self.lock, self._connect() as db:
            existing = {row[0] for row in db.execute(
                f"SELECT id FROM events WHERE id IN ({placeholders})", ids
            )}
            if existing:
                selected = sorted(existing)
                marks = ",".join("?" for _ in selected)
                db.execute(f"UPDATE events SET viewed=1 WHERE id IN ({marks})", selected)
        return {"updated": [event_id for event_id in ids if event_id in existing],
                "missing": [event_id for event_id in ids if event_id not in existing]}

    def image_path(self, event_id, role):
        if role not in IMAGE_ROLES | {"thumb"}:
            return None
        with self.lock, self._connect() as db:
            row = db.execute(
                "SELECT relative_path FROM images WHERE event_id=? AND role=?",
                (event_id, "peak" if role == "thumb" else role),
            ).fetchone()
        if not row:
            return None
        path = (self.root / row["relative_path"]).resolve()
        if role == "thumb":
            thumbnail = path.with_name("thumb.jpg")
            if not thumbnail.is_file() and path.is_file():
                try:
                    self._write_thumbnail(path.parent, path.read_bytes())
                except OSError:
                    return path
            path = thumbnail if thumbnail.is_file() else path
        if self.root not in path.parents or not path.is_file():
            return None
        return path

    def delete_event(self, event_id):
        return event_id in self.delete_events([event_id])["deleted"]

    @staticmethod
    def _remove_trash(paths):
        for path in paths:
            shutil.rmtree(path, ignore_errors=True)

    def delete_events(self, event_ids):
        ids = list(dict.fromkeys(int(event_id) for event_id in event_ids))
        if not ids:
            return {"deleted": [], "missing": []}
        placeholders = ",".join("?" for _ in ids)
        moved = []
        existing = set()
        with self.lock:
            try:
                with self._connect() as db:
                    existing = {row[0] for row in db.execute(
                        f"SELECT id FROM events WHERE id IN ({placeholders})", ids
                    )}
                    rows = db.execute(
                        f"SELECT event_id,relative_path FROM images WHERE event_id IN ({placeholders})", ids
                    ).fetchall()
                    directories = set()
                    for row in rows:
                        path = (self.root / row["relative_path"]).resolve()
                        if self.root in path.parents:
                            directories.add(path.parent)
                    for source in directories:
                        if not source.is_dir():
                            continue
                        destination = self.trash_root / f"{source.name}-{uuid.uuid4().hex}"
                        os.replace(source, destination)
                        moved.append((source, destination))
                    if existing:
                        selected = sorted(existing)
                        marks = ",".join("?" for _ in selected)
                        db.execute(f"DELETE FROM events WHERE id IN ({marks})", selected)
            except Exception:
                for source, destination in reversed(moved):
                    if destination.exists() and not source.exists():
                        source.parent.mkdir(parents=True, exist_ok=True)
                        os.replace(destination, source)
                raise
        if moved:
            threading.Thread(target=self._remove_trash,
                             args=([destination for _, destination in moved],),
                             name="event-trash-cleanup", daemon=True).start()
        return {"deleted": [event_id for event_id in ids if event_id in existing],
                "missing": [event_id for event_id in ids if event_id not in existing]}

    def cleanup(self, now=None):
        now = now or utc_now()
        cutoff = iso(now - timedelta(days=self.retention_days))
        with self.lock, self._connect() as db:
            expired = [row[0] for row in db.execute(
                "SELECT id FROM events WHERE started_at < ? ORDER BY started_at", (cutoff,)
            )]
        for event_id in expired:
            self.delete_event(event_id)
        with self.lock, self._connect() as db:
            total = db.execute("SELECT COALESCE(SUM(bytes),0) FROM images").fetchone()[0]
            oldest = [row for row in db.execute(
                "SELECT e.id,COALESCE(SUM(i.bytes),0) size FROM events e "
                "JOIN images i ON i.event_id=e.id GROUP BY e.id ORDER BY e.started_at"
            )]
        for event_id, size in oldest:
            if total <= self.quota_bytes:
                break
            if self.delete_event(event_id):
                total -= size
        return {"bytes": max(0, total), "expired": len(expired)}
