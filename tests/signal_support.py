"""Synthetic inputs for the private-diagnostics tests. Nothing here is provider data: every value is made up
to put a signal on a chosen side of its threshold, and every row is labelled `synthetic`."""
from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from cnmacro.evidence import TestResult
from cnmacro.store import OBS_COLUMNS, load_dictionary

ROOT = Path(__file__).resolve().parents[1]
WHEN = "2026-10-10T08:00:00Z"              # the as-of time of the default synthetic snapshot
RETRIEVED = "2026-10-10T07:59:00+00:00"
LAST_DAY = "2026-10-09"                     # latest daily observation (Beijing date)
CITIES = {"bj": "cn_hf_prop_bj", "sh": "cn_hf_prop_sh", "sz": "cn_hf_prop_sz", "gz": "cn_hf_prop_gz"}
METRICS = load_dictionary(ROOT / "data/dictionary/metrics.yaml")


def series_key(provider: str, metric_id: str) -> str:
    """The key a provider's rows carry: Wind's is the pinned code of the metric; another provider's is made up here."""
    return METRICS[metric_id].wind.code if provider == "wind" else f"{provider.upper()}:{metric_id}"


def trading_days(n: int, end: str = LAST_DAY) -> list[str]:
    return [d.strftime("%Y-%m-%d") for d in pd.bdate_range(end=end, periods=n)]


def calendar_days(n: int, end: str = LAST_DAY) -> list[str]:
    return [d.strftime("%Y-%m-%d") for d in pd.date_range(end=end, periods=n, freq="D")]


@dataclass
class Scenario:
    """Knobs for one synthetic information set. None leaves that input out entirely."""
    dr007: tuple | None = (1.80, 1.80)                     # (previous 20 obs, recent 20 obs) level, %
    dr007_n: int = 40
    cgb_change_bp: float | None = 0.0                       # 20- and 60-day change of the daily 10Y
    cgb_n: int = 61
    csi_return_pct: float | None = 0.0
    csi_n: int = 25
    hh: tuple | None = ((100.0, 100.0), (100.0, 100.0))     # ((ST year-ago, ST recent), (ML year-ago, ML recent)) per month
    corp: tuple | None = ((100.0, 100.0), (100.0, 100.0))
    cities: dict = field(default_factory=lambda: {c: (100.0, 100.0) for c in CITIES})   # (previous, recent) daily area
    city_days: dict = field(default_factory=dict)          # city -> observed days per window (default 28)
    consensus: bool = True
    retrieved_at: str = RETRIEVED
    file: str = "wind_SYNTHETIC1"
    provider: str = "wind"                                 # whose rows these are (the `source` label is Wind for wind)
    last_day: str = LAST_DAY
    last_month: str = "2026-08"


def _row(metric_id: str, period: str, value, s: Scenario) -> dict:
    r = {c: "" for c in OBS_COLUMNS}
    r.update(metric_id=metric_id, reference_period=period, value=value, release_date_basis="unknown",
             retrieved_at=s.retrieved_at, source="Wind" if s.provider == "wind" else s.provider, source_code=series_key(s.provider, metric_id),
             source_class="private",
             quality_flag="ok", limitation="synthetic")
    r["_file"] = f"data/private/observations/{s.file}.csv"
    return r


