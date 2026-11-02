"""Evidence tests (hypothesis level) and terminal decision rules (thesis level).

An evidence test answers one narrow question about one indicator and moves one
hypothesis. A terminal decision rule combines test results and decides whether
the whole thesis is CONFIRMED, FALSIFIED or still ACTIVE. Keeping these apart
stops a single bad monthly print from "falsifying" a multi-quarter thesis.
"""
from __future__ import annotations

import operator
from dataclasses import dataclass, field

from .derive import Deriver

OPS = {">": operator.gt, ">=": operator.ge, "<": operator.lt, "<=": operator.le}
HYPOTHESES = {"H0", "H1", "H2", "H3", "H4"}
RULES = {"latest", "change", "streak", "avg"}


@dataclass
class EvidenceTest:
    id: str
    hypothesis: str           # H0..H4
    indicator: str            # metric_id or fn(args)
    rule: str                 # latest | change | streak | avg
    op: str                   # > >= < <=
    threshold: float
    n: int = 1                # periods for change / streak / avg
    window: str = ""          # human-readable evaluation window
    check: str = ""           # release that triggers evaluation
    if_true: str = "supports"  # supports | challenges  (effect on `hypothesis` when condition holds)
    description: str = ""
    threshold_basis: str = ""  # how the threshold was set (historical calibration etc.)

    def validate(self) -> None:
        assert self.hypothesis in HYPOTHESES, f"{self.id}: bad hypothesis"
        assert self.rule in RULES, f"{self.id}: bad rule"
        assert self.op in OPS, f"{self.id}: bad op"
        assert self.if_true in {"supports", "challenges"}, f"{self.id}: bad if_true"
        assert self.n >= 1


@dataclass
class TestResult:
    id: str
    hypothesis: str
    outcome: str              # true | false | insufficient_data
    effect: str               # supports | challenges | none
    observed: float | None
    latest_period: str | None
    refs: list[str] = field(default_factory=list)


def evaluate_test(t: EvidenceTest, d: Deriver) -> TestResult:
    t.validate()
    s = d.series_for(t.indicator).dropna()
    if s.empty:
        return TestResult(t.id, t.hypothesis, "insufficient_data", "none", None, None)
    last = s.index[-1]
    # Windows are calendar periods, not "the last n rows": a gap (e.g. a Jan-Feb combined
    # release) must not silently stretch a 6-month change into 7 months.
    periods = [last - t.n, last] if t.rule == "change" else [last - k for k in range(t.n - 1, -1, -1)]
    if any(p not in s.index for p in periods):
        return TestResult(t.id, t.hypothesis, "insufficient_data", "none", None, str(last))
    vals = [float(s[p]) for p in periods]
    cmp = OPS[t.op]
    if t.rule == "latest":
        observed, ok = vals[-1], cmp(vals[-1], t.threshold)
    elif t.rule == "change":
        observed = vals[-1] - vals[0]
        ok = cmp(observed, t.threshold)
    elif t.rule == "streak":
        observed, ok = vals[-1], all(cmp(v, t.threshold) for v in vals)
    else:  # avg
        observed = sum(vals) / len(vals)
        ok = cmp(observed, t.threshold)
    effect = t.if_true if ok else ("challenges" if t.if_true == "supports" else "supports")
    refs = [d.ref_for(t.indicator, p) for p in periods]
    return TestResult(t.id, t.hypothesis, "true" if ok else "false", effect,
                      round(observed, 4), str(periods[-1]), refs)


def evaluate_condition(cond: dict, results: dict[str, TestResult]) -> bool | None:
    """Boolean tree over test outcomes. Returns None if any needed leaf lacks data.

    Leaves: {"test": id, "is": true|false}
    Nodes:  {"all": [...]}, {"any": [...]}, {"at_least": n, "of": [...]}
    """
    if "test" in cond:
        r = results.get(cond["test"])
        if r is None or r.outcome == "insufficient_data":
            return None
        return (r.outcome == "true") == bool(cond.get("is", True))
    if "all" in cond:
        vals = [evaluate_condition(c, results) for c in cond["all"]]
        if any(v is False for v in vals):
            return False
        return None if any(v is None for v in vals) else True
    if "any" in cond:
        vals = [evaluate_condition(c, results) for c in cond["any"]]
        if any(v is True for v in vals):
            return True
        return None if any(v is None for v in vals) else False
    if "at_least" in cond:
        vals = [evaluate_condition(c, results) for c in cond["of"]]
        trues, unknown = sum(v is True for v in vals), sum(v is None for v in vals)
        if trues >= cond["at_least"]:
            return True
        return None if trues + unknown >= cond["at_least"] else False
    raise ValueError(f"bad condition node {cond}")


def terminal_rule(rules: dict, results: dict[str, TestResult], decision_window_open: bool) -> tuple[str, str | None]:
    """(status, name of the rule that fired). CONFIRMED / FALSIFIED only from preregistered
    rules; otherwise ACTIVE.

    `decision_window_open` is False before the terminal window; early termination is
    allowed only through rules explicitly marked `early: true`.
    """
    named = [(k, r) for k, r in rules.items() if isinstance(r, dict) and "when" in r]
    # falsification is checked before confirmation
    named.sort(key=lambda kr: kr[1].get("status", kr[0]) != "FALSIFIED")
    for key, rule in named:
        status = rule.get("status", key)
        if not decision_window_open and not rule.get("early", False):
            continue
        if evaluate_condition(rule["when"], results) is True:
            return status, key
    # At the terminal window, a thesis no rule can decide (required data missing) is
    # closed as inconclusive (RETIRED) rather than left open indefinitely.
    return ("RETIRED", None) if decision_window_open else ("ACTIVE", None)


def terminal_decision(rules: dict, results: dict[str, TestResult], decision_window_open: bool) -> str:
    return terminal_rule(rules, results, decision_window_open)[0]


def window_is_open(horizon: dict, deriver, when) -> bool:
    """Has the terminal decision window opened by `when`?

    `terminal_window_opens` is either a timestamp, or {when_available: [refs]}: the window
    opens once every listed observation (e.g. the first 2027Q1 GDP print) is in the as-of
    information set. Null means the window cannot open yet.
    """
    opens = (horizon or {}).get("terminal_window_opens")
    if not opens:
        return False
    if isinstance(opens, dict):
        refs = opens.get("when_available") or []
        return bool(refs) and all(deriver.resolve(r) is not None for r in refs)
    from .store import utc_naive
    return utc_naive(when) >= utc_naive(opens)


def load_tests(raw: list[dict]) -> list[EvidenceTest]:
    tests = [EvidenceTest(**t) for t in raw]
    ids = [t.id for t in tests]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate evidence test id")
    for t in tests:
        t.validate()
    return tests
