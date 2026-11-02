"""Provider-neutral normalization, publication and route selection (V1.2.1 core).

What every provider adapter shares, lifted out of the Wind adapter so a second provider reuses it instead of
copying it (docs/provider/provider-independence-design.md sections 4-8):

    observation_row / validate_rows     the 12-column Observation contract and its pre-publication checks
    month_end_points                    the month-end rule, with a coverage guard
    metadata_differences                provider metadata drift against a route's `expected` block
    require_access                      the access policy fails closed, before any network call or file parse
    publish                             rows of the route active at `at` -> observations/, all others -> candidates/
    select_active / as_of_routed        the route filter, applied BEFORE store.as_of
    runtime_block / runtime_version     the generic `runtime` block of a run manifest

Nothing here names a provider. Which route is authoritative is `store.route_at`, a function of time.
"""
from __future__ import annotations

import csv
import hashlib
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from .store import OBS_COLUMNS, Metric, SourceRoute, as_of, route_at, route_change_at, utc_naive

OBS_DIR = Path("data/private/observations")       # active publications: the route was authoritative when written
CAND_DIR = Path("data/private/candidates")        # candidate publications: never evidence, never an anchor
PROVIDER_FAILURES = ("ACCESS_NOT_PERMITTED", "ROUTE_BACKFILL_AFTER_ACTIVATION", "ROUTE_HISTORY_RETROACTIVE",
                     "ANCHOR_NOT_ELIGIBLE", "MALFORMED_RESULT", "INCOMPLETE_RESULT")


class ProviderFailure(Exception):
    """A provider-neutral failure with one of the shared codes (design section 9)."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


# ---------------------------------------------------------------- the run manifest's runtime block
def runtime_block(kind: str, expected: dict | None = None) -> dict:
    """The generic `runtime` block every adapter's run manifest carries (design section 4):

        {kind, version, fingerprints, expected, ...}

    `kind` names what ran (a skill, an HTTP endpoint, a file parser); `version` and `fingerprints` ({name: SHA256}) are
    what was actually observed to have produced the run, filled once the adapter has verified it; `expected` is what the
    adapter pinned. An adapter adds its own keys (Wind: `pre`, `post`, `unchanged`, `location`). Readers use
    `runtime_version`, never an adapter-specific block."""
    return {"kind": kind, "version": None, "fingerprints": {}, "expected": dict(expected or {})}


def runtime_version(manifest: dict) -> str | None:
    """The runtime version a manifest records. A manifest written before V1.2.1 keeps it in the Wind-specific `skill`
    block; it is read as it is, never rewritten."""
    version = (manifest.get("runtime") or {}).get("version")
    return version if version is not None else (manifest.get("skill") or {}).get("version")


# ---------------------------------------------------------------- access policy
def require_access(route: SourceRoute, mode: str) -> None:
    """`mode` is `automated_retrieval` (a fetching adapter) or `manual_import` (a file parser). Raised before any
    network call or file is read. Storing the values at all also needs `private_use`. `unknown` is `prohibited`."""
    if not route.access.permits(mode):
        raise ProviderFailure("ACCESS_NOT_PERMITTED", f"{route.provider}: access.{mode} is {route.access.__dict__[mode]}")
    if not route.access.permits("private_use"):
        raise ProviderFailure("ACCESS_NOT_PERMITTED", f"{route.provider}: access.private_use is {route.access.private_use}")


# ---------------------------------------------------------------- rows
def provider_of(source) -> str:
    """The provider key a row's `source` names. Legacy Wind rows are labelled `Wind`; the key is `wind`."""
    return str(source).strip().lower()


def source_class_of(metric: Metric) -> str:
    return "public" if metric.redistribution == "public" else "private"


def fmt_value(x) -> str:
    return repr(x) if isinstance(x, float) else str(x)


def observation_row(metric: Metric, period: str, value, retrieved_at: str, *, source: str, series_key: str,
                    limitation: str, release_date: str = "", release_date_basis: str = "unknown") -> dict:
    """One Observation-contract row. `source_class` comes from the metric, never from the provider's name;
    a private row's availability is `retrieved_at`, so it carries no release date."""
    return {"metric_id": metric.metric_id, "reference_period": period, "value": fmt_value(value),
            "release_date": release_date, "release_date_basis": release_date_basis, "retrieved_at": retrieved_at,
            "source": source, "source_code": series_key, "source_class": source_class_of(metric), "consensus": "",
            "quality_flag": "ok", "limitation": limitation}


