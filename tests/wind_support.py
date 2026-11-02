"""Synthetic Wind replies and a scripted transport for the Wind tests.

Nothing here is provider data. Replies are built from the dictionary's own pinned metadata (codes, names,
units are public identifiers, not licensed values) with obviously fake numbers, so the suite needs no
credential and no real observation ever becomes a fixture."""
from __future__ import annotations

import dataclasses
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path

from cnmacro import wind

ROOT = Path(__file__).resolve().parents[1]
FAKE = 7.25                       # every synthetic value is FAKE + index
FREQ_ZH = {"D": "日", "W": "周", "M": "月", "Q": "季", "A": "年"}
KLINE_COLUMNS = ["TIME", "OPEN", "MATCH", "HIGH", "LOW", "TURNOVER", "VOLUME", "CHANGEHANDRATE", "AVPRICE"]

SKILL_FILES = {"scripts/cli.mjs": "const SKILL_VERSION = '9.9.9';\n// synthetic stand-in, not the Wind skill\n",
               "scripts/tool-manifest.json": "{}\n", "scripts/call-rules.json": "{}\n",
               "scripts/update-check.mjs": "// synthetic stand-in\n"}


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def make_skill(root: Path) -> Path:
    d = root / "skill"
    for rel, text in SKILL_FILES.items():
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / rel).write_bytes(text.encode("utf-8"))      # bytes, so Windows does not rewrite newlines under the pinned hash
    return d


def pinned_runtime(real: wind.RuntimeContract, **changes) -> wind.RuntimeContract:
    """The real operations and groups, pinned to the synthetic skill."""
    return dataclasses.replace(real, version="9.9.9", files={rel: sha(t) for rel, t in SKILL_FILES.items()}, **changes)


class Clock:
    """True-time stand-in: every reading is one second later."""

    def __init__(self, start="2026-10-10T08:00:00+00:00"):
        self.t = datetime.fromisoformat(start)

    def __call__(self) -> str:
        self.t += timedelta(seconds=1)
        return self.t.isoformat()


def envelope(payload) -> str:
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return json.dumps({"content": [{"type": "text", "text": text}], "isError": False,
                       "cli_meta": {"schema_version": "1.0", "warnings": []}}, ensure_ascii=False)


def error_envelope(code: str, message: str = "") -> str:
    return json.dumps({"ok": False, "code": code, "message": message}, ensure_ascii=False)


def dates_for(w, metric) -> list[str]:
    if w.aggregate == "month_end":      # two completed months and a partial one in the retrieval month
        return ["20260828", "20260831", "20260929", "20260930", "20261008"]
    if w.expected_freq == "D":
        return ["20261007", "20261008", "20261009"]
    return ["20260630", "20260731", "20260831"]


def economic_payload(group: wind.Group, metrics, drop=(), tweak=None, values=None) -> dict:
    series = []
    owners = {}
    for mid in group.metric_ids:                     # one series per code: a second stored view shares its owner's reply
        owners.setdefault(metrics[mid].wind.code, mid)
    for mid in owners.values():
        m = metrics[mid]
        w = m.wind
        if w.code in drop:
            continue
        dates = dates_for(w, m)
        meta = {"code": w.code, "name": w.expected_name, "unit": w.expected_unit, "freq": FREQ_ZH[w.expected_freq],
                "source": "synthetic"}
        if tweak:
            tweak(w, meta)
        vals = values(len(dates)) if callable(values) else values if values is not None else [FAKE + i for i in range(len(dates))]
        series.append({"meta": meta, "date": dates, "value": vals})
    return {"metrics": series}


def kline_payload(group: wind.Group, metrics, columns=None, rows=None) -> dict:
    cols = columns or KLINE_COLUMNS
    rows = rows if rows is not None else [[f"2026-10-0{d}T00:00:00.000+08:00"] + [str(FAKE + d)] * (len(cols) - 1) for d in (7, 8, 9)]
    return {"data": {"columns": [{"name": c, "type": "string"} for c in cols], "rows": rows,
                     "unit": {"TURNOVER 单位：": "元"}}, "error": None}


def good_reply(group: wind.Group, metrics, **kw) -> str:
    kind = wind.ALLOWED_TOOLS[group.tool][1]
    return envelope(economic_payload(group, metrics, **kw) if kind == "economic" else kline_payload(group, metrics, **kw))


class FakeWind:
    """A scripted transport. `script[group]` is a list of replies (a string, or a callable that returns one)
    consumed in order; a group without a script, or with its script used up, answers with a good reply."""

    def __init__(self, plan: list[wind.Group], metrics, script: dict | None = None, on_call=None):
        self.plan, self.metrics, self.script, self.on_call = plan, metrics, {k: list(v) for k, v in (script or {}).items()}, on_call
        self.calls: list[tuple[str, str, dict]] = []
        self.requests: list[Path] = []

    def group_of(self, params: dict) -> wind.Group:
        codes = tuple(params["question"].split(",")) if "question" in params else (params["windcode"],)
        return next(g for g in self.plan if g.codes == codes)

    def __call__(self, server, tool, params, request_file):
        self.calls.append((server, tool, params))
        self.requests.append(request_file)
        request_file.parent.mkdir(parents=True, exist_ok=True)
        request_file.write_text(json.dumps(params, ensure_ascii=False), encoding="utf-8")
        if self.on_call:
            self.on_call(len(self.calls))
        g = self.group_of(params)
        queue = self.script.get(g.name)
        if queue:
            reply = queue.pop(0)
            reply = reply() if callable(reply) else reply
            if isinstance(reply, Exception):
                raise reply
            return reply
        return good_reply(g, self.metrics)
