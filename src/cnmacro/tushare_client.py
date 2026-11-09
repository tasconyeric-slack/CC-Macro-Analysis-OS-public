"""Minimal Tushare Pro HTTP client (no extra dependency).

The token is read from the environment (GitHub Actions secret TUSHARE_TOKEN) and is never
logged, returned or written anywhere: every message that leaves this module is scrubbed.
Errors are classified so a caller can skip a series (missing token, endpoint not permitted)
without failing the whole run, and never substitutes guessed values.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

API_URL = "https://api.tushare.pro"
TOKEN_ENV = "TUSHARE_TOKEN"

MISSING_TOKEN = "missing_token"
INVALID_TOKEN = "invalid_token"
NOT_PERMITTED = "not_permitted"
RATE_LIMITED = "rate_limited"
NETWORK = "network"
OTHER = "error"


class TushareError(Exception):
    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


def token_from_env(env=None) -> str:
    return ((env if env is not None else os.environ).get(TOKEN_ENV) or "").strip()


def classify(message: str) -> str:
    """Map a Tushare error message (Chinese) to a coarse kind."""
    m = message or ""
    if "token" in m.lower() and any(k in m for k in ("不对", "无效", "失效", "过期", "invalid")):
        return INVALID_TOKEN
    if "权限" in m or "积分" in m:
        return NOT_PERMITTED
    if "频率" in m or "每分钟" in m or "每小时" in m or "每天" in m:
        return RATE_LIMITED
    return OTHER


def scrub(text: str, token: str) -> str:
    text = str(text)
    return text.replace(token, "***") if token else text


def call(api_name: str, params: dict | None = None, fields: list[str] | None = None, *,
         token: str | None = None, timeout: int = 60, retries: int = 2,
         rate_limit_wait: float = 62.0, opener=None) -> list[dict]:
    """One Tushare query; returns the rows as dicts. Raises TushareError(kind, scrubbed message)."""
    token = token_from_env() if token is None else token
    if not token:
        raise TushareError(MISSING_TOKEN, f"{TOKEN_ENV} is not set")
    body = {"api_name": api_name, "token": token, "params": params or {},
            "fields": ",".join(fields) if fields else ""}
    request = urllib.request.Request(API_URL, data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"}, method="POST")
    open_ = opener or urllib.request.urlopen
    last: TushareError | None = None
    for attempt in range(retries + 1):
        try:
            with open_(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            last = TushareError(NETWORK, scrub(f"{type(exc).__name__}: {exc}", token)[:200])
            time.sleep(min(5 * (attempt + 1), 15))
            continue
        if payload.get("code") not in (0, "0", None):
            message = scrub(payload.get("msg") or "", token)
            kind = classify(message)
            last = TushareError(kind, message[:300])
            if kind == RATE_LIMITED and attempt < retries:
                time.sleep(rate_limit_wait)
                continue
            raise last
        data = payload.get("data") or {}
        columns = data.get("fields") or []
        return [dict(zip(columns, item)) for item in data.get("items") or []]
    raise last or TushareError(OTHER, "no response")
