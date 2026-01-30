"""Loki push helper for structured JSON logs.

Used when SF_LOKI_ENABLED=true.
"""

import json
import os
import time
from typing import Dict, Any, List

import requests


class LokiClient:
    def __init__(self, endpoint: str, labels: str = "service=sf", timeout_s: int = 5):
        self.endpoint = endpoint.rstrip("/")
        self.labels = labels
        self.timeout_s = timeout_s

    def _build_stream(self, message: Dict[str, Any]) -> Dict[str, Any]:
        now_ns = int(time.time() * 1e9)
        label_pairs = [l.split("=", 1) for l in self.labels.split(",") if "=" in l]
        labels_obj = {k.strip(): v.strip() for k, v in label_pairs}
        return {
            "stream": labels_obj,
            "values": [[str(now_ns), json.dumps(message)]],
        }

    def push(self, message: Dict[str, Any]) -> None:
        payload = {"streams": [self._build_stream(message)]}
        resp = requests.post(
            f"{self.endpoint}/loki/api/v1/push",
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
            timeout=self.timeout_s,
        )
        resp.raise_for_status()


def get_loki_client() -> LokiClient:
    if os.getenv("SF_LOKI_ENABLED", "false").lower() != "true":
        return None
    endpoint = os.getenv("SF_LOKI_ENDPOINT", "http://localhost:3100")
    labels = os.getenv("SF_LOKI_LABELS", "service=sf,component=worker")
    timeout_s = int(os.getenv("SF_LOKI_TIMEOUT_S", "5"))
    try:
        return LokiClient(endpoint, labels, timeout_s)
    except Exception:
        return None

