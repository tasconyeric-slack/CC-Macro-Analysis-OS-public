"""Deterministic eval gate. Runs before research generation and on every build.

    E0 data quality        schema, duplicates, missing values, provenance
    E1 citation integrity  every claim value matches the data as of the claim date
    E2 derived lineage     every derived value recomputes from existing observations
    E3 as-of leakage       nothing cited was unavailable at the artifact's as-of time
    E4 preregistration     baseline and updates are append-only in git history (or in the origin
                           repository's, via origin_history.json); so is every route history
    E5 thesis discipline   probability grid, explained changes, terminal rules only

An LLM rubric on research method may be added as a secondary signal; it never
replaces these checks.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

import pandas as pd

from .claims import LOCALES, Claim, validate_claim
from .derive import REF_RE, Deriver, parse_drv
from .normalize import as_of_routed
from .store import (GENESIS, OBS_COLUMNS, REQUIRED, SOURCE_CLASSES, Metric, RouteChange, _change,
                    to_period)
from .thesis import fold

PERIOD_RE = {"M": re.compile(r"^\d{4}-\d{2}$"), "Q": re.compile(r"^\d{4}Q[1-4]$"),
             "D": re.compile(r"^\d{4}-\d{2}-\d{2}$")}


@dataclass
class Check:
    id: str
    name: str
    status: str = "pass"      # pass | warn | fail
    details: list[str] = field(default_factory=list)

    def fail(self, msg):
        self.status = "fail"
        self.details.append(msg)

    def warn(self, msg):
        if self.status == "pass":
            self.status = "warn"
        self.details.append(msg)


def data_quality(obs: pd.DataFrame, metrics: dict[str, Metric], public_only: bool = False) -> Check:
    """In public mode, metrics that are not publicly redistributable are expected to be absent."""
    c = Check("E0", "Data quality")
    missing_cols = [col for col in OBS_COLUMNS if col not in obs.columns]
    if missing_cols:
        c.fail(f"missing columns {missing_cols}")
        return c
    for col in REQUIRED:
        blank = obs[obs[col].isna() | (obs[col].astype(str) == "")]
        for _, r in blank.iterrows():
            c.fail(f"{r['_file']}: {r['metric_id']}@{r['reference_period']} missing {col}")
    bad_cls = obs[~obs["source_class"].isin(SOURCE_CLASSES)]
    for _, r in bad_cls.iterrows():
        c.fail(f"{r['metric_id']}@{r['reference_period']}: source_class '{r['source_class']}'")
    unknown = sorted(set(obs["metric_id"]) - set(metrics))
    if unknown:
        c.fail(f"metrics not in dictionary: {unknown}")
    dup = obs[obs.duplicated(["metric_id", "reference_period", "retrieved_at"], keep=False)]
    if not dup.empty:
        c.fail(f"{len(dup)} duplicate rows (metric, period, retrieved_at)")
    for _, r in obs.iterrows():
        m = metrics.get(r["metric_id"])
        if m and not PERIOD_RE[m.frequency].match(str(r["reference_period"])):
            c.fail(f"{r['metric_id']}: period '{r['reference_period']}' does not match frequency {m.frequency}")
        if not r["release_date"] and not r["limitation"]:
            c.fail(f"{r['metric_id']}@{r['reference_period']}: release_date unknown and no limitation recorded")
    for mid, m in metrics.items():
        if public_only and m.tier == "supplemental":
            continue  # private diagnostics sit outside the public build; the public report never names them
        sub = obs[obs["metric_id"] == mid]
        if sub.empty:
            if public_only and m.redistribution != "public":
                c.details.append(f"{mid}: not in public build ({m.redistribution}); private mode only")
            else:
                (c.fail if m.tier == "core" else c.warn)(f"{mid}: no observations")
            continue
        if m.frequency in ("M", "Q"):
            ps = sorted({to_period(p, m.frequency) for p in sub["reference_period"]
                         if PERIOD_RE[m.frequency].match(p)})
            if ps:
                full = pd.period_range(ps[0], ps[-1], freq=ps[0].freq)
                gaps = [str(p) for p in full if p not in set(ps)]
                # January (and February, for single-month series) is absent under Jan-Feb combined releases
                skip = ("-01", "-02") if m.jan_feb_combined else ("-01",)
                gaps = [g for g in gaps if not (m.frequency == "M" and g.endswith(skip))]
                if gaps:
                    c.warn(f"{mid}: {len(gaps)} gap(s), e.g. {gaps[:3]}")
    return c


def lint_memo(path: Path, c: "Check", claim_ids: set[str], locale: str = "en") -> None:
    """A memo template may not contain bare numbers and may only cite known claims."""
    from .claims import bare_numbers
    if not path.exists():
        return
    text = re.sub(r"\{#.*?#\}", "", path.read_text(encoding="utf-8"), flags=re.S)
    for cid in re.findall(r'c\("([^"]+)"\)', text):
        if cid not in claim_ids:
            c.fail(f"{path.name}: cites unknown claim {cid}")
    body = re.sub(r"\{#.*?#\}|\{\{.*?\}\}|\{%.*?%\}", "", text, flags=re.S)
    for i, line in enumerate(body.splitlines(), 1):
        for n in bare_numbers(line, locale):
            c.fail(f"{path.name}:{i}: bare number '{n}'")


def lint_presentation(path: Path, c: "Check") -> None:
    """Research prose in the presentation layer follows the memo rule: figures come from bound
    claims or policy-event figures, never from typing. Applies to every {en, zh} text pair."""
    import yaml
    from .claims import bare_numbers
    if not path.exists():
        return
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    def walk(node, where):
        if isinstance(node, dict):
            for k, v in node.items():
                if k in ("en", "zh") and isinstance(v, str):
                    for n in bare_numbers(v, k):
                        c.fail(f"{path.name}:{where}.{k}: bare number '{n}'")
                else:
                    walk(v, f"{where}.{k}" if where else str(k))
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{where}[{i}]")
    walk(doc, "")


def citation_integrity(claims: list[Claim], obs: pd.DataFrame, metrics, tol: float = 0.051,
                       memo: Path | dict[str, Path] | None = None,
                       presentation: Path | list[Path] | None = None) -> Check:
    """`memo` is one template (English) or {locale: template}; `presentation` the research-prose files."""
    c = Check("E1", "Citation integrity")
    memos = memo if isinstance(memo, dict) else ({"en": memo} if memo is not None else {})
    for loc, path in memos.items():
        lint_memo(path, c, {cl.id for cl in claims}, loc)
    for prose in ([] if presentation is None else presentation if isinstance(presentation, list) else [presentation]):
        lint_presentation(prose, c)
    ids = {cl.id for cl in claims}
    for cl in claims:
        for e in validate_claim(cl):
            c.fail(e)
        for s in cl.supports:
            if s not in ids:
                c.fail(f"{cl.id}: supports unknown claim {s}")
        d = Deriver(as_of_routed(obs, metrics, cl.as_of), metrics)
        for name, b in cl.values.items():
            try:
                pt = d.resolve(b.ref)
            except (KeyError, ValueError) as ex:
                c.fail(f"{cl.id}.{name}: cannot resolve {b.ref} ({ex})")
                continue
            if pt is None:
                c.fail(f"{cl.id}.{name}: {b.ref} not found as of {cl.as_of}")
            elif b.recorded is None:
                c.fail(f"{cl.id}.{name}: value not recorded (run fill)")
            elif abs(pt.value - b.recorded) > tol:
                c.fail(f"{cl.id}.{name}: recorded {b.recorded} != data {pt.value:.3f} ({b.ref})")
        for r in cl.refs:
            if d.resolve(r) is None:
                c.fail(f"{cl.id}: ref {r} not found as of {cl.as_of}")
    return c


def derived_lineage(claims: list[Claim], obs: pd.DataFrame, metrics) -> Check:
    c = Check("E2", "Derived calculation lineage")
    for cl in claims:
        d = Deriver(as_of_routed(obs, metrics, cl.as_of), metrics)
        for r in cl.all_refs():
            if not r.startswith("drv:"):
                continue
            body = REF_RE.match(r).group(2)
            fn, args = parse_drv(body)
            for a in args:
                if a not in metrics and not a.lstrip("-").isdigit():
                    c.fail(f"{cl.id}: {r} uses unknown input {a}")
            pt = d.resolve(r)
            if pt is None:
                continue  # reported by E1
            if not pt.inputs:
                c.fail(f"{cl.id}: {r} has no recorded inputs")
            for inp in pt.inputs:
                if d.resolve(inp) is None:
                    c.fail(f"{cl.id}: {r} input {inp} not resolvable")
    return c


def asof_leakage(claims: list[Claim], obs: pd.DataFrame, metrics) -> Check:
    """A ref that resolves on the full store but not on the as-of store is a leak."""
    c = Check("E3", "As-of leakage")
    full = Deriver(as_of_routed(obs, metrics, "2262-01-01"), metrics)
    for cl in claims:
        d = Deriver(as_of_routed(obs, metrics, cl.as_of), metrics)
        for r in cl.all_refs():
            try:
                if d.resolve(r) is None and full.resolve(r) is not None:
                    c.fail(f"{cl.id} (as of {cl.as_of}) cites {r}, not available until later")
            except (KeyError, ValueError):
                pass
    return c


def git_history(path: Path) -> list[str]:
    """Commits that touched `path`, newest first, following renames. `--follow` also detects copies, and a new
    refresh record resembles the previous one closely enough to be reported as its copy (C051 on 2026-10-14),
    which would lend the new file the old file's commit; a copy is where this path's history begins."""
    try:
        out = subprocess.check_output(["git", "log", "--format=%x00%H", "--name-status", "--follow", "--", str(path)],
                                      text=True, stderr=subprocess.DEVNULL)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    commits = []
    for block in out.split("\0")[1:]:
        sha, _, changes = block.partition("\n")
        commits.append(sha.strip())
        if changes.strip().startswith("C"):
            break
    return commits


ORIGIN_HISTORY = "origin_history.json"


def origin_history(case_dir: Path) -> dict:
    """The origin-history anchor (scripts/origin_history.py): first commits, in the private origin repository, of the
    research files this repository's one-commit snapshot carried over. Empty when the case has no anchor."""
    import json
    f = case_dir / ORIGIN_HISTORY
    if not f.exists():
        return {}
    return json.loads(f.read_text(encoding="utf-8"))