def validate_rows(rows: list[dict], metrics: dict[str, Metric], provider: str, source_label: str | None = None) -> list[str]:
    """Pre-publication check of the whole batch against the Observation contract and the provider's route.
    `source_label` is how the provider writes itself into `source` (legacy Wind rows say `Wind`)."""
    from .checks import PERIOD_RE
    label = source_label or provider
    errs, keys = [], set()
    for r in rows:
        m = metrics.get(r["metric_id"])
        if m is None:
            errs.append(f"{r['metric_id']}: not in the dictionary")
            continue
        route = next((x for x in m.sources if x.provider == provider), None)
        if route is None:
            errs.append(f"{r['metric_id']}: no route for provider {provider}")
            continue
        if set(r) != set(OBS_COLUMNS):
            errs.append(f"{r['metric_id']}: columns differ from the Observation contract")
        if not PERIOD_RE[m.frequency].match(r["reference_period"]):
            errs.append(f"{r['metric_id']}: period does not match frequency {m.frequency}")
        if r["source"] != label:
            errs.append(f"{r['metric_id']}: source is not {label}")
        if r["source_class"] != source_class_of(m):
            errs.append(f"{r['metric_id']}: source_class is not the one the metric's redistribution gives")
        if r["source_class"] == "private" and (r["release_date"] or not r["limitation"]):
            errs.append(f"{r['metric_id']}: a private row has no release date and needs a limitation")
        if r["source_code"] != route.series_key:
            errs.append(f"{r['metric_id']}: source_code is not the route's series_key")
        k = (r["metric_id"], r["reference_period"], r["retrieved_at"])
        if k in keys:
            errs.append(f"{r['metric_id']}@{r['reference_period']}: duplicate row")
        keys.add(k)
    return errs


def metadata_differences(expected: dict, observed: dict) -> list[str]:
    """Where the provider's metadata differs from the route's `expected`. A field `expected` records as None is a
    known gap and must still be absent: if the provider starts supplying it, the contract needs a review."""
    diffs = []
    for fld in ("name", "freq", "unit"):
        want, got = expected.get(fld), observed.get(fld)
        if want is None:
            if got not in (None, ""):
                diffs.append(f"{fld}: provider now supplies one; the contract records a known gap")
        elif got != want:
            diffs.append(f"{fld}: provider value differs from the contract")
    return diffs


# ---------------------------------------------------------------- month-end rule
def beijing_month(retrieved_at: str) -> tuple[int, int]:
    t = datetime.fromisoformat(retrieved_at).astimezone(timezone(timedelta(hours=8)))
    return t.year, t.month


def beijing_date(retrieved_at: str) -> str:
    return datetime.fromisoformat(retrieved_at).astimezone(timezone(timedelta(hours=8))).strftime("%Y%m%d")


def month_end_points(points: list[tuple[str, float]], retrieved_at: str, *, covered_through: str | None = None
                     ) -> tuple[list[tuple[str, str, float]], list[str]]:
    """The last observation of each COMPLETED month (Beijing calendar), from sorted (yyyymmdd, value) points.

    Returns ([(yyyymm01, date of the month-end observation, value)], skipped months). Coverage guard: a completed
    month is emitted only if the batch is known to extend past it, so a truncated download can never store an earlier
    day as the month-end. The batch is known to extend past month M when it holds a point in a later month, or when
    the adapter states `covered_through` (yyyymmdd, the date its response is complete to, which an API request
    window gives and a downloaded file does not)."""
    ry, rm = beijing_month(retrieved_at)
    last: dict[str, tuple[str, float]] = {}
    for d, x in points:
        if (int(d[:4]), int(d[4:6])) < (ry, rm):
            last[d[:6]] = (d, x)                                  # sorted, so the last write is the month-end
    latest = max((d for d, _ in points), default=None)
    emitted, skipped = [], []
    for ym, (d, x) in sorted(last.items()):
        month_last_day = pd.Period(f"{ym[:4]}-{ym[4:6]}", freq="M").end_time.strftime("%Y%m%d")
        covered = (latest is not None and latest[:6] > ym) or (covered_through is not None and covered_through >= month_last_day)
        if covered:
            emitted.append((ym + "01", d, x))
        else:
            skipped.append(ym)
    return emitted, skipped


