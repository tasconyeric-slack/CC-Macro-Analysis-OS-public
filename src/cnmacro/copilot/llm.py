"""DeepSeek Anthropic-compatible Messages transport; fixtures remain explicitly synthetic."""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

API_URL = "https://api.deepseek.com/anthropic/v1/messages"
API_VERSION = "2023-06-01"
DEFAULT_MODEL = "deepseek-flash"
MODELS = {"deepseek-flash", "deepseek-v4-pro"}
EFFORT = {"low": "low", "medium": "high", "high": "high", "xhigh": "high", "max": "max"}


class ModelUnavailable(Exception):
    """A call failed or returned no complete, supported answer."""

    def __init__(self, kind: str, detail: str = "", raw: dict | None = None, latency_ms: int | None = None,
                 response_meta: dict | None = None):
        super().__init__(f"{kind}: {detail}")
        self.kind, self.detail, self.raw, self.latency_ms = kind, detail, raw, latency_ms
        self.response_meta = response_meta or {}


@dataclass
class Reply:
    text: str
    raw: dict
    usage: dict = field(default_factory=dict)
    latency_ms: int = 0
    stop_reason: str | None = None
    served_model: str | None = None
    request_id: str | None = None
    attempts: int = 1
    message_id: str | None = None


def cost_usd(model: str, usage: dict) -> None:
    """Token counts alone cannot establish DeepSeek's model/time/cache billing category."""
    return None


class DeepSeekClient:
    genuine = True
    provider = "deepseek"

    def __init__(self, model: str = DEFAULT_MODEL, effort: str | None = "high", max_tokens: int = 24000,
                 timeout: int = 900, api_key: str | None = None):
        if model not in MODELS:
            raise ModelUnavailable("unsupported_model", "select deepseek-flash or deepseek-v4-pro")
        if effort is not None and effort not in EFFORT:
            raise ModelUnavailable("unsupported_effort", "select low, medium, high, xhigh, max or none")
        key = api_key if api_key is not None else os.environ.get("DEEPSEEK_API_KEY")
        if not key:
            raise ModelUnavailable("no_credential", "DEEPSEEK_API_KEY is not set (the deterministic pipeline does not need it)")
        self._key, self.model, self.requested_effort = key, model, effort
        self.effort = EFFORT.get(effort) if effort else None
        self.max_tokens, self.timeout = max_tokens, timeout

    def identity(self) -> dict:
        return {"provider": self.provider, "requested_id": self.model, "effort": self.effort,
                "requested_effort": self.requested_effort, "max_tokens": self.max_tokens,
                "api_version": API_VERSION}

    def _safe(self, value):
        """A provider error or response must not be able to echo the credential into a record."""
        return json.loads(json.dumps(value, ensure_ascii=False).replace(self._key, "[REDACTED]"))

    def _safe_header(self, value: str | None) -> str | None:
        return value.replace(self._key, "[REDACTED]") if value else None

    def call(self, system: str, user: str) -> Reply:
        body = {"model": self.model, "max_tokens": self.max_tokens, "system": system,
                "messages": [{"role": "user", "content": user}]}
        if self.effort:
            body["output_config"] = {"effort": self.effort}
        req = urllib.request.Request(
            API_URL, data=json.dumps(body).encode("utf-8"),
            headers={"content-type": "application/json", "x-api-key": self._key,
                     "anthropic-version": API_VERSION}, method="POST")
        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                payload = response.read()
                request_id = self._safe_header(response.headers.get("request-id") or response.headers.get("x-request-id"))
        except urllib.error.HTTPError as e:
            latency = int((time.monotonic() - t0) * 1000)
            request_id = self._safe_header((e.headers.get("request-id") or e.headers.get("x-request-id")) if e.headers else None)
            try:
                error = self._safe(json.loads(e.read(4096).decode("utf-8")))
            except (ValueError, UnicodeError):
                error = None
            error_type = (error.get("error") or {}).get("type") if isinstance(error, dict) and isinstance(error.get("error"), dict) else None
            safe_type = error_type if isinstance(error_type, str) and re.fullmatch(r"[a-zA-Z_ -]{1,60}", error_type) else "api_error"
            raise ModelUnavailable("http_error", f"HTTP {e.code}: {safe_type}",
                                   {"http_status": e.code, "error": error}, latency,
                                   {"request_id": request_id}) from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise ModelUnavailable("network", type(e).__name__, None,
                                   int((time.monotonic() - t0) * 1000)) from None
        latency = int((time.monotonic() - t0) * 1000)
        try:
            raw = self._safe(json.loads(payload.decode("utf-8")))
        except (ValueError, UnicodeError):
            raise ModelUnavailable("invalid_json", "the response body is not JSON", None, latency,
                                   {"request_id": request_id}) from None
        meta = {"request_id": request_id}
        if isinstance(raw, dict):
            meta |= {"served_model": raw.get("model"), "stop_reason": raw.get("stop_reason"),
                     "message_id": raw.get("id"), "usage": raw.get("usage")}
        if not isinstance(raw, dict) or raw.get("type") != "message":
            raise ModelUnavailable("unsupported_response", "expected a Messages response", raw, latency, meta)
        stop = raw.get("stop_reason")
        if stop == "refusal":
            raise ModelUnavailable("refusal", "the model refused the request", raw, latency, meta)
        if stop == "max_tokens":
            raise ModelUnavailable("truncated", "the answer reached max_tokens", raw, latency, meta)
        if stop not in ("end_turn", "stop_sequence"):
            raise ModelUnavailable("incomplete", "the response did not finish normally", raw, latency, meta)
        content, usage = raw.get("content"), raw.get("usage")
        if not isinstance(content, list) or not isinstance(usage, dict) or any(
            not isinstance(usage.get(k), int) or isinstance(usage.get(k), bool) or usage[k] < 0
            for k in ("input_tokens", "output_tokens")
        ):
            raise ModelUnavailable("unsupported_response", "missing content or token usage", raw, latency, meta)
        if raw.get("model") is not None and not isinstance(raw["model"], str):
            raise ModelUnavailable("unsupported_response", "invalid served model ID", raw, latency, meta)
        texts = []
        for block in content:
            if not isinstance(block, dict) or block.get("type") not in ("text", "thinking", "redacted_thinking"):
                raise ModelUnavailable("unsupported_response", "unsupported content block", raw, latency, meta)
            if block["type"] == "text":
                if not isinstance(block.get("text"), str):
                    raise ModelUnavailable("unsupported_response", "invalid text block", raw, latency, meta)
                texts.append(block["text"])
        answer = "".join(texts)
        if not answer.strip():
            raise ModelUnavailable("empty", "no text block in the response", raw, latency, meta)
        return Reply(answer, raw, usage, latency, stop, raw.get("model"), request_id, 1, raw.get("id"))


class FixtureClient:
    """Replays hand-written responses (draft first, then challenge). Never a genuine model run."""
    genuine = False
    provider = "fixture"
    model = "fixture:hand-written"

    def __init__(self, files: list[Path]):
        self._files, self._i = [Path(f) for f in files], 0

    def identity(self) -> dict:
        return {"provider": self.provider, "requested_id": self.model, "files": [f.name for f in self._files]}

    def call(self, system: str, user: str) -> Reply:
        f = self._files[self._i]
        self._i += 1
        return Reply(f.read_text(encoding="utf-8"), {"fixture": True, "file": f.name},
                     {"input_tokens": 0, "output_tokens": 0}, 0, "end_turn", self.model)
