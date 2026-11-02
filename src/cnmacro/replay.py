"""Historical replay of the release-update path, in a sandbox.

    cnmacro replay --release-at 2026-08-09 --out /tmp/replay

Proves end to end, on real already-published data, that
    old as-of state -> new observations arrive -> evidence tests recompute
    -> flipped tests are detected -> refresh record is produced -> eval passes -> site rebuilds
and that re-running the refresh afterwards is a no-op.

The sandbox is a separate directory. It never touches the live case, its preregistered
baseline, its updates or the public observation store, and every page of its site carries
a REPLAY banner. Only observations with an official release date take part (their
availability in the past is known); series without one are left out of the sandbox, and so
are the evidence tests that need them. Inputs are frozen by --data-cutoff (rows retrieved
after it are ignored) so the replay gives the same answer however the store grows.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pandas as pd
import yaml

from .refresh import Paths, evaluate, refresh_public
from .store import OBS_COLUMNS, load_dictionary, load_observations, release_time, utc_naive
from .thesis import effective_case

BANNER = ("REPLAY: a historical simulation of the release-update path on already-published data. "
          "Not a live update and not part of the preregistered record.")


def _dated(obs: pd.DataFrame, cutoff: str) -> pd.DataFrame:
    d = obs[(obs.release_date != "") & (obs.retrieved_at.map(utc_naive) <= utc_naive(cutoff))].copy()
    d["avail_t"] = d.release_date.map(release_time)
    return d.sort_values("retrieved_at").drop_duplicates(["metric_id", "reference_period"], keep="last")


def _rows(df: pd.DataFrame, retrieved_at) -> list[dict]:
    out = []
    for r in df.itertuples():
        row = {c: getattr(r, c) for c in OBS_COLUMNS}
        row["retrieved_at"] = retrieved_at if isinstance(retrieved_at, str) else retrieved_at(r)
        row["consensus"] = "" if pd.isna(row["consensus"]) else row["consensus"]
        out.append(row)
    return out


def replay(release_at: str, out: Path, root: Path = Path("."), data_cutoff: str = "2026-10-04T23:59:59Z",
           before_minutes: int = 60, after_hours: int = 12, log=print) -> dict:
    """Replay the official release(s) on `release_at` (a Beijing date, or an exact time)."""
    root, out = Path(root), Path(out)
    if out.exists():
        shutil.rmtree(out)
    paths = Paths(root=out, case_dir=out / "case", obs_dir=out / "observations",
                  dictionary=out / "dictionary.yaml", calendar=out / "calendar.yaml", site_out=out / "site")
    live = Paths.default(root)
    dated = _dated(load_observations(live.obs_dir), data_cutoff)

    t_rel = release_time(release_at)
    t0 = (t_rel - pd.Timedelta(minutes=before_minutes)).isoformat() + "Z"
    t1 = (t_rel + pd.Timedelta(hours=after_hours)).isoformat() + "Z"
    # sandbox dictionary, case and calendar: only series whose release dates are known and
    # that already had history at t0
    kept = sorted(set(dated[dated.avail_t <= utc_naive(t0)].metric_id))
    dated = dated[dated.metric_id.isin(kept)]
    arriving = dated[(dated.avail_t > utc_naive(t0)) & (dated.avail_t <= utc_naive(t1))]
    if arriving.empty:
        raise ValueError(f"no dated observation was released between {t0} and {t1}")
    raw = yaml.safe_load(live.dictionary.read_text(encoding="utf-8"))
    paths.dictionary.parent.mkdir(parents=True, exist_ok=True)
    paths.dictionary.write_text(yaml.safe_dump({"metrics": [m for m in raw["metrics"] if m["metric_id"] in kept]},
                                               sort_keys=False, allow_unicode=True), encoding="utf-8")
    metrics = load_dictionary(paths.dictionary)
    case, _, _ = effective_case(live.case_dir)

    from .derive import parse_drv
    from .evidence import load_tests

    def uses(t):
        if "(" not in t.indicator:
            return {t.indicator}
        return {x for x in parse_drv(t.indicator)[1] if not x.lstrip("-").isdigit()}
    tests = load_tests(case["evidence_tests"])
    dropped = [t.id for t in tests if not uses(t) <= set(kept)]
    case = {**case, "evidence_tests": [t for t in case["evidence_tests"] if t["id"] not in dropped]}
    cal = [{"name": f"{mid} {p} (official release date)", "period": p, "release": str(rd),
            "metrics": [mid]} for mid, p, rd in dated[["metric_id", "reference_period", "release_date"]].itertuples(index=False)]
    paths.calendar.write_text(yaml.safe_dump({"releases": cal}, sort_keys=False, allow_unicode=True), encoding="utf-8")

    # the store as it stood at t0: each row retrieved when it was released
    held = dated[dated.avail_t <= utc_naive(t0)]
    paths.obs_dir.mkdir(parents=True)
    pd.DataFrame(_rows(held, lambda r: r.avail_t.isoformat() + "Z"), columns=OBS_COLUMNS).to_csv(
        paths.obs_dir / "replay_store.csv", index=False)

    # a sandbox baseline at t0, carrying the live judgment and the case in force
    live_base = yaml.safe_load(sorted((live.case_dir / "preregistered").glob("*-baseline.yaml"))[0].read_text(encoding="utf-8"))
    obs0 = load_observations(paths.obs_dir)
    res0, term0 = evaluate(obs0, metrics, case, t0)
    (paths.case_dir / "preregistered").mkdir(parents=True)
    (paths.case_dir / "case.yaml").write_text(yaml.safe_dump(case, sort_keys=False, allow_unicode=True), encoding="utf-8")
    base = {"kind": "baseline", "replay": True, "as_of": t0, "committed_before": None,
            **{k: live_base[k] for k in ("probability", "conviction", "status", "last_update_direction",
                                          "rationale", "hypothesis_assessment")},
            "key_claims": [], "test_results": {k: v.__dict__ for k, v in res0.items()},
            "terminal_status_at_baseline": term0["status"], "case": case}
    (paths.case_dir / "preregistered" / f"{t0[:10]}-baseline.yaml").write_text(
        yaml.safe_dump(base, sort_keys=False, allow_unicode=True), encoding="utf-8")

    # the fetcher sees what the official source would serve at t1: everything released by then
    def fetcher(route, ms, held_periods, mets, calendar, got):
        ids = {m.metric_id for m in ms}
        avail = dated[(dated.metric_id.isin(ids)) & (dated.avail_t <= utc_naive(t1))]
        return {"replay_store.csv": _rows(avail, got)}

    log(f"replay: {len(arriving)} observations released between {t0} and {t1}")
    first = refresh_public(paths, now=t1, fetcher=fetcher, use_agenda=False, banner=BANNER, log=log)
    second = refresh_public(paths, now=t1, fetcher=fetcher, use_agenda=False, build=False, log=log)
    record = json.loads(Path(first.record).read_text(encoding="utf-8")) if first.record else {}
    report = {
        "kind": "replay", "release_at": release_at, "before": t0, "after": t1, "data_cutoff": data_cutoff,
        "sandbox": str(out), "series_in_sandbox": kept, "tests_left_out": dropped,
        "arrived": sorted(f"{m}@{p}" for m, p in arriving[["metric_id", "reference_period"]].itertuples(index=False)),
        "refresh": {"status": first.status, "new_rows": first.new_rows, "record": first.record,
                    "flipped": [f["test"] for f in first.flipped], "eval": first.eval_status},
        "terminal": record.get("terminal"),
        "rerun": {"status": second.status, "new_rows": second.new_rows, "record": second.record},
        # every page, as a path under the site: {en,zh}/<page>.html plus the root selector and legacy redirects
        "site_pages": sorted(p.relative_to(out / "site").as_posix() for p in (out / "site").rglob("*.html")),
    }
    (out / "replay-report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report
