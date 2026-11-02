"""The structured result contract, the hard gates (fail closed) and the deterministic renderer.

Strategy §4 P4, §8.3, §8.4, §11.2, §12. The model returns two JSON objects (Draft, Challenge). Both are
checked against a *closed* schema. A violation of any gate blocks the output: nothing here repairs,
substitutes or guesses.

Unrepresentable hallucination: prose may carry data only as `{obs:...}` / `{drv:...}` placeholders that
name an allow-listed evidence id; code renders the value. Any other digit, any unit word, any period
the information set cannot contain, any code-owned field and any thesis-state field is a violation.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

import pandas as pd

from ..claims import period_tokens
from .context import PERIODS, allowed_refs

GATES = ("schema", "numeric_grounding", "invalid_evidence_ref", "as_of_violation", "mechanical_delta_overwrite",
         "thesis_state_write", "divergence_inconsistent", "missing_evidence")
# strategy §11.2: the five hard gates, target zero (the fifth is "unsupported claim published", enforced as
# `missing_evidence` + the fact that nothing failing is ever rendered or shown)
HARD_GATES = ("numeric_grounding", "invalid_evidence_ref", "as_of_violation", "mechanical_delta_overwrite", "missing_evidence")

LENSES = ("level", "marginal", "breadth", "mechanism")
MATERIALITY = ("high", "medium", "low")
ASSESSMENTS = ("strengthen", "weaken", "unchanged", "unresolved")
HINTS = ("hold", "consider_up", "consider_down")
DISPLAY_ORDER = ("H0", "H1", "H2", "H3", "H4")

# code-owned or thesis-owned names: the model may not supply them anywhere in its output
CODE_OWNED = {"mechanical_delta", "vs_expectation", "release_id", "as_of", "prior_as_of", "terminal", "terminal_status"}
THESIS_OWNED = {"probability", "conviction", "status", "thesis_probability", "new_probability", "last_update_direction"}

PLACEHOLDER = re.compile(r"\{([^{}]*)\}")
H_LABEL = re.compile(r"\bH[0-4]\b")
UNIT_WORDS = re.compile(r"%|\bper ?cent(age)?( points?)?\b|\bpercent(age)?( points?)?\b|\bbasis points?\b|\bbps?\b|百分|个点", re.I)
THESIS_ASSIGN = re.compile(r"\bconviction\b[^.;]{0,30}\b(low|medium|high)\b|\bconviction\s+(to|at)\s+\w+", re.I)
MAX_LEN = {"default": 700, "draft_analyst_update": 1800}


@dataclass
class Violation:
    gate: str
    path: str
    message: str

    def as_dict(self) -> dict:
        return {"gate": self.gate, "path": self.path, "message": self.message}


class RenderError(ValueError):
    pass


# ---------------------------------------------------------------- text-level gates
def digits_left(text: str) -> list[str]:
    """Digits that remain once placeholders, period labels (2026-08, 2026Q3, 2026) and H0-H4 are removed."""
    t = H_LABEL.sub(" ", PERIODS.sub(" ", PLACEHOLDER.sub(" ", text)))
    return re.findall(r"\d+(?:[.,]\d+)*", t)


def _period_future(tok: str, when: pd.Timestamp, forward: set[str]) -> bool:
    if tok in forward:
        return False
    try:
        if re.fullmatch(r"\d{4}", tok):
            return int(tok) > when.year
        return pd.Period(tok).end_time > when
    except (ValueError, KeyError):
        return True


class Checker:
    """Collects violations for one pass against one context."""

    def __init__(self, ctx: dict):
        self.ctx, self.allow, self.errs = ctx, allowed_refs(ctx), []
        self.when = pd.Timestamp(ctx["as_of"]).tz_localize(None)
        self.forward = set(ctx["forward_periods"])

    def err(self, gate: str, path: str, msg: str) -> None:
        self.errs.append(Violation(gate, path, msg))

    # -- structure
    def keys(self, path: str, d, required: set[str]) -> bool:
        if not isinstance(d, dict):
            self.err("schema", path, "must be an object")
            return False
        for k in sorted(set(d) - required):
            gate = ("mechanical_delta_overwrite" if k == "mechanical_delta" else
                    "thesis_state_write" if k in THESIS_OWNED else "schema")
            what = ("code-owned and cannot be supplied by the model" if k in CODE_OWNED
                    else "owned by the analyst and cannot be supplied by the model" if k in THESIS_OWNED else "not in the schema")
            self.err(gate, f"{path}.{k}", f"'{k}' is {what}")
        missing = required - set(d)
        for k in sorted(missing):
            self.err("schema", f"{path}.{k}", "required field missing")
        return not (set(d) - required) and not missing

    def enum(self, path: str, v, allowed) -> None:
        if v not in allowed:
            self.err("schema", path, f"{v!r} is not one of {list(allowed)}")

    def refs(self, path: str, v, *, minimum: int = 1) -> list[str]:
        if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
            self.err("schema", path, "must be a list of evidence ids")
            return []
        if len(v) < minimum:
            self.err("missing_evidence", path, f"at least {minimum} evidence id required: a claim without evidence is not publishable")
        for r in v:
            if r not in self.allow:
                self.err("invalid_evidence_ref", path, f"{r!r} is not in the supplied evidence allowlist")
        return v

    # -- prose
    def text(self, path: str, s, *, declared: list[str] | None = None, placeholders: bool = True, long: bool = False) -> None:
        if not isinstance(s, str) or not s.strip():
            self.err("schema", path, "must be a non-empty string")
            return
        if len(s) > MAX_LEN["draft_analyst_update" if long else "default"]:
            self.err("schema", path, f"too long ({len(s)} characters): this is a delta, not an essay")
        if s.count("{") != s.count("}"):
            self.err("schema", path, "unbalanced braces")
        used = PLACEHOLDER.findall(s)
        if used and not placeholders:
            self.err("invalid_evidence_ref", path, "background knowledge cannot carry evidence placeholders")
        for u in used:
            if u not in self.allow:
                self.err("invalid_evidence_ref", path, f"placeholder {{{u}}} is not in the supplied evidence allowlist")
            elif declared is not None and u not in declared:
                self.err("missing_evidence", path, f"placeholder {{{u}}} is not listed in this item's evidence_refs")
        for n in digits_left(s):
            self.err("numeric_grounding", path, f"bare number {n!r}: data may only appear as an allow-listed placeholder")
        m = UNIT_WORDS.search(PLACEHOLDER.sub(" ", s))
        if m:
            self.err("numeric_grounding", path, f"unit word {m.group(0)!r}: magnitudes belong in placeholders")
        for tok in sorted(period_tokens(PLACEHOLDER.sub(" ", s))):
            if _period_future(tok, self.when, self.forward):
                self.err("as_of_violation", path, f"period {tok} is after the information set (as_of {self.ctx['as_of']}) and is not a scheduled release")
        if THESIS_ASSIGN.search(s):
            self.err("thesis_state_write", path, "assigns a conviction level: conviction belongs to the analyst")


# ---------------------------------------------------------------- pass 1: Draft
def validate_draft(raw, ctx: dict) -> list[Violation]:
    c = Checker(ctx)
    c.keys("$", raw, {"executive_delta", "hypothesis_impact", "preliminary_implications"})
    if not isinstance(raw, dict):
        return c.errs
    deltas = raw.get("executive_delta")
    if not isinstance(deltas, list) or not 1 <= len(deltas) <= 5:
        c.err("schema", "$.executive_delta", "between 1 and 5 items required")
    else:
        seen = set()
        for i, x in enumerate(deltas):
            p = f"$.executive_delta[{i}]"
            if c.keys(p, x, {"id", "template", "lens", "materiality", "evidence_refs"}) or isinstance(x, dict):
                if x.get("id") in seen or not re.fullmatch(r"X[1-5]", str(x.get("id"))):
                    c.err("schema", f"{p}.id", "id must be unique and X1..X5")
                seen.add(x.get("id"))
                c.enum(f"{p}.lens", x.get("lens"), LENSES)
                c.enum(f"{p}.materiality", x.get("materiality"), MATERIALITY)
                declared = c.refs(f"{p}.evidence_refs", x.get("evidence_refs"))
                c.text(f"{p}.template", x.get("template"), declared=declared)
    impact = raw.get("hypothesis_impact")
    if not isinstance(impact, list):
        c.err("schema", "$.hypothesis_impact", "must be a list with one entry for each of H0-H4")
    else:
        got = [h.get("hypothesis") if isinstance(h, dict) else None for h in impact]
        if sorted(map(str, got)) != sorted(DISPLAY_ORDER):
            c.err("schema", "$.hypothesis_impact", f"exactly one entry for each of {list(DISPLAY_ORDER)} required (got {got})")
        for i, h in enumerate(impact):
            p = f"$.hypothesis_impact[{i}]"
            if not (c.keys(p, h, {"hypothesis", "ai_assessment", "divergence", "divergence_reason", "rationale_template", "evidence_refs"})
                    or isinstance(h, dict)):
                continue
            c.enum(f"{p}.ai_assessment", h.get("ai_assessment"), ASSESSMENTS)
            declared = c.refs(f"{p}.evidence_refs", h.get("evidence_refs"), minimum=0 if h.get("ai_assessment") == "unresolved" else 1)
            c.text(f"{p}.rationale_template", h.get("rationale_template"), declared=declared)
            hid = h.get("hypothesis")
            if hid in ctx["hypotheses"] and h.get("ai_assessment") in ASSESSMENTS:
                expect = divergence_of(ctx["hypotheses"][hid]["mechanical_delta"], h["ai_assessment"])
                if h.get("divergence") is not expect:
                    c.err("divergence_inconsistent", f"{p}.divergence",
                          f"mechanical_delta is {ctx['hypotheses'][hid]['mechanical_delta']!r} and ai_assessment {h['ai_assessment']!r}: "
                          f"divergence must be {str(expect).lower()}")
                if h.get("divergence") is True:
                    c.text(f"{p}.divergence_reason", h.get("divergence_reason"), declared=declared)
                elif h.get("divergence") is False and str(h.get("divergence_reason") or "").strip():
                    c.err("divergence_inconsistent", f"{p}.divergence_reason", "no divergence: the reason must be empty")
    prelim = raw.get("preliminary_implications")
    if not isinstance(prelim, list) or len(prelim) > 3:
        c.err("schema", "$.preliminary_implications", "a list of at most 3 items (may be empty)")
    else:
        for i, x in enumerate(prelim):
            p = f"$.preliminary_implications[{i}]"
            if c.keys(p, x, {"template", "hypothesis", "evidence_refs"}):
                c.enum(f"{p}.hypothesis", x["hypothesis"], DISPLAY_ORDER)
                declared = c.refs(f"{p}.evidence_refs", x["evidence_refs"])
                c.text(f"{p}.template", x["template"], declared=declared)
    return c.errs


def divergence_of(mechanical: str, ai: str) -> bool:
    """Divergence is derived, never trusted: the AI direction against the code-owned direction (§8.4).
    Aligned: supports/strengthen, challenges/weaken, unchanged/unchanged, and unchanged/unresolved."""
    return (mechanical, ai) not in {("supports", "strengthen"), ("challenges", "weaken"),
                                    ("unchanged", "unchanged"), ("unchanged", "unresolved")}


# ---------------------------------------------------------------- pass 2: Challenge
def validate_challenge(raw, ctx: dict) -> list[Violation]:
    c = Checker(ctx)
    c.keys("$", raw, {"competing_explanation", "does_not_prove", "research_needs", "draft_analyst_update"})
    if not isinstance(raw, dict):
        return c.errs
    ce = raw.get("competing_explanation")
    if c.keys("$.competing_explanation", ce, {"claim", "why_plausible", "discriminating_observation", "evidence_refs", "background_knowledge"}):
        declared = c.refs("$.competing_explanation.evidence_refs", ce["evidence_refs"])
        for k in ("claim", "why_plausible", "discriminating_observation"):
            c.text(f"$.competing_explanation.{k}", ce[k], declared=declared)
        bk = ce["background_knowledge"]
        if not isinstance(bk, list) or len(bk) > 3:
            c.err("schema", "$.competing_explanation.background_knowledge", "a list of at most 3 strings (may be empty)")
        else:
            for i, s in enumerate(bk):
                c.text(f"$.competing_explanation.background_knowledge[{i}]", s, placeholders=False)
    dnp = raw.get("does_not_prove")
    if not isinstance(dnp, list) or not 1 <= len(dnp) <= 4:
        c.err("schema", "$.does_not_prove", "between 1 and 4 items required")
    else:
        for i, s in enumerate(dnp):
            c.text(f"$.does_not_prove[{i}]", s)
    needs = raw.get("research_needs")
    if not isinstance(needs, list) or len(needs) > 3:
        c.err("schema", "$.research_needs", "at most 3 items, ordered by information value")
    else:
        for i, n in enumerate(needs):
            p = f"$.research_needs[{i}]"
            if c.keys(p, n, {"question", "hypothesis", "why_now", "decision_it_could_change", "resolving_data"}):
                c.enum(f"{p}.hypothesis", n["hypothesis"], DISPLAY_ORDER)
                for k in ("question", "why_now", "decision_it_could_change", "resolving_data"):
                    c.text(f"{p}.{k}", n[k])
    up = raw.get("draft_analyst_update")
    if c.keys("$.draft_analyst_update", up, {"text_template", "direction_hint"}):
        c.enum("$.draft_analyst_update.direction_hint", up["direction_hint"], HINTS)
        c.text("$.draft_analyst_update.text_template", up["text_template"], long=True)
    return c.errs


# ---------------------------------------------------------------- code-owned assembly and rendering
def vs_expectation(delta: dict, ctx: dict) -> str:
    """Computed by code from the frozen Expectation Note; the model never writes it."""
    exp = ctx.get("expectation")
    if not exp or exp.get("status") != "frozen":
        return "not_set"
    by_ref = {it["ref"]: it["vs_expectation"] for it in exp["items"]}
    return next((by_ref[r] for r in delta["evidence_refs"] if r in by_ref), "not_set")


def assemble(ctx: dict, draft: dict, challenge: dict) -> dict:
    """The §8.3 result: model fields plus the code-owned ones (release_id, as_of, mechanical_delta, vs_expectation)."""
    impact = sorted(draft["hypothesis_impact"], key=lambda h: DISPLAY_ORDER.index(h["hypothesis"]))
    return {
        "release_id": ctx["release"]["release_id"], "as_of": ctx["as_of"],
        "executive_delta": [{**x, "vs_expectation": vs_expectation(x, ctx)} for x in draft["executive_delta"]],
        "hypothesis_impact": [{"hypothesis": h["hypothesis"], "mechanical_delta": ctx["hypotheses"][h["hypothesis"]]["mechanical_delta"],
                               **{k: v for k, v in h.items() if k != "hypothesis"}} for h in impact],
        "preliminary_implications": draft["preliminary_implications"],
        "competing_explanation": challenge["competing_explanation"],
        "does_not_prove": challenge["does_not_prove"],
        "research_needs": challenge["research_needs"],
        "draft_analyst_update": challenge["draft_analyst_update"],
    }


def _fill(s: str, by_ref: dict) -> str:
    def sub(m):
        e = by_ref.get(m.group(1))
        if e is None:
            raise RenderError(f"placeholder {{{m.group(1)}}} has no allow-listed value: refusing to render")
        return e["ref"].split(":", 1)[1] if e["kind"] == "test" else e["display"]
    return PLACEHOLDER.sub(sub, s)


def render(result: dict, ctx: dict) -> dict:
    """Same shape as `result`, every placeholder replaced by its code-computed display value."""
    by_ref = {e["ref"]: e for e in ctx["allowlist"]}

    def walk(node, key=""):
        if isinstance(node, dict):
            return {k: walk(v, k) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v, key) for v in node]
        if isinstance(node, str) and key not in ("evidence_refs",):
            return _fill(node, by_ref)
        return node
    return walk(result)


def render_markdown(rendered: dict, ctx: dict, *, show_hint: bool) -> str:
    """Reading order of strategy §8.6: What Changed, vs Expectation, Divergence, Why It Matters, Counter-case,
    What We Still Don't Know, then the analyst's decision. The direction hint is shown only after a blind take."""
    r, o = rendered, []
    o += [f"# {ctx['release']['name']} — Copilot read (as of {ctx['as_of']})", ""]
    if ctx.get("replay_disclosure"):
        o += [f"> {ctx['replay_disclosure']}", ""]
    o += ["## What changed"] + [f"- **{x['id']}** [{x['lens']}, {x['materiality']}, vs expectation: {x['vs_expectation']}] {x['template']}"
                                  for x in r["executive_delta"]] + [""]
    divs = [h for h in r["hypothesis_impact"] if h["divergence"]]
    o += ["## Divergence (the AI disagrees with the mechanical test direction)"]
    o += [f"- **{h['hypothesis']}**: mechanical *{h['mechanical_delta']}*, AI *{h['ai_assessment']}*. {h['divergence_reason']}" for h in divs] or ["- none"]
    o += ["", "## Why it matters (hypothesis impact)"]
    o += [f"- **{h['hypothesis']}** mechanical *{h['mechanical_delta']}* · AI *{h['ai_assessment']}*. {h['rationale_template']}"
          for h in r["hypothesis_impact"]]
    o += [f"- implication ({p['hypothesis']}): {p['template']}" for p in r["preliminary_implications"]]
    ce = r["competing_explanation"]
    o += ["", "## Strongest counter-case", ce["claim"], f"*Why plausible:* {ce['why_plausible']}",
          f"*What would discriminate:* {ce['discriminating_observation']}"]
    o += [f"*Background knowledge (not evidence):* {b}" for b in ce["background_knowledge"]]
    o += ["", "## What we still don't know"] + [f"- {s}" for s in r["does_not_prove"]]
    o += ["", "## Research needs"] + [f"- ({n['hypothesis']}) {n['question']} — why now: {n['why_now']}; could change: {n['decision_it_could_change']}; "
                                     f"resolve with: {n['resolving_data']}" for n in r["research_needs"]]
    up = r["draft_analyst_update"]
    o += ["", "## Draft analyst update (for your consideration; you own the thesis)", up["text_template"]]
    o += [f"*Direction hint:* {up['direction_hint']}" if show_hint else "*Direction hint withheld until your blind take is recorded.*"]
    return "\n".join(o) + "\n"


def parse_json(text: str):
    """The model must return one JSON object; a single ```json fence is tolerated, nothing else."""
    s = text.strip()
    m = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", s, re.S)
    return json.loads(m.group(1) if m else s)


def gate_counts(errs: list[Violation]) -> dict[str, int]:
    return {g: sum(e.gate == g for e in errs) for g in GATES}
