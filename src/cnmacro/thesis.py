"""Thesis state: immutable preregistered baseline + append-only amendments and updates.

    preregistered/<date>-baseline.yaml      written once, never edited
    preregistered/<date>-amendment-NN-*.yaml pre-release corrections to the frozen case
                                            definition; written once, never edited
    updates/<date>-<release>.yaml            one per release, never edited
    current state                            folded from these, never stored by hand
"""
from __future__ import annotations

import copy
from pathlib import Path

import yaml

STATUSES = {"ACTIVE", "CONFIRMED", "FALSIFIED", "RETIRED"}
CONVICTIONS = {"LOW", "MEDIUM", "HIGH"}
DIRECTIONS = {"STRENGTHENED", "UNCHANGED", "WEAKENED"}
PROB_STEP = 0.05


def load_yaml(p: str | Path) -> dict:
    return yaml.safe_load(Path(p).read_text(encoding="utf-8"))


def case_files(case_dir: str | Path) -> tuple[Path, list[Path]]:
    case_dir = Path(case_dir)
    baselines = sorted((case_dir / "preregistered").glob("*-baseline.yaml"))
    if not baselines:
        raise FileNotFoundError("no preregistered baseline")
    updates = sorted((case_dir / "updates").glob("*.yaml"))
    return baselines[0], updates


def amendment_files(case_dir: str | Path) -> list[Path]:
    return sorted((Path(case_dir) / "preregistered").glob("*-amendment-*.yaml"))


AMENDABLE = ("terminal_rules", "horizon")  # amendments may correct decision logic, never evidence or judgment


def _get_path(d: dict, dotted: str):
    for k in dotted.split("."):
        d = d.get(k) if isinstance(d, dict) else None
    return d


def _set_path(d: dict, dotted: str, value) -> None:
    *head, last = dotted.split(".")
    for k in head:
        d = d.setdefault(k, {})
    d[last] = value


def apply_amendments(case: dict, amendments: list[tuple[str, dict]], baseline_file: str) -> tuple[dict, list[str]]:
    """Frozen case + amendments, in file order. Each change must state the exact `before`
    value it replaces, so an amendment cannot silently rewrite anything else."""
    case, errs = copy.deepcopy(case), []
    for name, a in amendments:
        if a.get("kind") != "amendment":
            errs.append(f"{name}: kind must be 'amendment'")
            continue
        if a.get("baseline") != baseline_file:
            errs.append(f"{name}: amends {a.get('baseline')}, not {baseline_file}")
        if a.get("informed_by_tested_data") is not False:
            errs.append(f"{name}: must declare informed_by_tested_data: false")
        for k in ("id", "reason", "baseline_commit", "effective_before"):
            if not a.get(k):
                errs.append(f"{name}: missing {k}")
        for ch in a.get("changes", []):
            path = ch.get("path", "")
            if path.split(".")[0] not in AMENDABLE:
                errs.append(f"{name}: may not change '{path}' (amendable: {', '.join(AMENDABLE)})")
                continue
            if _get_path(case, path) != ch.get("before"):
                errs.append(f"{name}: '{path}' before-value does not match the frozen case")
                continue
            _set_path(case, path, ch.get("after"))
    return case, errs


def effective_case(case_dir: str | Path) -> tuple[dict, list[dict], list[str]]:
    """(case definition in force, amendment docs, errors): the baseline's frozen case plus amendments."""
    base_path, _ = case_files(case_dir)
    base = load_yaml(base_path)
    docs = [(p.name, load_yaml(p)) for p in amendment_files(case_dir)]
    case, errs = apply_amendments(base["case"], docs, base_path.name)
    return case, [{**d, "_file": n} for n, d in docs], errs


def on_grid(p: float) -> bool:
    return abs(round(p / PROB_STEP) * PROB_STEP - p) < 1e-9 and 0 <= p <= 1


def validate_state_fields(d: dict, where: str) -> list[str]:
    errs = []
    if d.get("status") not in STATUSES:
        errs.append(f"{where}: bad status {d.get('status')}")
    if d.get("conviction") not in CONVICTIONS:
        errs.append(f"{where}: bad conviction {d.get('conviction')}")
    if d.get("last_update_direction") not in DIRECTIONS:
        errs.append(f"{where}: bad last_update_direction")
    if not on_grid(float(d.get("probability", -1))):
        errs.append(f"{where}: probability must be in [0,1] on a {PROB_STEP} grid")
    return errs


def validate_update(u: dict, prev: dict, where: str) -> list[str]:
    """Probability never changes silently: every change must be fully explained."""
    errs = validate_state_fields(u, where)
    pc = u.get("probability_change")
    if float(u["probability"]) != float(prev["probability"]):
        if not pc:
            errs.append(f"{where}: probability changed without probability_change block")
        else:
            for k in ("previous", "new", "evidence", "hypotheses", "reasoning"):
                if not pc.get(k):
                    errs.append(f"{where}: probability_change.{k} missing")
            if pc and float(pc.get("previous", -1)) != float(prev["probability"]):
                errs.append(f"{where}: probability_change.previous != prior state")
            if pc and float(pc.get("new", -1)) != float(u["probability"]):
                errs.append(f"{where}: probability_change.new != probability")
    if u.get("status") in {"CONFIRMED", "FALSIFIED"} and not u.get("terminal_rule_fired"):
        errs.append(f"{where}: terminal status requires terminal_rule_fired from the preregistered rules")
    if u.get("baseline") != prev.get("_baseline_file"):
        errs.append(f"{where}: baseline pointer {u.get('baseline')} != {prev.get('_baseline_file')}")
    return errs


def fold(case_dir: str | Path) -> tuple[dict, list[dict], list[str]]:
    """Return (current_state, history, errors)."""
    base_path, update_paths = case_files(case_dir)
    base = load_yaml(base_path)
    state = {k: base[k] for k in ("probability", "conviction", "status", "last_update_direction")}
    state["as_of"] = base["as_of"]
    state["_baseline_file"] = base_path.name
    errs = validate_state_fields(base, base_path.name)
    history = [{"kind": "baseline", "file": base_path.name, **state}]
    _, amendments, amend_errs = effective_case(case_dir)
    errs += amend_errs
    for a in amendments:
        history.append({"kind": "amendment", "file": a["_file"], "as_of": str(a.get("date")), "id": a.get("id"),
                        "title": a.get("title"), **{k: state[k] for k in
                        ("probability", "conviction", "status", "last_update_direction")}})
    for p in update_paths:
        u = load_yaml(p)
        errs += validate_update(u, state, p.name)
        state = {**state, **{k: u[k] for k in ("probability", "conviction", "status", "last_update_direction")},
                 "as_of": u["as_of"]}
        history.append({"kind": "update", "file": p.name, **{k: u.get(k) for k in
                        ("as_of", "release", "probability", "conviction", "status", "last_update_direction")}})
    return state, history, errs