def _git_path(f: Path) -> str:
    try:
        return subprocess.check_output(["git", "ls-files", "--full-name", "--", str(f)], text=True,
                                       stderr=subprocess.DEVNULL).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def _blob(f: Path) -> str:
    try:
        return subprocess.check_output(["git", "hash-object", "--", str(f)], text=True, stderr=subprocess.DEVNULL).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def commit_time(sha: str, anchor: dict | None = None) -> pd.Timestamp | None:
    """Commit time of `sha`, from this repository's history, else from the origin-history anchor."""
    at = (anchor or {}).get("commits", {}).get(sha)
    if at is None and anchor and sha:
        at = next((v for k, v in anchor.get("commits", {}).items() if k.startswith(sha)), None)
    if at is not None:
        return pd.Timestamp(at).tz_convert("UTC").tz_localize(None)
    try:
        out = subprocess.check_output(["git", "show", "-s", "--format=%cI", sha], text=True,
                                      stderr=subprocess.DEVNULL).strip()
        return pd.Timestamp(out).tz_convert("UTC").tz_localize(None)
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError):
        return None


# ---------------------------------------------------------------- route history: append-only across versions
DICTIONARY = Path("data/dictionary/metrics.yaml")


IDENTITY_FIELDS = ("provider", "series_key", "equivalence", "aggregate")


