from __future__ import annotations

import base64
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from core.request_logs import parse_log_start_time, sanitize_request_body
from core.stores import RequestLogStore


class RequestBodySanitizerTests(unittest.TestCase):
    def test_sanitizes_data_url_and_plain_base64_but_preserves_prompt(self) -> None:
        data_url_payload = base64.b64encode(b"image-bytes" * 200).decode("ascii")
        plain_payload = base64.b64encode(b"raw-image-bytes" * 200).decode("ascii")
        raw = (
            "{"
            '"model":"firefly-test",'
            '"prompt":"keep the full prompt",'
            '"image":"data:image/png;base64,'
            + data_url_payload
            + '",'
            '"nested":{"blob":"'
            + plain_payload
            + '"}'
            "}"
        ).encode("utf-8")

        sanitized = sanitize_request_body(raw)

        self.assertIsInstance(sanitized, dict)
        assert isinstance(sanitized, dict)
        self.assertEqual("keep the full prompt", sanitized["prompt"])
        self.assertNotIn(data_url_payload, str(sanitized))
        self.assertNotIn(plain_payload, str(sanitized))
        self.assertIn("base64 image omitted", str(sanitized["image"]))
        self.assertIn("base64 payload omitted", str(sanitized["nested"]["blob"]))

    def test_parse_log_start_time_accepts_space_separated_seconds(self) -> None:
        ts = parse_log_start_time("2026-06-17 17:51:46")

        parsed = datetime.fromtimestamp(ts)
        self.assertEqual("2026-06-17 17:51:46", parsed.strftime("%Y-%m-%d %H:%M:%S"))

    def test_sanitizer_truncates_unbounded_text_values(self) -> None:
        long_prompt = "prompt text: " * 600
        raw = ('{"prompt":"' + long_prompt + '"}').encode("utf-8")

        sanitized = sanitize_request_body(raw)

        self.assertIsInstance(sanitized, dict)
        assert isinstance(sanitized, dict)
        prompt = sanitized["prompt"]
        self.assertIsInstance(prompt, str)
        self.assertLess(len(prompt), len(long_prompt))
        self.assertIn("text omitted", prompt)
        self.assertIn(f"chars={len(long_prompt)}", prompt)

    def test_sanitizer_truncates_deep_nested_values(self) -> None:
        nested = "leaf"
        for _ in range(16):
            nested = {"child": nested}
        raw = json.dumps({"root": nested}).encode("utf-8")

        sanitized = sanitize_request_body(raw)

        self.assertIn("object truncated", str(sanitized))


class RequestLogStoreTests(unittest.TestCase):
    def test_list_filters_by_start_time_and_model_in_ascending_order_without_body(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = RequestLogStore(Path(tmp_dir) / "request_logs.jsonl", max_items=50)
            store.add_payload(
                {"id": "old", "ts": 100.0, "model": "firefly-a", "request_body": {"prompt": "old"}}
            )
            store.add_payload(
                {"id": "match-1", "ts": 200.0, "model": "firefly-a", "request_body": {"prompt": "one"}}
            )
            store.add_payload(
                {"id": "other-model", "ts": 250.0, "model": "firefly-b", "request_body": {"prompt": "two"}}
            )
            store.add_payload(
                {"id": "match-2", "ts": 300.0, "model": "firefly-a", "request_body": {"prompt": "three"}}
            )

            rows, total = store.list(
                limit=10,
                page=1,
                start_ts=150.0,
                model="firefly-a",
                order="asc",
            )

            self.assertEqual(2, total)
            self.assertEqual(["match-1", "match-2"], [row["id"] for row in rows])
            self.assertTrue(all(row["has_request_body"] for row in rows))
            self.assertTrue(all("request_body" not in row for row in rows))

    def test_get_returns_latest_matching_record_with_request_body(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = RequestLogStore(Path(tmp_dir) / "request_logs.jsonl", max_items=50)
            store.add_payload({"id": "same", "ts": 100.0, "request_body": {"prompt": "first"}})
            store.add_payload({"id": "same", "ts": 200.0, "request_body": {"prompt": "latest"}})

            item = store.get("same")

            self.assertIsNotNone(item)
            assert item is not None
            self.assertTrue(item["has_request_body"])
            self.assertEqual({"prompt": "latest"}, item["request_body"])


if __name__ == "__main__":
    unittest.main()
