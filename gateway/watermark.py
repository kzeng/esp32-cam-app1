"""Timestamp watermarking for JPEG files saved or downloaded by the gateway."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import cv2
import numpy as np


DISPLAY_TIMEZONE = ZoneInfo("Asia/Shanghai")


def timestamp_text(captured_at):
    if not isinstance(captured_at, datetime) or captured_at.tzinfo is None:
        raise ValueError("captured_at must be a timezone-aware datetime")
    return captured_at.astimezone(DISPLAY_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")


def watermark_jpeg(jpeg, captured_at, quality=90):
    """Return a JPEG with a readable top-right timestamp watermark."""
    image = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("JPEG decode failed while adding timestamp")

    label = timestamp_text(captured_at)
    height, width = image.shape[:2]
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = min(0.85, max(0.42, width / 900))
    thickness = max(1, round(scale * 2))
    padding = max(5, round(scale * 9))
    margin = max(5, round(min(width, height) * 0.018))
    (text_width, text_height), baseline = cv2.getTextSize(label, font, scale, thickness)

    available = width - 2 * (margin + padding)
    if text_width > available:
        scale *= available / text_width
        thickness = max(1, round(scale * 2))
        (text_width, text_height), baseline = cv2.getTextSize(label, font, scale, thickness)

    left = max(margin, width - margin - text_width - 2 * padding)
    top = margin
    right = min(width - margin, left + text_width + 2 * padding)
    bottom = min(height - margin, top + text_height + baseline + 2 * padding)

    overlay = image.copy()
    cv2.rectangle(overlay, (left, top), (right, bottom), (0, 0, 0), cv2.FILLED)
    cv2.addWeighted(overlay, 0.58, image, 0.42, 0, image)
    origin = (left + padding, top + padding + text_height)
    cv2.putText(image, label, origin, font, scale, (255, 255, 255), thickness, cv2.LINE_AA)

    ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise ValueError("JPEG encode failed while adding timestamp")
    return encoded.tobytes()