class Routing(NamedTuple):
    """What one version of the dictionary says about a metric's routing."""
    records: list[RouteChange]          # the route history
    implicit: bool                      # the genesis record is synthesized: a `wind:` metric with no explicit history
    identities: dict[str, tuple | None]  # per route the history names: IDENTITY_FIELDS values, None if not declared


def _routing_of(entry: dict) -> Routing:
    """The route history of one raw dictionary entry: its explicit `route_history`; or, for a `wind:` metric without
    one, the synthesized genesis record (implicit: it has no `decision` text to compare); or nothing. With it, the
    identity of every route the history names. That is what a record means: `provider` alone would let a later edit
    to `series_key`, `equivalence` or `aggregate` change an old record's meaning while the record itself stayed put.
    Access, bases, expected metadata, known gaps and params are documentation or present-tense policy, not identity."""
    declared: dict[str, tuple] = {}
    for r in entry.get("sources") or []:
        if isinstance(r, dict) and r.get("provider") is not None:
            declared[str(r["provider"])] = (str(r["provider"]), r.get("series_key"), r.get("equivalence"), r.get("aggregate"))
    w = entry.get("wind")
    if isinstance(w, dict) and not entry.get("sources"):         # the compatibility shim: the incumbent route, only while
        declared["wind"] = ("wind", w.get("code"), "EXACT", w.get("aggregate"))     # nothing declares routes explicitly
    if entry.get("route_history"):
        records, implicit = [_change(c) for c in entry["route_history"]], False
    elif w or entry.get("sources"):
        records, implicit = [RouteChange(GENESIS, "wind")], True
    else:
        return Routing([], False, {})
    return Routing(records, implicit, {p: declared.get(p) for p in dict.fromkeys(c.active for c in records)})


