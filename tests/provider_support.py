"""Synthetic provider routes for the V1.2.1 core tests. Nothing here is provider data and no second provider exists:
`altprov` is a stand-in with made-up series keys, so the core can be shown to be provider-blind before any adapter lands."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import yaml

ALT = "altprov"
ROUTED = "cn_dr007"                      # the metric the tests route to a second provider
DICT_REL = "data/dictionary/metrics.yaml"


def access(automated="permitted", manual="permitted", private="permitted", basis="synthetic test policy") -> dict:
    return {"automated_retrieval": automated, "manual_import": manual, "private_use": private,
            "redistribution": "prohibited", "basis": basis}


def wind_route(code: str) -> dict:
    return {"provider": "wind", "series_key": code, "equivalence": "EXACT", "equivalence_basis": "incumbent",
            "validation": "PASSED", "validation_basis": "incumbent", "access": access("permitted", "prohibited"),
            "expected": {"name": "DR007", "freq": "D", "unit": "%"}}


NO_METADATA = [{"field": f, "reason": "synthetic provider: it supplies no metadata"} for f in ("name", "freq", "unit")]


def alt_route(metric_id: str = ROUTED, **changes) -> dict:
    return {"provider": ALT, "series_key": f"{ALT.upper()}:{metric_id}", "equivalence": "EXACT",
            "equivalence_basis": "synthetic: the same statistic by construction", "validation": "PASSED",
            "validation_basis": "synthetic: every period compared", "access": access(), "collect": True,
            "known_gaps": NO_METADATA, **changes}


def read(path: Path) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def write(path: Path, raw: dict) -> None:
    Path(path).write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")


def entry(raw: dict, metric_id: str = ROUTED) -> dict:
    return next(e for e in raw["metrics"] if e["metric_id"] == metric_id)


def wind_route_for(e: dict) -> dict:
    """The explicit form of the incumbent route the loader would synthesize from this entry's `wind:` block."""
    w = e["wind"]
    r = wind_route(w["code"])
    r["expected"] = {k: w[f"expected_{k}"] for k in ("name", "freq", "unit") if w.get(f"expected_{k}") is not None}
    r["known_gaps"] = list(w.get("known_gaps") or [])
    for k in ("aggregate", "same_series_as"):
        if w.get(k) is not None:
            r[k] = w[k]
    return r


def route_metric(path: Path, metric_id: str, *, activate_at: str | None = None, alt: dict | None = None) -> dict:
    """Give a Wind metric explicit `sources` (Wind and `altprov`) and a history that starts on Wind. With `activate_at`,
    the history also carries the record that makes `altprov` authoritative from then. Returns the raw dictionary."""
    raw = read(path)
    e = entry(raw, metric_id)
    e["sources"] = [wind_route_for(e), alt or alt_route(metric_id)]
    e["route_history"] = [{"effective_at": "genesis", "active": "wind", "decision": "genesis: the incumbent route"}]
    if activate_at:
        e["route_history"].append({"effective_at": activate_at, "active": ALT, "decision": "synthetic reviewed change"})
    write(path, raw)
    return raw


def route_cn_dr007(path: Path, *, activate_at: str | None = None, alt: dict | None = None) -> dict:
    """`route_metric` for cn_dr007, the metric the tests route to a second provider."""
    return route_metric(path, ROUTED, activate_at=activate_at, alt=alt)


def append_activation(path: Path, effective_at: str, active: str = ALT, decision: str = "synthetic reviewed change") -> None:
    raw = read(path)
    entry(raw)["route_history"].append({"effective_at": effective_at, "active": active, "decision": decision})
    write(path, raw)


def edited(path: Path, fn, metric_id: str = ROUTED) -> None:
    """Apply `fn(entry)` to one metric's entry (default cn_dr007) in the dictionary file."""
    raw = read(path)
    fn(entry(raw, metric_id))
    write(path, raw)


# ---------------------------------------------------------------- a throwaway git repository
def git(repo: Path, *args: str) -> str:
    env = {k: v for k, v in os.environ.items() if k not in {"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"}}
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false",
                           *args], cwd=repo, env=env, capture_output=True, text=True, check=True).stdout.strip()


def init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    git(repo, "init", "-q")


def commit_dictionary(repo: Path, message: str) -> None:
    git(repo, "add", DICT_REL)
    git(repo, "commit", "-q", "-m", message)