def private_rows(s: Scenario) -> list[dict]:
    rows = []
    if s.dr007 is not None:
        days = trading_days(s.dr007_n, s.last_day)
        half = len(days) - 20
        rows += [_row("cn_dr007", d, s.dr007[0] if i < half else s.dr007[1], s) for i, d in enumerate(days)]
    if s.cgb_change_bp is not None:
        days = trading_days(s.cgb_n, s.last_day)
        rows += [_row("cn_cgb10y_daily", d, 1.75 + (s.cgb_change_bp / 100 if i == len(days) - 1 else 0), s)
                 for i, d in enumerate(days)]
    if s.csi_return_pct is not None:
        days = trading_days(s.csi_n, s.last_day)
        rows += [_row("mkt_csi300", d, 4000.0 * (1 + s.csi_return_pct / 100) if i == len(days) - 1 else 4000.0, s)
                 for i, d in enumerate(days)]
    last = pd.Period(s.last_month, freq="M")
    for prefix, spec in (("cn_loans_hh", s.hh), ("cn_loans_corp", s.corp)):
        if spec is None:
            continue
        for leg, (ago, now) in zip(("short", "mlt"), spec):
            for k in range(15):                               # last-14 .. last
                p = last - (14 - k)
                v = now if k >= 12 else ago if k <= 2 else 50.0
                rows.append(_row(f"{prefix}_{leg}_flow", str(p), v, s))
    for city, mid in CITIES.items():
        if city not in s.cities or s.cities[city] is None:
            continue
        prev, recent = s.cities[city]
        days = calendar_days(56, s.last_day)
        keep = s.city_days.get(city, 28)
        for i, d in enumerate(days):
            in_recent = i >= 28
            if (i % 28) >= keep:
                continue                                      # an unobserved day: not filled
            rows.append(_row(mid, d, recent if in_recent else prev, s))
    if s.consensus:
        rows += [_row("cn_cpi_consensus_wind", "2026-09", 0.5, s), _row("cn_ppi_consensus_wind", "2026-09", -2.0, s)]
    return rows


def frame(*scenarios: Scenario) -> pd.DataFrame:
    rows = [r for s in scenarios for r in private_rows(s)]
    df = pd.DataFrame(rows, columns=OBS_COLUMNS + ["_file"])
    df["value"] = pd.to_numeric(df["value"])
    df["consensus"] = pd.to_numeric(df["consensus"], errors="coerce")
    return df


def public_results(outcomes: dict[str, str]) -> dict[str, TestResult]:
    """Public TestResults with the given outcomes (true | false | insufficient_data)."""
    hyp = {"T-H1": "H1", "T-H2": "H2", "T-H3": "H3", "T-H4": "H4", "T-H0": "H0"}
    out = {}
    for tid, o in outcomes.items():
        effect = {"true": "supports", "false": "challenges"}.get(o, "none")
        out[tid] = TestResult(tid, hyp[tid[:4]], o, effect, None, None)
    return out


PRICE_UP = {"T-H1-01": "true", "T-H1-02": "true", "T-H1-03": "true", "T-H4-01": "false", "T-H4-02": "false"}
PRICE_DOWN = {"T-H1-01": "false", "T-H1-02": "false", "T-H1-03": "false", "T-H4-01": "false", "T-H4-02": "false"}

# Channel presets
HH_BROADENING = ((100.0, 150.0), (100.0, 150.0))
HH_WEAKENING = ((100.0, 50.0), (100.0, 50.0))
CORP_BROADENING = HH_BROADENING
CORP_WEAKENING = HH_WEAKENING
PROP_UP = {c: (100.0, 120.0) for c in CITIES}
PROP_DOWN = {c: (100.0, 80.0) for c in CITIES}


def write_publication(root: Path, s: Scenario, run_id: str, kind: str = "observations", manifest_sha: str | None = None) -> Path:
    """A published synthetic publication plus the run manifest the adapter would have written. `kind` is the directory
    it went to: observations (active) or candidates."""
    folder = root / "data/private" / kind
    folder.mkdir(parents=True, exist_ok=True)
    s.file = f"{s.provider}_{run_id}"
    df = pd.DataFrame(private_rows(s), columns=OBS_COLUMNS + ["_file"]).drop(columns="_file")
    path = folder / f"{s.provider}_{run_id}.csv"
    df.to_csv(path, index=False)
    entry = {"file": f"data/private/{kind}/{path.name}", "rows": len(df), "sha256": manifest_sha or hashlib.sha256(path.read_bytes()).hexdigest()}
    pub = {"status": "published", **entry} if kind == "observations" else {"status": "published", "file": None, "rows": 0,
                                                                          "sha256": None, "candidates": entry}
    run_dir = root / "data/private" / s.provider / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "manifest.json").write_text(json.dumps({"run_id": run_id, "status": "published", "publication": pub}), encoding="utf-8")
    return path


def write_snapshot(root: Path, s: Scenario, run_id: str, manifest_sha: str | None = None) -> Path:
    """A published synthetic Wind snapshot plus the run manifest refresh-private would have written."""
    return write_publication(root, s, run_id, "observations", manifest_sha)
