from __future__ import annotations

import base64
import json
import re
from datetime import datetime
from typing import Any


BASE64_TEXT_MIN_LENGTH = 512
MAX_RAW_BODY_BYTES = 256 * 1024
MAX_TEXT_CHARS = 4096
MAX_SANITIZE_DEPTH = 8
MAX_OBJECT_KEYS = 100
MAX_LIST_ITEMS = 100
BASE64_DATA_URL_RE = re.compile(
    r"^data:(?P<mime>[^;,]+)?(?P<meta>(?:;[^,]*)*);base64,(?P<body>[A-Za-z0-9+/=_\-\s]+)$",
    re.IGNORECASE,
)
BASE64_TEXT_RE = re.compile(r"^[A-Za-z0-9+/=_\-\s]+$")


def _estimate_base64_bytes(value: str) -> int:
    compact = re.sub(r"\s+", "", value or "")
    padding = len(compact) - len(compact.rstrip("="))
    return max(0, (len(compact) * 3 // 4) - padding)


def _format_size(byte_count: int) -> str:
    if byte_count >= 1024 * 1024:
        return f"{byte_count / (1024 * 1024):.1f}MB"
    if byte_count >= 1024:
        return f"{byte_count / 1024:.1f}KB"
    return f"{byte_count}B"


def _payload_label_from_mime(mime_type: str) -> str:
    normalized = str(mime_type or "application/octet-stream").lower()
    if normalized.startswith("image/"):
        return "image"
    if normalized.startswith("video/"):
        return "video"
    return "payload"


def _looks_like_base64(value: str) -> bool:
    compact = re.sub(r"\s+", "", value or "")
    if len(compact) < BASE64_TEXT_MIN_LENGTH:
        return False
    if len(compact) % 4 != 0:
        return False
    if not BASE64_TEXT_RE.match(compact):
        return False
    try:
        base64.b64decode(compact.replace("-", "+").replace("_", "/"), validate=True)
    except Exception:
        return False
    return True


def sanitize_request_body(raw_body: bytes) -> Any:
    if not raw_body:
        return None
    if len(raw_body) > MAX_RAW_BODY_BYTES:
        return f"[request body omitted, bytes={len(raw_body)}]"
    try:
        text = raw_body.decode("utf-8")
    except Exception:
        return "request body unavailable after sanitization"

    try:
        parsed = json.loads(text)
    except Exception:
        return _sanitize_value(text, depth=0)
    return _sanitize_value(parsed, depth=0)


def _sanitize_value(value: Any, *, depth: int) -> Any:
    if isinstance(value, dict):
        if depth >= MAX_SANITIZE_DEPTH:
            return f"[object truncated, depth={depth}]"
        result: dict[str, Any] = {}
        items = list(value.items())
        for key, item in items[:MAX_OBJECT_KEYS]:
            result[str(key)] = _sanitize_value(item, depth=depth + 1)
        if len(items) > MAX_OBJECT_KEYS:
            result["__truncated__"] = f"[object truncated, omitted_keys={len(items) - MAX_OBJECT_KEYS}]"
        return result
    if isinstance(value, list):
        if depth >= MAX_SANITIZE_DEPTH:
            return f"[list truncated, depth={depth}]"
        result = [_sanitize_value(item, depth=depth + 1) for item in value[:MAX_LIST_ITEMS]]
        if len(value) > MAX_LIST_ITEMS:
            result.append(f"[list truncated, omitted_items={len(value) - MAX_LIST_ITEMS}]")
        return result
    if not isinstance(value, str):
        return value

    data_url_match = BASE64_DATA_URL_RE.match(value.strip())
    if data_url_match:
        mime_type = str(data_url_match.group("mime") or "application/octet-stream")
        body = str(data_url_match.group("body") or "")
        label = _payload_label_from_mime(mime_type)
        size = _format_size(_estimate_base64_bytes(body))
        return f"[base64 {label} omitted, mime={mime_type}, approx={size}]"

    if _looks_like_base64(value):
        compact = re.sub(r"\s+", "", value)
        size = _format_size(_estimate_base64_bytes(compact))
        return f"[base64 payload omitted, chars={len(compact)}, approx={size}]"

    if len(value) > MAX_TEXT_CHARS:
        return f"{value[:MAX_TEXT_CHARS]}...[text omitted, chars={len(value)}]"

    return value


def parse_log_start_time(value: str) -> float:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("start_time is empty")

    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M",
    ):
        try:
            return datetime.strptime(raw, fmt).timestamp()
        except ValueError:
            continue
    raise ValueError("start_time must be YYYY-MM-DD HH:MM:SS")