def _histories(text: str) -> dict[str, Routing]:
    import yaml
    raw = yaml.safe_load(text) or {}
    return {e["metric_id"]: _routing_of(e) for e in raw.get("metrics") or [] if isinstance(e, dict) and "metric_id" in e}


def identity_change(old: tuple | None, new: tuple | None) -> str | None:
    """Which identity fields differ between two versions of a named route, or None."""
    if old == new:
        return None
    if new is None:
        return "the route is no longer declared"
    return ", ".join(f"{f} {o!r} -> {n!r}" for f, o, n in zip(IDENTITY_FIELDS, old, new) if o != n)


def history_rewrite(old: Routing, new: Routing) -> str | None:
    """Why `new` is not an append-only extension of `old`, or None. Every earlier record must survive unchanged and in
    order; only new records at the end are allowed. (A `decision` is compared only where the older record had one.)"""
    old_recs, old_implicit = old.records, old.implicit
    new_recs = new.records
    if len(new_recs) < len(old_recs):
        return f"{len(old_recs) - len(new_recs)} earlier record(s) removed"
    for i, (o, n) in enumerate(zip(old_recs, new_recs)):
        if (o.effective_at, o.active) != (n.effective_at, n.active):
            return f"record {i} changed from ({o.effective_at}, {o.active}) to ({n.effective_at}, {n.active})"
        if not (old_implicit and i == 0) and o.decision != n.decision:
            return f"record {i} ({o.effective_at}, {o.active}): its decision reference was edited"
    return None


