"""Wind private-data adapter (V1.2 Phase 1). Local only; no credential, raw response or value leaves
the researcher's machine.

    official Wind skill -> runtime verification -> pinned metric codes -> bounded grouped calls
    -> strict normalization -> atomic append-only private snapshot -> existing Observation store

Design rules (docs/wind-capability-note.md):
  * The officially installed skill is wrapped, never copied or vendored. Its version and the SHA256 of
    its runtime files are pinned in data/dictionary/wind_runtime.yaml and verified before and after a run.
  * The API key stays with the skill's own CLI. Nothing here reads, stores or logs it.
  * Metric codes come from the dictionary (`wind:` blocks). Normal refresh never searches for codes.
  * Failure is the default: a text reply is not a success, a missing code is not skipped, and provider
    metadata that differs from the dictionary stops the run.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import yaml

from . import normalize
from .store import Metric

WIND_PRIORITIES = ("P0", "P1", "P2")
WIND_ROLES = ("private_primary", "public_mirror", "gap_fill", "cross_check")
WIND_EVIDENCE_USE = ("active_diagnostic", "mirror", "snapshot_only")
WIND_AGGREGATES = (None, "month_end")
WIND_GAP_FIELDS = ("name", "freq", "unit")


@dataclass
class WindContract:
    """The pinned Wind route for one metric (docs/wind-capability-note.md). Codes are never searched
    for at refresh time. `expected_*` are the provider metadata that must come back unchanged;
    a field the provider does not supply is declared in `known_gaps`, never special-cased in code.
    The core sees this only as the incumbent `wind` route (store._wind_route)."""
    server: str                       # economic_data | index_data
    tool: str                         # query_economic_indicator_data | get_index_kline
    code: str                         # EDB code, or the exact windcode of an index
    priority: str                     # P0 | P1 | P2
    role: str                         # private_primary | public_mirror | gap_fill | cross_check
    evidence_use: str                 # active_diagnostic | mirror | snapshot_only
    query_group: str                  # metrics sharing a group are fetched in one call
    expected_name: str | None = None  # provider name, as returned
    expected_freq: str | None = None  # provider frequency: D | W | M | Q | A
    expected_unit: str | None = None  # provider unit, as returned
    value_field: str | None = None    # K-line column that carries the value
    aggregate: str | None = None      # month_end: store the last daily observation of each completed month
    mirrors: str | None = None        # the public metric this cross-checks
    experimental: bool = False        # not validated for evidence use
    same_series_as: str | None = None  # a second stored view (e.g. daily vs month-end) of the metric that owns this code
    known_gaps: list[dict] = field(default_factory=list)   # [{field: name|freq|unit, reason: ...}]


def check_wind_enums(metric: Metric) -> None:
    w = metric.wind
    for what, value, allowed in (("priority", w.priority, WIND_PRIORITIES), ("role", w.role, WIND_ROLES),
                                 ("evidence_use", w.evidence_use, WIND_EVIDENCE_USE),
                                 ("aggregate", w.aggregate, WIND_AGGREGATES)):
        if value not in allowed:
            raise ValueError(f"{metric.metric_id}: wind.{what} '{value}' not in {allowed}")
    for g in w.known_gaps:
        if set(g) != {"field", "reason"} or g["field"] not in WIND_GAP_FIELDS or not str(g["reason"]).strip():
            raise ValueError(f"{metric.metric_id}: wind.known_gaps entries need field in {WIND_GAP_FIELDS} and a reason")


RUNTIME_KIND = "wind-mcp-skill"                # the `kind` of the run manifest's generic runtime block
RUNTIME_CONTRACT = Path("data/dictionary/wind_runtime.yaml")
SKILL_DIR_ENV = "CCMACRO_WIND_SKILL_DIR"      # optional local override; never a place for the API key
SKILL_DIRNAME = "wind-mcp-skill"

# The only tools a refresh may call. `search_economic_indicator` is deliberately absent: codes are
# pinned in the dictionary, and discovery is a separate, audited activity.
ALLOWED_TOOLS = {"query_economic_indicator_data": ("economic_data", "economic"),
                 "get_index_kline": ("index_data", "kline")}
EDB_CODE = re.compile(r"^[A-Z]\d{7}$")                   # e.g. M1006337, S0203228
INDEX_WINDCODE = re.compile(r"^\d{6}\.[A-Z]{2,3}$")      # exact code, e.g. 000300.SH; never an index name
SHA256 = re.compile(r"^[0-9a-f]{64}$")

# Provider vocabulary (Wind's response formats), not metric data.
WIND_FREQ = {"日": "D", "周": "W", "月": "M", "季": "Q", "年": "A"}
KLINE_PERIOD_FREQ = {"1d": "D"}
QUOTA_MARKER = "账户积分余额不足"                         # "account points balance insufficient"
PERMISSION_MARKER = "受限指标已剔除"                      # "restricted indicators removed" (+ "无权限")
NO_RESULTS_MARKER = "没有搜索到指标"                      # "no indicator found"
CAP_NOTICE = re.compile(r"单次最多提取\s*\d+\s*个指标")    # "at most N indicators per call"
VERSION_RE = re.compile(r"""SKILL_VERSION\s*=\s*['"]([^'"]+)['"]""")

LIMITATION = ("Wind current-vintage data: availability begins at retrieved_at, not at the reference "
              "period or any release date. No first-availability or vintage claim (docs/wind-capability-note.md).")

# Normalized failure codes (WindFailure.code): WIND_RUNTIME_DRIFT, WIND_METADATA_DRIFT, WIND_SKILL_NOT_FOUND,
# WIND_FORBIDDEN_TOOL, AUTH_ERROR, BLOCKED_QUOTA, BLOCKED_PERMISSION, NO_RESULTS, INCOMPLETE_RESULT,
# MALFORMED_RESULT, NETWORK_ERROR, RATE_LIMIT_ERROR, BACKEND_ERROR, CLI_ERROR, CALL_BUDGET_EXCEEDED,
# WIND_CONTRACT_INVALID.
# Every one halts the run and publishes nothing. Only NETWORK_ERROR is ever retried (identically, a bounded
# number of times); auth, quota, backend, rate-limit, permission and drift errors stop at once.
RETRYABLE = {"NETWORK_ERROR"}


class WindFailure(Exception):
    """A normalized, fail-closed Wind error. `details` hold identifiers (codes, field names), never values."""

    def __init__(self, code: str, detail: str = "", group: str | None = None, details: list[str] | None = None):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code, self.detail, self.group, self.details = code, detail, group, list(details or [])

    def as_dict(self) -> dict:
        return {"code": self.code, "message": self.detail, "group": self.group, "details": self.details}


# ---------------------------------------------------------------- runtime contract
@dataclass(frozen=True)
class GroupWindow:
    back_days: int
    forward_days: int = 0
    period: str | None = None


@dataclass(frozen=True)
class RuntimeContract:
    version: str
    files: dict[str, str]
    min_spacing_s: float
    network_retries: int
    retry_pause_s: float
    call_timeout_s: float
    call_budget: int
    max_codes_per_query: int
    groups: dict[str, GroupWindow]


def load_runtime(path: str | Path = RUNTIME_CONTRACT) -> RuntimeContract:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    skill, ops = raw["skill"], raw["operations"]
    files = {str(k): str(v) for k, v in skill["files"].items()}
    bad = [k for k, v in files.items() if not SHA256.match(v)]
    if not files or bad:
        raise ValueError(f"{path}: skill.files needs a SHA256 for every runtime file (bad: {bad})")
    groups = {name: GroupWindow(int(g["back_days"]), int(g.get("forward_days", 0)), g.get("period"))
              for name, g in raw["groups"].items()}
    c = RuntimeContract(str(skill["version"]), files, float(ops["min_spacing_s"]), int(ops["network_retries"]),
                        float(ops["retry_pause_s"]), float(ops["call_timeout_s"]), int(ops["call_budget"]),
                        int(ops["max_codes_per_query"]), groups)
    if c.network_retries < 0 or c.call_budget < 1 or not 1 <= c.max_codes_per_query <= 10 or c.min_spacing_s < 0:
        raise ValueError(f"{path}: operations out of range")
    return c


def locate_skill_dir(env: dict | None = None, home: Path | None = None) -> Path:
    """The officially installed skill: `CCMACRO_WIND_SKILL_DIR` if set, else ~/.agents/skills/wind-mcp-skill."""
    env = os.environ if env is None else env
    override = env.get(SKILL_DIR_ENV)
    d = Path(override).expanduser() if override else (home or Path.home()) / ".agents" / "skills" / SKILL_DIRNAME
    if not d.is_dir():
        raise WindFailure("WIND_SKILL_NOT_FOUND", f"the Wind skill directory does not exist: {d}")
    return d


@dataclass(frozen=True)
class RuntimeReading:
    version: str | None
    hashes: dict[str, str | None]       # relative path -> SHA256, or None when the file is missing

    def as_dict(self) -> dict:
        return {"version": self.version, "files": dict(self.hashes)}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_runtime(skill_dir: Path, contract: RuntimeContract) -> RuntimeReading:
    """Fingerprint the installed runtime. Content only: mtimes change when the skill touches itself."""
    hashes: dict[str, str | None] = {}
    for rel in contract.files:
        f = Path(skill_dir) / rel
        hashes[rel] = sha256_bytes(f.read_bytes()) if f.is_file() else None
    cli = Path(skill_dir) / "scripts/cli.mjs"
    m = VERSION_RE.search(cli.read_text(encoding="utf-8", errors="replace")) if cli.is_file() else None
    return RuntimeReading(m.group(1) if m else None, hashes)


def runtime_differences(reading: RuntimeReading, contract: RuntimeContract) -> list[str]:
    diffs = []
    if reading.version != contract.version:
        diffs.append(f"version: installed {reading.version}, pinned {contract.version}")
    for rel, want in contract.files.items():
        got = reading.hashes.get(rel)
        if got is None:
            diffs.append(f"{rel}: missing")
        elif got != want:
            diffs.append(f"{rel}: SHA256 {got[:12]} differs from pinned {want[:12]}")
    return diffs


def verify_runtime(skill_dir: Path, contract: RuntimeContract, phase: str) -> RuntimeReading:
    """Raise WIND_RUNTIME_DRIFT unless the installed skill is exactly the pinned one."""
    reading = read_runtime(skill_dir, contract)
    diffs = runtime_differences(reading, contract)
    if diffs:
        raise WindFailure("WIND_RUNTIME_DRIFT", f"the installed Wind skill differs from the pinned runtime ({phase})",
                          details=diffs)
    return reading


def pin_runtime(path: str | Path, reading: RuntimeReading) -> None:
    """Rewrite the version and file hashes of the contract in place (comments and layout kept)."""
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    text, n = re.subn(r'(?m)^(  version:\s*)"[^"]*"', lambda m: f'{m.group(1)}"{reading.version}"', text, count=1)
    if n != 1:
        raise ValueError(f"{p}: cannot find skill.version")
    for rel, digest in reading.hashes.items():
        if digest is None:
            raise ValueError(f"cannot pin: {rel} is missing from the installed skill")
        text, n = re.subn(rf"(?m)^(    {re.escape(rel)}:\s*)[0-9a-f]{{64}}", lambda m: m.group(1) + digest, text, count=1)
        if n != 1:
            raise ValueError(f"{p}: cannot find a hash line for {rel}")
    p.write_text(text, encoding="utf-8", newline="")


# ---------------------------------------------------------------- the plan: pinned codes, grouped
@dataclass(frozen=True)
class Group:
    name: str
    server: str
    tool: str
    codes: tuple[str, ...]
    metric_ids: tuple[str, ...]
    window: GroupWindow


def p0_metrics(metrics: dict[str, Metric]) -> list[Metric]:
    return [m for m in metrics.values() if m.wind is not None and m.wind.priority == "P0"]


def validate_contracts(metrics: dict[str, Metric], runtime: RuntimeContract) -> None:
    """Static checks on what is specific to the Wind adapter: allowed tools, code formats, the K-line window, query
    groups and the per-query cap. The provider-neutral route rules (frequency, known gaps, second views, boundary)
    are enforced for every route by the dictionary loader (store._validate_routes). Raises ValueError listing every problem."""
    errs: list[str] = []
    seen_codes: dict[str, Metric] = {}
    by_group: dict[str, list[Metric]] = {}
    for m in p0_metrics(metrics):
        w, mid = m.wind, m.metric_id
        if w.tool not in ALLOWED_TOOLS:
            errs.append(f"{mid}: wind.tool '{w.tool}' is not an allowed refresh tool {sorted(ALLOWED_TOOLS)}")
            continue
        server, kind = ALLOWED_TOOLS[w.tool]
        if w.server != server:
            errs.append(f"{mid}: tool {w.tool} belongs to server {server}, not {w.server}")
        if kind == "economic" and not EDB_CODE.match(w.code):
            errs.append(f"{mid}: '{w.code}' is not an EDB code of the form M0000000")
        if kind == "kline":
            if not INDEX_WINDCODE.match(w.code):
                errs.append(f"{mid}: K-line retrieval needs the exact windcode (e.g. 000300.SH), got '{w.code}'")
            if not w.value_field:
                errs.append(f"{mid}: K-line contract needs wind.value_field")
        owner = seen_codes.setdefault(w.code, m)
        if owner is not m and w.query_group != owner.wind.query_group:   # one request feeds both views of the series
            errs.append(f"{mid}: a second view of {w.code} must share {owner.metric_id}'s query_group")
        if w.query_group not in runtime.groups:
            errs.append(f"{mid}: query_group '{w.query_group}' is not defined in wind_runtime.yaml")
        by_group.setdefault(w.query_group, []).append(m)
    for name, ms in by_group.items():
        pairs = {(m.wind.server, m.wind.tool) for m in ms}
        if len(pairs) > 1:
            errs.append(f"group {name}: mixes server/tool pairs {sorted(pairs)}")
        codes = {m.wind.code for m in ms}
        if len(codes) > runtime.max_codes_per_query:
            errs.append(f"group {name}: {len(codes)} codes exceed the {runtime.max_codes_per_query}-code query cap")
        if any(m.wind.tool == "get_index_kline" for m in ms):
            if len(ms) != 1:
                errs.append(f"group {name}: a K-line call takes exactly one windcode")
            if runtime.groups.get(name) and runtime.groups[name].period not in KLINE_PERIOD_FREQ:
                errs.append(f"group {name}: K-line period must be one of {sorted(KLINE_PERIOD_FREQ)}")
    for name in runtime.groups:
        if name not in by_group:
            errs.append(f"group {name}: defined in wind_runtime.yaml but no P0 metric uses it")
    if errs:
        raise ValueError("Wind contract errors:\n  - " + "\n  - ".join(errs))


def plan_groups(metrics: dict[str, Metric], runtime: RuntimeContract) -> list[Group]:
    """One Group per query_group, in the order wind_runtime.yaml lists them. At most
    `max_codes_per_query` codes in each, and no search call anywhere."""
    validate_contracts(metrics, runtime)
    ms = p0_metrics(metrics)
    plan = []
    for name, window in runtime.groups.items():
        members = [m for m in ms if m.wind.query_group == name]
        codes = tuple(dict.fromkeys(m.wind.code for m in members))      # a code is requested once, whatever views it feeds
        plan.append(Group(name, members[0].wind.server, members[0].wind.tool,
                          codes, tuple(m.metric_id for m in members), window))
    return plan


def window_dates(group: Group, today: date) -> tuple[str, str]:
    return ((today - timedelta(days=group.window.back_days)).isoformat(),
            (today + timedelta(days=group.window.forward_days)).isoformat())


def build_request(group: Group, today: date) -> dict:
    """The CLI params for a group: pinned codes only, explicit bounded dates."""
    if group.tool not in ALLOWED_TOOLS:
        raise WindFailure("WIND_FORBIDDEN_TOOL", f"{group.tool} is not an allowed refresh tool", group.name)
    begin, end = window_dates(group, today)
    if ALLOWED_TOOLS[group.tool][1] == "economic":
        return {"question": ",".join(group.codes), "beginDate": begin, "endDate": end}
    return {"windcode": group.codes[0], "begin_date": begin, "end_date": end, "period": group.window.period}


# ---------------------------------------------------------------- the official CLI
Transport = Callable[[str, str, dict, Path], str]   # (server, tool, params, request_file) -> CLI stdout


def cli_transport(skill_dir: Path, timeout_s: float, node: str | None = None) -> Transport:
    """Call the installed skill's CLI: `node scripts/cli.mjs call <server> <tool> @<request-file>`, run from
    the skill directory. The request file lives in the private run directory, not in the skill. The CLI
    resolves its own API key; this process never sees it."""
    exe = node or shutil.which("node")
    if not exe:
        raise WindFailure("WIND_SKILL_NOT_FOUND", "node is not on PATH; the Wind CLI needs it")

    def call(server: str, tool: str, params: dict, request_file: Path) -> str:
        if tool not in ALLOWED_TOOLS:
            raise WindFailure("WIND_FORBIDDEN_TOOL", f"{tool} is not an allowed refresh tool")
        request_file.parent.mkdir(parents=True, exist_ok=True)
        request_file.write_text(json.dumps(params, ensure_ascii=False), encoding="utf-8")
        try:
            done = subprocess.run([exe, "scripts/cli.mjs", "call", server, tool, "@" + str(request_file.resolve())],
                                  cwd=skill_dir, capture_output=True, stdin=subprocess.DEVNULL, timeout=timeout_s)
        except subprocess.TimeoutExpired:
            raise WindFailure("NETWORK_ERROR", f"the Wind CLI did not answer within {timeout_s:.0f}s") from None
        out = done.stdout.decode("utf-8", errors="replace")
        if not out.strip():
            raise WindFailure("MALFORMED_RESULT", f"the Wind CLI exited {done.returncode} with no output")
        return out

    return call


# ---------------------------------------------------------------- interpreting a response
def _texts(out: dict) -> list[str]:
    content = out.get("content")
    if not isinstance(content, list):
        raise WindFailure("MALFORMED_RESULT", "response has no content list")
    return [c["text"] for c in content if isinstance(c, dict) and c.get("type") == "text" and isinstance(c.get("text"), str)]


def interpret(stdout: str) -> dict:
    """The data payload of a successful CLI call, or a WindFailure.

    Wind can answer a failed request with a nominally successful MCP response carrying plain text,
    so a reply is only data if it parses as the expected JSON payload and carries none of the known
    failure notices."""
    try:
        out = json.loads(stdout)
    except ValueError:
        raise WindFailure("MALFORMED_RESULT", "CLI output is not JSON") from None
    if not isinstance(out, dict):
        raise WindFailure("MALFORMED_RESULT", "CLI output is not a JSON object")
    if out.get("ok") is False:                                  # the CLI's own error envelope
        code, message = str(out.get("code") or ""), str(out.get("message") or "")
        if QUOTA_MARKER in message:
            raise WindFailure("BLOCKED_QUOTA", "Wind account credits are exhausted")
        if code in ("AUTH_ERROR", "NETWORK_ERROR", "RATE_LIMIT_ERROR"):
            raise WindFailure(code, "")
        if code == "backend_error":
            raise WindFailure("BACKEND_ERROR", "the Wind backend returned an error")
        raise WindFailure("CLI_ERROR", f"CLI error {code or 'UNKNOWN'}")
    texts = _texts(out)
    if QUOTA_MARKER in "".join(texts):
        raise WindFailure("BLOCKED_QUOTA", "Wind account credits are exhausted")
    if out.get("isError"):
        raise WindFailure("BACKEND_ERROR", "the Wind backend flagged the response as an error")
    payloads, soft = [], []
    for t in texts:
        try:
            parsed = json.loads(t)
        except ValueError:
            parsed = None
        if isinstance(parsed, dict):
            payloads.append(parsed)
        else:
            soft.append(t)
    if any(PERMISSION_MARKER in t for t in soft):
        blocked = sorted(set(re.findall(r"[A-Z]\d{7}", " ".join(soft))))
        raise WindFailure("BLOCKED_PERMISSION", "restricted indicators were removed (no permission)", details=blocked)
    if any(NO_RESULTS_MARKER in t for t in soft):
        raise WindFailure("NO_RESULTS", "Wind found no matching indicator")
    if soft or len(payloads) != 1:
        raise WindFailure("MALFORMED_RESULT", "response is not a single structured payload")
    return payloads[0]


@dataclass
class Series:
    code: str
    observed: dict                       # provider metadata that was supplied: name, freq, unit
    dates: list[str]                     # yyyyMMdd
    values: list


def parse_economic(payload: dict, group: Group) -> tuple[dict[str, Series], bool]:
    """Series by code from a query_economic_indicator_data payload; fail unless every requested code is present."""
    metrics = payload.get("metrics")
    if not isinstance(metrics, list):
        raise WindFailure("MALFORMED_RESULT", "payload has no metrics list", group.name)
    cap = bool(CAP_NOTICE.search(str(payload.get("summary") or "")))
    out: dict[str, Series] = {}
    for m in metrics:
        meta = m.get("meta") if isinstance(m, dict) else None
        if not isinstance(meta, dict) or not meta.get("code"):
            raise WindFailure("MALFORMED_RESULT", "a metric has no meta.code", group.name)
        dates, values = m.get("date"), m.get("value")
        if not isinstance(dates, list) or not isinstance(values, list) or len(dates) != len(values):
            raise WindFailure("MALFORMED_RESULT", f"{meta['code']}: date and value arrays do not line up", group.name)
        if meta["code"] in out:
            raise WindFailure("MALFORMED_RESULT", f"{meta['code']}: returned twice", group.name)
        freq = meta.get("freq")
        out[meta["code"]] = Series(meta["code"], {"name": meta.get("name"), "freq": WIND_FREQ.get(freq, freq),
                                                  "unit": meta.get("unit")}, [str(d) for d in dates], values)
    extra = sorted(set(out) - set(group.codes))
    if extra:
        raise WindFailure("WIND_METADATA_DRIFT", "codes were returned that were not requested", group.name, extra)
    missing = [c for c in group.codes if c not in out]
    if missing:
        why = " (the payload carries the per-query indicator cap notice)" if cap else ""
        raise WindFailure("INCOMPLETE_RESULT", f"requested codes are missing from the response{why}", group.name, missing)
    return out, cap


def parse_kline(payload: dict, group: Group, contract: WindContract) -> dict[str, Series]:
    data = payload.get("data")
    if payload.get("error"):
        raise WindFailure("BACKEND_ERROR", "the K-line response carries an error", group.name)
    if not isinstance(data, dict):
        raise WindFailure("MALFORMED_RESULT", "K-line payload has no data object", group.name)
    names = [c.get("name") for c in data.get("columns") or [] if isinstance(c, dict)]
    need = ["TIME", contract.value_field]
    if any(n not in names for n in need):
        raise WindFailure("WIND_METADATA_DRIFT", "K-line columns changed", group.name, [n for n in need if n not in names])
    rows = data.get("rows")
    if not isinstance(rows, list) or not rows:
        raise WindFailure("NO_RESULTS", "the K-line response has no rows", group.name)
    it, iv = names.index("TIME"), names.index(contract.value_field)
    dates, values = [], []
    for r in rows:
        m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", str(r[it])) if isinstance(r, list) and len(r) == len(names) else None
        if not m:
            raise WindFailure("MALFORMED_RESULT", "a K-line row has no parseable date", group.name)
        dates.append("".join(m.groups()))
        values.append(r[iv])
    # name and unit are not supplied by K-line responses (declared as known gaps); the frequency is the requested bar
    observed = {"name": None, "unit": None, "freq": KLINE_PERIOD_FREQ[group.window.period]}
    return {group.codes[0]: Series(group.codes[0], observed, dates, values)}


def metadata_differences(contract: WindContract, series: Series) -> list[str]:
    """Where the provider's metadata differs from the dictionary. A field the contract records as a
    known gap must still be absent: if Wind starts supplying it, the contract needs a review."""
    return normalize.metadata_differences(
        {"name": contract.expected_name, "freq": contract.expected_freq, "unit": contract.expected_unit}, series.observed)


# ---------------------------------------------------------------- normalization
def reference_period(wind_date: str, freq: str) -> str:
    m = re.match(r"^(\d{4})(\d{2})(\d{2})$", wind_date)
    if not m:
        raise WindFailure("MALFORMED_RESULT", "an observation date is not yyyyMMdd")
    y, mo, d = m.groups()
    if not 1 <= int(mo) <= 12:
        raise WindFailure("MALFORMED_RESULT", "an observation date has an invalid month")
    return {"D": f"{y}-{mo}-{d}", "M": f"{y}-{mo}", "Q": f"{y}Q{(int(mo) - 1) // 3 + 1}"}[freq]


def to_number(v) -> float | int | None:
    """A finite number, or None for a missing value. Anything else is malformed."""
    if v is None or (isinstance(v, str) and v.strip().upper() in ("", "INVALID", "NULL", "NAN")):
        return None
    if isinstance(v, bool):
        raise WindFailure("MALFORMED_RESULT", "a value is a boolean")
    try:
        x = v if isinstance(v, (int, float)) else float(v)
    except (TypeError, ValueError):
        raise WindFailure("MALFORMED_RESULT", "a value is not numeric") from None
    return None if isinstance(x, float) and not math.isfinite(x) else x


def observation_rows(metric: Metric, series: Series, retrieved_at: str) -> tuple[list[dict], dict]:
    """Observation-contract rows for one metric (source=Wind, source_class=private, release_date empty:
    availability is retrieved_at, never a release date) plus counts for the manifest."""
    w = metric.wind
    pts, nulls = [], 0
    for d, v in zip(series.dates, series.values):
        reference_period(d, "D")                                   # a date that is not yyyyMMdd is malformed
        x = to_number(v)
        if x is None:
            nulls += 1
        else:
            pts.append((d, x))
    pts.sort()
    note = [LIMITATION]
    if w.experimental:
        note.append("EXPERIMENTAL: not validated as a pre-release value; a snapshot, never an evidence input.")
    note += [g["reason"] for g in w.known_gaps]
    month_end_dates: dict[str, str] = {}
    if w.aggregate == "month_end":                                 # the shared rule; Wind's response is complete to the retrieval date
        emitted, _ = normalize.month_end_points(pts, retrieved_at, covered_through=normalize.beijing_date(retrieved_at))
        pts = [(ym01, x) for ym01, _, x in emitted]
        month_end_dates = {ym01[:6]: d for ym01, d, _ in emitted}
    rows, seen = [], set()
    for d, x in pts:
        period = reference_period(d, metric.frequency)
        if period in seen:
            raise WindFailure("MALFORMED_RESULT", f"{metric.metric_id}: duplicate reference period {period}")
        seen.add(period)
        limitation = " ".join(note)
        if w.aggregate == "month_end":
            limitation += f" Month-end value: the last Wind observation dated within the month ({month_end_dates[d[:6]]})."
        rows.append(normalize.observation_row(metric, period, x, retrieved_at, source="Wind", series_key=w.code,
                                              limitation=limitation))
    if not rows:
        raise WindFailure("INCOMPLETE_RESULT", f"{metric.metric_id}: no usable observations in the response")
    return rows, {"rows": len(rows), "null_values": nulls}


@dataclass
class GroupResult:
    rows: list[dict] = field(default_factory=list)
    stats: dict = field(default_factory=dict)          # metric_id -> counts
    cap_notice: bool = False


def process_group(group: Group, metrics: dict[str, Metric], stdout: str, retrieved_at: str) -> GroupResult:
    """Interpret one CLI reply and return normalized rows, or raise a WindFailure. Pure: no I/O."""
    try:
        payload = interpret(stdout)
        by_code: dict[str, list[Metric]] = {}
        for mid in group.metric_ids:
            by_code.setdefault(metrics[mid].wind.code, []).append(metrics[mid])
        kind = ALLOWED_TOOLS[group.tool][1]
        if kind == "economic":
            series, cap = parse_economic(payload, group)
        else:
            series, cap = parse_kline(payload, group, by_code[group.codes[0]][0].wind), False
        drift = []
        for code, s in series.items():
            for m in by_code[code]:
                drift += [f"{m.metric_id} ({code}) {d}" for d in metadata_differences(m.wind, s)]
        if drift:
            raise WindFailure("WIND_METADATA_DRIFT", "provider metadata differs from the dictionary contract", group.name, drift)
        res = GroupResult(cap_notice=cap)
        for mid in group.metric_ids:                      # dictionary order, not response order
            m = metrics[mid]
            rows, st = observation_rows(m, series[m.wind.code], retrieved_at)
            res.rows += rows
            res.stats[mid] = st
        return res
    except WindFailure as f:
        f.group = f.group or group.name
        raise


def validate_rows(rows: list[dict], metrics: dict[str, Metric]) -> list[str]:
    """Pre-publication check of the whole batch against the Observation contract and the Wind route."""
    return normalize.validate_rows(rows, metrics, "wind", source_label="Wind")


# ---------------------------------------------------------------- a run: bounded calls, manifest, atomic publication
RUNS_DIR = Path("data/private/wind/runs")
OBS_DIR = Path("data/private/observations")


@dataclass
class RunOutcome:
    run_id: str
    status: str                       # published | failed
    run_dir: Path
    calls: int
    metrics: int
    rows: int
    snapshot: Path | None
    error: dict | None
    manifest: dict


class _Calls:
    """Serial, spaced, budgeted billable calls."""

    def __init__(self, runtime: RuntimeContract, sleep: Callable[[float], None], monotonic: Callable[[], float]):
        self.runtime, self.sleep, self.monotonic = runtime, sleep, monotonic
        self.made, self.last_end = 0, None

    def before_call(self) -> None:
        if self.made >= self.runtime.call_budget:
            raise WindFailure("CALL_BUDGET_EXCEEDED", f"the per-run budget of {self.runtime.call_budget} Wind calls is used up")
        if self.last_end is not None:
            wait = self.runtime.min_spacing_s - (self.monotonic() - self.last_end)
            if wait > 0:
                self.sleep(wait)
        self.made += 1

    def after_call(self) -> None:
        self.last_end = self.monotonic()


def _iso_utc(t: str) -> datetime:
    return datetime.fromisoformat(t).astimezone(timezone.utc)


def _new_run_dir(root: Path, started: str) -> tuple[str, Path]:
    base = _iso_utc(started).strftime("%Y%m%dT%H%M%SZ")
    for n in range(1, 100):
        run_id = base if n == 1 else f"{base}-{n}"
        d = root / RUNS_DIR / run_id
        try:
            d.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            continue
        (d / "raw").mkdir()
        return run_id, d
    raise WindFailure("MALFORMED_RESULT", "cannot allocate a run directory")


def publish_snapshot(staged: Path, obs_dir: Path, run_id: str) -> Path:
    """Atomically publish a fully validated batch as an immutable, never-overwritten Wind file (see
    normalize.publish_file)."""
    try:
        return normalize.publish_file(staged, obs_dir, "wind", run_id)
    except normalize.ProviderFailure as f:
        raise WindFailure(f.code, f.detail) from None


def _fetch_group(group: Group, idx: int, params: dict, metrics: dict[str, Metric], runtime: RuntimeContract,
                 transport: Transport, run_dir: Path, calls: _Calls, clock: Callable[[], str],
                 sleep: Callable[[float], None], monotonic: Callable[[], float], skill_dir: Path,
                 record: dict) -> GroupResult:
    """One group: spaced, budgeted, with at most `network_retries` identical retries after a NETWORK_ERROR."""
    stem = f"{idx:02d}_{group.name}"
    for attempt in range(1, runtime.network_retries + 2):
        verify_runtime(skill_dir, runtime, f"before call {calls.made + 1}")     # never run a changed skill
        calls.before_call()
        att = {"attempt": attempt, "started_at": clock()}
        record["attempts"].append(att)
        t0, failure, stdout = monotonic(), None, None
        try:
            stdout = transport(group.server, group.tool, params, run_dir / "requests" / f"{stem}.a{attempt}.json")
        except WindFailure as f:
            failure = f
        calls.after_call()
        att["elapsed_s"] = round(monotonic() - t0, 3)
        if stdout is not None:
            raw = run_dir / "raw" / f"{stem}.a{attempt}.json"
            data = stdout.encode("utf-8")
            raw.write_bytes(data)
            att.update(raw_file=f"raw/{raw.name}", raw_sha256=sha256_bytes(data), raw_bytes=len(data))
        if failure is None:
            retrieved_at = clock()
            try:
                result = process_group(group, metrics, stdout, retrieved_at)
            except WindFailure as f:
                failure = f
            else:
                att["outcome"] = "ok"
                record.update(status="ok", retrieved_at=retrieved_at, retries=attempt - 1,
                              rows={k: v["rows"] for k, v in result.stats.items()},
                              null_values={k: v["null_values"] for k, v in result.stats.items()},
                              cap_notice=result.cap_notice)
                return result
        failure.group = failure.group or group.name
        att["outcome"] = failure.code
        if failure.code in RETRYABLE and attempt <= runtime.network_retries:
            sleep(runtime.retry_pause_s)
            continue
        record.update(status="failed", retries=attempt - 1)
        raise failure
    raise AssertionError("unreachable")


def run_refresh(metrics: dict[str, Metric], runtime: RuntimeContract, *, root: Path | str = ".",
                skill_dir: Path | None = None, transport: Transport | None = None,
                clock: Callable[[], str] | None = None, sleep: Callable[[float], None] | None = None,
                monotonic: Callable[[], float] | None = None) -> RunOutcome:
    """Verify the runtime, fetch every P0 group, validate the whole batch, and only then publish it.

    Any failure leaves the private run directory (manifest and raw diagnostics) and publishes nothing."""
    import time
    from . import ingest
    root = Path(root)
    clock, sleep, monotonic = clock or ingest.now_iso, sleep or time.sleep, monotonic or time.monotonic
    started = clock()
    run_id, run_dir = _new_run_dir(root, started)
    manifest: dict = {"run_id": run_id, "started_at": started, "completed_at": None, "status": "failed", "error": None,
                      "runtime": normalize.runtime_block(
                          RUNTIME_KIND, {"version": runtime.version, "files": dict(runtime.files)}),
                      "budget": {"max_calls": runtime.call_budget, "calls_made": 0},
                      "operations": {"min_spacing_s": runtime.min_spacing_s, "network_retries": runtime.network_retries,
                                     "retry_pause_s": runtime.retry_pause_s},
                      "groups": [], "publication": {"status": "not_published"}, "metrics": 0, "rows": 0}
    calls = _Calls(runtime, sleep, monotonic)
    rows: list[dict] = []
    snapshot: Path | None = None

    def write_manifest() -> None:
        manifest["completed_at"] = clock()
        manifest["budget"]["calls_made"] = calls.made
        published = manifest["status"] == "published"
        manifest["metrics"] = len({r["metric_id"] for r in rows}) if published else 0
        manifest["rows"] = len(rows) if published else 0
        (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    try:
        skill_dir = skill_dir or locate_skill_dir()
        manifest["runtime"]["location"] = str(skill_dir)
        try:
            plan = plan_groups(metrics, runtime)
        except ValueError as e:
            raise WindFailure("WIND_CONTRACT_INVALID", str(e)) from None
        if len(plan) > runtime.call_budget:
            raise WindFailure("CALL_BUDGET_EXCEEDED", f"{len(plan)} groups exceed the per-run budget of {runtime.call_budget}")
        pre = verify_runtime(skill_dir, runtime, "before the run")
        manifest["runtime"]["pre"] = pre.as_dict()
        manifest["runtime"].update(version=pre.version, fingerprints=dict(pre.hashes))
        try:                                                    # the access policy fails closed, before any billable call
            for g in plan:
                for mid in g.metric_ids:
                    normalize.require_access(next(r for r in metrics[mid].sources if r.provider == "wind"), "automated_retrieval")
        except normalize.ProviderFailure as f:
            raise WindFailure(f.code, f.detail) from None
        transport = transport or cli_transport(skill_dir, runtime.call_timeout_s)
        today = _iso_utc(started).astimezone(timezone(timedelta(hours=8))).date()
        for i, group in enumerate(plan, 1):
            params = build_request(group, today)
            rec = {"name": group.name, "server": group.server, "tool": group.tool, "codes": list(group.codes),
                   "metric_ids": list(group.metric_ids), "params": params, "attempts": [], "status": "pending"}
            manifest["groups"].append(rec)
            res = _fetch_group(group, i, params, metrics, runtime, transport, run_dir, calls, clock, sleep, monotonic,
                               skill_dir, rec)
            rows += res.rows
        post = verify_runtime(skill_dir, runtime, "before publication")
        manifest["runtime"]["post"] = post.as_dict()
        manifest["runtime"]["unchanged"] = post.as_dict() == pre.as_dict()
        errs = validate_rows(rows, metrics)
        if errs:
            raise WindFailure("MALFORMED_RESULT", "the normalized batch failed validation", details=errs[:20])
        try:                                                    # rows of the route active now -> observations/, the rest -> candidates/
            pub = normalize.publish(rows, metrics, "wind", run_id, root=root, stage_dir=run_dir, at=clock(), started_at=started)
        except normalize.ProviderFailure as f:
            raise WindFailure(f.code, f.detail) from None
        active = pub["observations"]
        snapshot = root / active["file"] if active else None
        manifest["publication"] = {"status": "published", "file": active["file"] if active else None,
                                   "rows": active["rows"] if active else 0, "sha256": active["sha256"] if active else None}
        if pub["candidates"]:
            manifest["publication"]["candidates"] = pub["candidates"]
        manifest["route_states"] = pub["route_states"]
        manifest["status"] = "published"
    except WindFailure as f:
        manifest["error"] = f.as_dict()
        for g in manifest["groups"]:
            if g["status"] == "pending":
                g["status"] = "failed"
        if f.code == "WIND_RUNTIME_DRIFT":
            manifest["runtime"]["unchanged"] = False
    except Exception as e:                                      # fail closed, and still leave the diagnostics
        manifest["error"] = {"code": "UNEXPECTED_ERROR", "message": type(e).__name__, "group": None, "details": []}
        write_manifest()
        raise
    write_manifest()
    return RunOutcome(run_id, manifest["status"], run_dir, calls.made, manifest["metrics"], manifest["rows"],
                      snapshot, manifest["error"], manifest)