# ---------------------------------------------------------------- publication
def write_rows(rows: list[dict], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=OBS_COLUMNS)
        w.writeheader()
        w.writerows(rows)
        f.flush()
        os.fsync(f.fileno())


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def publish_file(staged: Path, dest_dir: Path, provider: str, run_id: str) -> Path:
    """Atomically publish a fully validated batch as an immutable, never-overwritten `<provider>_<run_id>.csv`.

    The batch is copied beside its destination under a name the store never loads, then renamed into place:
    a reader sees either no publication or the whole publication."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    final, part = dest_dir / f"{provider}_{run_id}.csv", dest_dir / f".{provider}_{run_id}.csv.part"
    if final.exists():
        raise ProviderFailure("MALFORMED_RESULT", f"{final.name} already exists; publications are append-only")
    try:
        shutil.copyfile(staged, part)
        with part.open("r+b") as f:                       # durable before it becomes visible
            f.flush()
            os.fsync(f.fileno())
        os.replace(part, final)
    finally:
        part.unlink(missing_ok=True)
    return final


def _is_active_row(row: dict, metric: Metric | None, at) -> bool:
    """A row is active if its metric is not routed, or its (source, series_key) is the route active at `at`."""
    if metric is None or not metric.routed:
        return True
    route = route_at(metric, at)
    return (provider_of(row["source"]), row["source_code"]) == (route.provider, route.series_key)


def route_states(metrics: dict[str, Metric], metric_ids, at) -> dict[str, dict]:
    """Per routed metric, the route active at `at`: recorded in the publication manifest."""
    out = {}
    for mid in sorted(set(metric_ids)):
        m = metrics.get(mid)
        change = route_change_at(m, at) if m is not None else None
        if change is not None:
            route = route_at(m, at)
            out[mid] = {"provider": route.provider, "series_key": route.series_key, "effective_at": change.effective_at}
    return out


def publish(rows: list[dict], metrics: dict[str, Metric], provider: str, run_id: str, *, root: Path | str,
            stage_dir: Path, at: str, started_at: str) -> dict:
    """Split a validated batch by route state at `at` and publish it: rows of the route active at `at` go to
    observations/, all others to candidates/. Both files are written atomically and append-only, the candidates
    file first so an anchor never exists without its companion.

    ROUTE_BACKFILL_AFTER_ACTIVATION: a row published as active must have been retrieved inside this run's own
    [started_at, at] window; a row can therefore never be back-dated into an information set already diagnosed."""
    root = Path(root)
    active = [r for r in rows if _is_active_row(r, metrics.get(r["metric_id"]), at)]
    candidates = [r for r in rows if not _is_active_row(r, metrics.get(r["metric_id"]), at)]
    lo, hi = utc_naive(started_at), utc_naive(at)
    for r in active:
        m = metrics.get(r["metric_id"])
        if m is not None and m.routed and not lo <= utc_naive(r["retrieved_at"]) <= hi:
            raise ProviderFailure("ROUTE_BACKFILL_AFTER_ACTIVATION",
                                  f"{r['metric_id']}@{r['reference_period']} was retrieved outside this run's window")
    out: dict = {"observations": None, "candidates": None,
                 "route_states": route_states(metrics, [r["metric_id"] for r in rows], at)}
    for kind, part, dest, stage_name in (("candidates", candidates, CAND_DIR, "normalized.candidates.tmp.csv"),
                                         ("observations", active, OBS_DIR, "normalized.tmp.csv")):
        if not part:
            continue
        staged = stage_dir / stage_name
        write_rows(part, staged)
        final = publish_file(staged, root / dest, provider, run_id)
        staged.unlink(missing_ok=True)
        out[kind] = {"file": (dest / final.name).as_posix(), "rows": len(part), "sha256": sha256_file(final)}
    return out


# ---------------------------------------------------------------- route selection: before as_of
def select_active(obs: pd.DataFrame, metrics: dict[str, Metric], at) -> pd.DataFrame:
    """For every ROUTED metric, keep only the rows of the route active at `at`: (source, source_code) equal to
    route_at(metric, at)'s (provider, series_key). Metrics that are not routed pass through untouched.

    This must run BEFORE `store.as_of`: as_of keeps one row per (metric, period), the latest retrieved, whatever its
    source, so an inactive or candidate provider retrieved later would silently displace the active one."""
    if obs.empty:
        return obs
    t = utc_naive(at)
    src = obs["source"].astype(str).str.strip().str.lower()
    code = obs["source_code"].astype(str)
    keep = pd.Series(True, index=obs.index)
    for mid in obs["metric_id"].unique():
        m = metrics.get(mid)
        if m is None or not m.routed:
            continue
        route = route_at(m, t)
        mine = obs["metric_id"] == mid
        keep &= ~mine | ((src == route.provider) & (code == route.series_key))
    return obs[keep]


def as_of_routed(obs: pd.DataFrame, metrics: dict[str, Metric], when) -> pd.DataFrame:
    """The information set at `when`: route filter first, then store.as_of. Use wherever private rows are combined."""
    return as_of(select_active(obs, metrics, when), when)