def route_history_audit(dictionary: Path = DICTIONARY) -> tuple[list[str], list[str]]:
    """(violations, notes). Walks every committed version of the dictionary, oldest first, then the working copy,
    and requires each metric's route history to be an append-only extension of the one before. A single YAML file
    can show only that its own history is well formed; this is what shows it was never rewritten between commits
    (and it catches a rewrite that contradicts no stored ResearchRun, which the retroactivity guard cannot)."""
    dictionary = Path(dictionary)
    try:
        top = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], cwd=dictionary.parent, text=True,
                                           stderr=subprocess.DEVNULL).strip()).resolve()
        rel = dictionary.resolve().relative_to(top).as_posix()
        shas = subprocess.check_output(["git", "log", "--reverse", "--format=%H", "--", rel], cwd=top, text=True,
                                       stderr=subprocess.DEVNULL).split()
        versions = [(sha[:10], subprocess.check_output(["git", "show", f"{sha}:{rel}"], cwd=top, text=True,
                                                       encoding="utf-8", stderr=subprocess.DEVNULL)) for sha in shas]
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError):
        return [], [f"{dictionary.as_posix()} has no git history here; route-history append-only is not verified"]
    if dictionary.exists():
        versions.append(("working copy", dictionary.read_text(encoding="utf-8")))
    shallow = subprocess.run(["git", "rev-parse", "--is-shallow-repository"], cwd=top, text=True, capture_output=True).stdout.strip()
    notes = ["shallow clone: only the visible commits were audited"] if shallow == "true" else []
    violations, prev, prev_label = [], None, ""
    named: dict[str, dict[str, tuple[tuple | None, str]]] = {}   # metric -> route -> (identity, version that first named it)
    for label, text in versions:
        try:
            cur = _histories(text)
        except Exception as ex:                                  # an unparsable old version proves nothing either way
            notes.append(f"{label}: dictionary not readable ({type(ex).__name__}); skipped")
            continue
        if prev is not None:
            for mid, old in prev.items():
                if not old.records:
                    continue
                why = history_rewrite(old, cur.get(mid, Routing([], False, {})))
                if why:
                    violations.append(f"{mid}: route history is not append-only between {prev_label} and {label}: {why}")
        for mid, fixed in named.items():                         # a route a record has named keeps the identity it had then
            if mid not in cur or not cur[mid].records:
                continue                                         # the metric itself vanished: reported above
            for provider, (identity, first) in list(fixed.items()):
                now = cur[mid].identities.get(provider)
                why = identity_change(identity, now)
                if why:                                          # reported once; later versions are compared with this one
                    violations.append(f"{mid}: route {provider} was named by the route history in {first}, but its identity "
                                      f"changed by {label}: {why}; a changed definition is a new route with its own activation record")
                    fixed[provider] = (now, first)
        for mid, routing in cur.items():
            for provider, identity in routing.identities.items():
                named.setdefault(mid, {}).setdefault(provider, (identity, label))
        prev, prev_label = cur, label
    return violations, notes


def route_history_integrity(c: "Check", dictionary: Path) -> None:
    violations, notes = route_history_audit(dictionary)
    for v in violations:
        c.fail(v)
    for n in notes:
        c.warn(n)


def preregistration(case_dir: Path) -> Check:
    """Baseline, amendments, updates and refresh records are append-only; amendments must be
    committed after the baseline and before the first release they could have been informed by.

    A file carried over from the origin repository (listed in the origin-history anchor) is immutable when its
    content still equals the blob the origin committed, and its first commit is the origin's."""
    from .store import utc_naive
    c = Check("E4", "Preregistration immutability")
    anchor = origin_history(case_dir)
    anchored = anchor.get("files", {})
    files = (sorted((case_dir / "preregistered").glob("*.yaml")) + sorted((case_dir / "updates").glob("*.yaml"))
             + sorted((case_dir / "refreshes").glob("*.json")) + sorted((case_dir / "reviews").glob("*/*.json")))
    if anchor:
        files.append(case_dir / ORIGIN_HISTORY)         # the anchor itself is append-only
    if not files:
        c.warn("no preregistered baseline yet")
    first_at: dict[Path, pd.Timestamp | None] = {}
    for f in files:
        origin = anchored.get(_git_path(f))
        if origin:
            if _blob(f) != origin.get("blob"):
                c.fail(f"{f.name}: differs from the content first committed in {anchor.get('origin_repo')} "
                       f"({origin['sha'][:7]})")
            if origin.get("origin_commits", 1) != 1:
                c.fail(f"{f.name}: modified in the origin repository ({origin['origin_commits']} commits)")
            first_at[f] = pd.Timestamp(origin["at"]).tz_convert("UTC").tz_localize(None)
        commits = git_history(f)          # anchored or not, this repo's own history must stay append-only too
        dirty = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", str(f)]).returncode != 0
        if origin:
            if len(commits) > 1:
                c.fail(f"{f.name}: modified in this repository after the snapshot ({len(commits)} commits)")
            if commits and dirty:
                c.fail(f"{f.name}: uncommitted edits to an immutable file")
            continue
        if not commits:
            c.warn(f"{f.name}: not committed yet")
        elif len(commits) > 1:
            c.fail(f"{f.name}: modified after first commit ({len(commits)} commits)")
        if commits and dirty:
            c.fail(f"{f.name}: uncommitted edits to an immutable file")
        first_at[f] = commit_time(commits[-1]) if commits else None
    import yaml
    for f in sorted((case_dir / "preregistered").glob("*-amendment-*.yaml")):
        a = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        t = first_at.get(f)
        if t is None:
            continue
        base_commit = commit_time(a.get("baseline_commit", ""), anchor) if a.get("baseline_commit") else None
        deadline = (a.get("effective_before") or {}).get("at")
        if base_commit is None:
            c.fail(f"{f.name}: baseline_commit {a.get('baseline_commit')} not found in history")
        elif t < base_commit:
            c.fail(f"{f.name}: committed before the baseline it amends")
        if not deadline:
            c.fail(f"{f.name}: no effective_before release")
        elif t >= utc_naive(deadline):
            c.fail(f"{f.name}: committed at {t} UTC, after the release it must precede ({deadline})")
    return c


def thesis_discipline(case_dir: Path) -> Check:
    c = Check("E5", "Thesis update discipline")
    try:
        _, _, errs = fold(case_dir)
    except FileNotFoundError as ex:
        c.warn(str(ex))
        return c
    for e in errs:
        c.fail(e)
    return c


def is_shallow() -> bool:
    """True in a shallow clone, where `git log` reports the graft commit, not a file's real first commit."""
    try:
        return subprocess.check_output(["git", "rev-parse", "--is-shallow-repository"], text=True,
                                       stderr=subprocess.DEVNULL).strip() == "true"
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def audit_manifest(case_dir: Path) -> dict:
    """{repo-relative path: first commit} for every immutable research file, so a site built
    from a shallow clone can still show the audit trail. Empty in a shallow clone."""
    out = {}
    if is_shallow():
        return out
    files = (sorted((case_dir / "preregistered").glob("*.yaml")) + sorted((case_dir / "updates").glob("*.yaml"))
             + sorted((case_dir / "refreshes").glob("*.json")))
    anchored = origin_history(case_dir).get("files", {})
    for f in files:
        rel = _git_path(f)
        if rel in anchored:                              # first committed in the origin repository
            out[rel] = {"sha": anchored[rel]["sha"], "at": anchored[rel]["at"]}
            continue
        try:
            log = subprocess.check_output(["git", "log", "--diff-filter=A", "--format=%H|%cI", "--", str(f)],
                                          text=True, stderr=subprocess.DEVNULL).strip()
            rel = subprocess.check_output(["git", "ls-files", "--full-name", str(f)], text=True,
                                          stderr=subprocess.DEVNULL).strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue
        if log and rel:
            sha, at = log.splitlines()[-1].split("|")
            out[rel] = {"sha": sha, "at": at}
    return out


def write_report(results: list[Check], out: Path, mode: str, case_dir: Path | None = None) -> dict:
    """Eval report with a true-time stamp (server-synced), the commit it ran on, and the
    audit manifest of immutable files."""
    import json
    from dataclasses import asdict
    from . import ingest
    ingest.sync_clock(timeout=5)
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        commit = ""
    audit = audit_manifest(case_dir) if case_dir else {}
    if case_dir and is_shallow() and out.exists():
        # truncated history cannot say when a file was first committed: keep the last full-history manifest
        audit = json.loads(out.read_text(encoding="utf-8")).get("audit", {})
    report = {"generated_at": ingest.now_iso(), "commit": commit, "mode": mode,
              "checks": [asdict(c) for c in results], "audit": audit}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def run_all(obs, metrics, claims, case_dir: Path, public_only: bool = False, dictionary: Path | None = None) -> list[Check]:
    """The eval gate. With `dictionary`, E4 also audits that route history is append-only across git versions."""
    e4 = preregistration(case_dir)
    if dictionary is not None:
        route_history_integrity(e4, dictionary)
    return [
        data_quality(obs, metrics, public_only),
        citation_integrity(claims, obs, metrics,
                           memo={loc: case_dir / f"memo.{loc}.md.j2" for loc in LOCALES},
                           presentation=[case_dir / "presentation.yaml", case_dir / "policy_events.yaml"]),
        derived_lineage(claims, obs, metrics),
        asof_leakage(claims, obs, metrics),
        e4,
        thesis_discipline(case_dir),
    ]
