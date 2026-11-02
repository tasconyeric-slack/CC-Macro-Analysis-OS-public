"""One research state, two languages: assemble what a page needs, in one language.

`build.py` computes the language-neutral model once (observations, derived values, evidence-test
outcomes, thesis state, claims with their bound numbers). Everything here only CHOOSES WORDS:
it never recomputes or alters a number, a claim id, an outcome, a threshold, a probability or the
thesis state. Texts that exist only in English (immutable preregistered artifacts) are rendered
from frozen_zh.yaml; if one is missing the English text is used and recorded in `View.missing`,
which tests require to be empty for the repository's own content.
"""
from __future__ import annotations

import json
import re
from datetime import date
from html import escape

import pandas as pd
from markupsafe import Markup

import localization as L
from cnmacro.derive import REF_RE, parse_drv

STAGES = ["signal", "announced", "funded", "implementation", "observed_impact"]
LENSES = ["level", "marginal", "breadth", "mechanism"]
STATE_TONE = {"supportive": "good", "partly": "warn", "unconfirmed": "bad", "mixed": "warn", "leading_alt": "alt"}
POLICY_CATEGORIES = {"fiscal", "monetary", "investment", "consumption", "property", "multi"}
SOURCE_KINDS = {"primary", "official_media"}
OFFICIAL_HOSTS = ("gov.cn", "news.cn", "xinhuanet.com", "stats.gov.cn", "pbc.gov.cn", "ndrc.gov.cn",
                  "mof.gov.cn", "customs.gov.cn", "csrc.gov.cn", "safe.gov.cn")
SCENARIO_ROWS = ["rates", "cny", "equities", "banks", "confirming", "falsifying"]


def pick(node, loc: str):
    """{en:..., zh:...} -> the text in `loc`; a plain string is returned as is."""
    text = node.get(loc) if isinstance(node, dict) else node
    return L.tidy(text, loc)


def fmt_cny(value: float, loc: str) -> str:
    """250e9 -> 'RMB 250bn' | '2500亿元' (the same amount, written in each language's convention)."""
    return f"RMB {value / 1e9:g}bn" if loc == "en" else f"{value / 1e8:g}亿元"


def parse_zh_amount(text: str) -> float:
    """'2500亿元' -> 2.5e11; used by tests and the build to prove a figure's value and quote agree."""
    m = re.fullmatch(r"([\d.]+)(万亿|亿|万)?元", text.strip())
    if not m:
        raise ValueError(f"cannot read amount {text!r}")
    return float(m.group(1)) * {"万亿": 1e12, "亿": 1e8, "万": 1e4, None: 1}[m.group(2)]


def validate_policy_events(doc: dict) -> list[str]:
    errs, seen = [], set()
    for e in (doc or {}).get("events", []):
        eid = e.get("event_id", "?")
        for k in ("event_id", "published", "institution", "title", "source", "category", "measure", "stage",
                  "channel", "hypothesis", "interpretation", "next_confirmation"):
            if not e.get(k):
                errs.append(f"{eid}: missing {k}")
        for k in ("institution", "title", "measure", "channel", "interpretation", "next_confirmation"):
            for loc in L.LOCALES:
                if not str((e.get(k) or {}).get(loc, "")).strip():
                    errs.append(f"{eid}: {k} missing in {loc}")
        if eid in seen:
            errs.append(f"{eid}: duplicate event_id")
        seen.add(eid)
        if e.get("stage") not in STAGES:
            errs.append(f"{eid}: stage {e.get('stage')!r} not in {STAGES}")
        if e.get("category") not in POLICY_CATEGORIES:
            errs.append(f"{eid}: category {e.get('category')!r}")
        if e.get("hypothesis") not in {"H0", "H1", "H2", "H3", "H4"}:
            errs.append(f"{eid}: hypothesis {e.get('hypothesis')!r}")
        src = e.get("source") or {}
        host = re.sub(r"^https?://([^/]+)/?.*$", r"\1", str(src.get("url", "")))
        if not str(src.get("url", "")).startswith("https://") or not host.endswith(OFFICIAL_HOSTS):
            errs.append(f"{eid}: source url must be an official https host ({src.get('url')!r})")
        if src.get("kind") not in SOURCE_KINDS:
            errs.append(f"{eid}: source.kind must be one of {sorted(SOURCE_KINDS)}")
        if src.get("kind") == "official_media" and not src.get("primary_listing"):
            errs.append(f"{eid}: official_media needs primary_listing (the issuer's own page)")
        figs = {f["id"]: f for f in e.get("figures", [])}
        for f in figs.values():
            try:
                if abs(parse_zh_amount(f["quote_zh"]) - float(f["value_cny"])) > 1:
                    errs.append(f"{eid}: figure {f['id']} value {f['value_cny']} != quote {f['quote_zh']}")
            except ValueError as ex:
                errs.append(f"{eid}: figure {f['id']}: {ex}")
        for loc in L.LOCALES:
            used = set(re.findall(r"\{(\w+)\}", str((e.get("measure") or {}).get(loc, ""))))
            if used != set(figs):
                errs.append(f"{eid}: measure.{loc} uses figures {sorted(used)} but defines {sorted(figs)}")
    return errs


class View:
    """The research state as one language reads it."""

    def __init__(self, model: dict, loc: str):
        self.m, self.loc = model, loc
        self.t = L.Translator(loc)
        self.missing: list[str] = []
        self.p = model.get("presentation") or {}
        self.fz = (model.get("frozen_zh") or {}) if loc == "zh" else {}
        self.src = {s["id"]: s for s in (model.get("sources") or {}).get("sources", [])}

    # ------------------------------------------------------------ low level
    def date(self, v):
        return L.fmt_date(v, self.loc)

    def when(self, v):
        return L.fmt_when(v, self.loc)

    def period(self, v, long=False):
        return L.fmt_period(v, self.loc, long)

    def need(self, what: str, text):
        """Mark text that fell back to English on the Chinese page."""
        if self.loc == "zh" and text:
            self.missing.append(what)
        return text

    def frozen(self, en_text, *path, what=None):
        """English text of an immutable artifact, or its rendering in frozen_zh.yaml."""
        if self.loc == "en" or en_text in (None, ""):
            return en_text
        node = self.fz
        for k in path:
            node = node.get(k) if isinstance(node, dict) else None
        if isinstance(node, str) and node.strip():
            return L.tidy(node, self.loc)
        return self.need(what or ".".join(map(str, path)), en_text)

    def source_name(self, sid: str) -> str:
        s = self.src.get(sid)
        return pick(s["name"], self.loc) if s else sid

    def metric_name(self, mid: str) -> str:
        m = self.m["metrics"].get(mid)
        if not m:
            return mid
        return (m.name_zh or self.need(f"metric {mid} name", m.name)) if self.loc == "zh" else m.name

    def metric_role(self, mid: str) -> str:
        m = self.m["metrics"][mid]
        return (m.role_zh or self.need(f"metric {mid} role", m.role)) if self.loc == "zh" else m.role

    def unit(self, unit: str) -> str:
        key = f"units.{unit}"
        return self.t(key) if self.t.has(key) else unit

    def status(self, s):
        return self.t(f"status.{s}") if s and self.t.has(f"status.{s}") else (s or "–")

    def confidence(self, c):
        return self.t(f"confidence.{c}") if c and self.t.has(f"confidence.{c}") else (c or "–")

    def direction(self, d):
        return self.t(f"direction.{d}") if d and self.t.has(f"direction.{d}") else (d or "–")

    # ------------------------------------------------------------ case text
    def case(self) -> dict:
        c = self.m["case"]
        q = pick((self.p.get("question") or {}), self.loc) or (c["question"] if self.loc == "en" else c.get("question_zh"))
        return {
            "question": q or c["question"],
            "statement": self.frozen(c["statement"], "case", "statement", what="case statement"),
            "terminal_release": self.frozen(c["horizon"]["terminal_release"], "case", "terminal_release", what="terminal release"),
            "sustainable": self.frozen(c["horizon"]["definition_of_sustainable"], "case", "definition_of_sustainable",
                                       what="definition of sustainable"),
            "otherwise": self.frozen(c["terminal_rules"].get("otherwise", ""), "case", "terminal_rules_otherwise",
                                     what="terminal rules otherwise"),
        }

    def hypothesis_text(self, hid: str, h: dict) -> dict:
        return {"name": self.frozen(h["name"], "hypotheses", hid, "name", what=f"{hid} name"),
                "claim": self.frozen(h["claim"], "hypotheses", hid, "claim", what=f"{hid} claim"),
                "short": self.t(f"hyp.short.{hid}")}

    def assessment(self, hid: str, en_text):
        base = self.m["baseline"]
        return self.frozen(en_text, "documents", base["_file"], "hypothesis_assessment", hid, what=f"{hid} assessment")

    def view_state(self, hid: str) -> dict:
        s = (self.p.get("hypothesis_states") or {}).get(hid) or {}
        state = s.get("state")
        return {"state": state, "tone": STATE_TONE.get(state, "alt"),
                "label": self.t(f"state.{state}") if state else "–", "note": pick(s.get("note"), self.loc) or ""}

    def test_row(self, row: dict) -> dict:
        t = dict(row)
        t["description"] = self.frozen(row["description"], "tests", row["id"], what=f"{row['id']} description")
        if self.loc == "zh":
            t["window"] = self.fz.get("windows", {}).get(row["window"]) or self.need(f"window {row['window']}", row["window"])
            t["check"] = self.fz.get("checks", {}).get(row["check"]) or self.need(f"check {row['check']}", row["check"])
        return t

    # ------------------------------------------------------------ claims and provenance
    def prov_line(self, it: dict) -> str:
        inst = " / ".join(self.source_name(s) for s in it["sources"]) or "–"
        if it["kind"] == "drv":
            name = self.derived_name(it)
        else:
            name = self.metric_name(it["metric_id"])
        ps = it["periods"]
        if len(ps) == 1:
            sep = "" if self.loc == "zh" else " "
            main = f"{self.period(ps[0], long=True)}{sep}{name}"
        else:
            span = L.fmt_periods(ps, self.loc)
            main = f"{name} ({span})" if self.loc == "en" else f"{name}（{span}）"
        if it.get("released"):
            tail = self.t("prov.released", date=self.date(it["released"]))
        else:
            tail = self.t("prov.retrieved", date=self.date(it["retrieved"]))
        return " · ".join([inst, main, tail])

    def derived_name(self, it: dict) -> str:
        fn, args = it["fn"], it["args"]
        mids = [a for a in args if a in self.m["metrics"]]
        nums = [a for a in args if a not in self.m["metrics"]]
        key = f"derived.{fn}"
        if fn == "deflator_yoy":
            return self.t(key)
        names = [self.metric_name(a) for a in mids]
        return self.t(key, metric=names[0] if names else "", n=nums[0] if nums else "")

    def claim(self, cid: str) -> dict | None:
        c = self.m["claims"].get(cid)
        if not c:
            return None
        prov = [self.prov_line(it) for it in c["prov"]]
        return {
            **{k: c[k] for k in ("id", "type", "stance", "hypotheses", "withheld", "supports", "source", "refs")},
            "text": c["text"][self.loc],
            "type_label": self.t(f"claim_type.{c['type']}"),
            "prov": prov[:3], "prov_more": max(0, len(prov) - 3), "prov_all": prov,
            "as_of": c["as_of"], "lineage": c["lineage"],
        }

    # ------------------------------------------------------------ curated evidence
    def curated(self, key: str) -> list[dict]:
        out = []
        for it in self.p.get(key) or []:
            cl = self.claim(it["claim"])
            if cl:
                out.append({"claim": cl, "lens": it.get("lens"),
                            "lens_label": self.t(f"lens.{it['lens']}") if it.get("lens") else ""})
        return out

    # ------------------------------------------------------------ policy
    def policy(self) -> dict:
        doc = self.m.get("policy") or {}
        base = self.m.get("baseline") or {}
        base_day = pd.Timestamp(str(base["as_of"])).date() if base else None
        in_judgment = set(base.get("policy_events") or [])
        events = []
        for e in doc.get("events", []):
            figs = {f["id"]: fmt_cny(float(f["value_cny"]), self.loc) for f in e.get("figures", [])}
            pub = pd.Timestamp(str(e["published"])).date()
            if e["event_id"] in in_judgment:
                scope = "in_baseline"
            elif base_day and pub <= base_day:
                scope = "before_baseline"
            else:
                scope = "after_baseline"
            src = e["source"]
            events.append({
                "id": e["event_id"], "published": e["published"], "date": self.date(str(e["published"])),
                "institution": pick(e["institution"], self.loc), "title": pick(e["title"], self.loc),
                "headline_zh": e.get("official_headline_zh"),
                "url": src["url"], "publisher": pick(src["publisher"], self.loc), "source_kind": src["kind"],
                "primary_listing": src.get("primary_listing"),
                "category": self.t(f"policy.category.{e['category']}"),
                "measure": pick(e["measure"], self.loc).format(**figs),
                "stage": e["stage"], "stage_label": self.t(f"policy.stage.{e['stage']}"),
                "stage_index": STAGES.index(e["stage"]),
                "stages": [{"key": s, "label": self.t(f"policy.stage.{s}"), "done": i <= STAGES.index(e["stage"]),
                            "current": i == STAGES.index(e["stage"])} for i, s in enumerate(STAGES)],
                "channel": pick(e["channel"], self.loc), "hypothesis": e["hypothesis"], "also": e.get("also", []),
                "interpretation": pick(e["interpretation"], self.loc),
                "next": pick(e["next_confirmation"], self.loc),
                "scope": scope, "scope_label": self.t(f"policy.scope.{scope}"),
                "reviewed": self.date(str(e.get("reviewed"))) if e.get("reviewed") else None,
            })
        events.sort(key=lambda e: e["published"], reverse=True)
        return {"events": events, "summary": pick((self.p.get("current_view") or {}).get("policy"), self.loc) or "",
                "realized": [self.claim(c) for c in ("C-H3-01", "C-H3-02") if self.claim(c)],
                "h3_tests": [self.test_row(t) for t in self.m["tests"] if t["hypothesis"] == "H3"]}

    # ------------------------------------------------------------ terminal rules in words
    def rules(self) -> list[dict]:
        case = self.m["case"]
        by_id = {t["id"]: t for t in self.m["tests"]}
        out = []
        for name, r in case["terminal_rules"].items():
            if not (isinstance(r, dict) and r.get("when")):
                continue
            status = r.get("status") or name
            out.append({
                "key": name, "status": status, "status_label": self.status(status),
                "title": self.t(f"rules.name.{name}") if self.t.has(f"rules.name.{name}") else self.status(status),
                "early": bool(r.get("early")),
                "tree": self._rule_node(r["when"], by_id),
                "raw": json.dumps(r, indent=2, ensure_ascii=False),
            })
        return out

    def _rule_node(self, node: dict, by_id: dict) -> dict:
        if "test" in node:
            t = self.test_row(by_id[node["test"]]) if node["test"] in by_id else {"id": node["test"], "description": node["test"]}
            want = node.get("is", True)
            outcome = (by_id.get(node["test"], {}).get("result") or {}).get("outcome")
            met = None if outcome in (None, "insufficient_data") else ((outcome == "true") == bool(want))
            return {"kind": "test", "id": node["test"], "want": bool(want), "description": t["description"], "met": met,
                    "hyp": t.get("hypothesis")}
        for kind in ("all", "any"):
            if kind in node:
                return {"kind": kind, "children": [self._rule_node(c, by_id) for c in node[kind]]}
        if "at_least" in node:
            kids = [self._rule_node(c, by_id) for c in node["of"]]
            return {"kind": "at_least", "n": node["at_least"], "total": len(kids), "children": kids,
                    "met_count": sum(1 for k in kids if k["met"]), "pending": sum(1 for k in kids if k["met"] is None)}
        return {"kind": "raw", "text": json.dumps(node, ensure_ascii=False)}

    # ------------------------------------------------------------ calendar
    def release_label(self, entry: dict) -> str:
        zh = self.p.get("calendar_names_zh") or {}
        if self.loc == "zh" and not L.calendar_label_is_localized(entry, "zh", zh):
            self.missing.append(f"calendar name {entry['name']}")
        return L.calendar_label(entry, self.loc, zh)

    def release_name(self, name: str) -> str:
        """A release named by its English calendar name (e.g. in the baseline's committed_before)."""
        return self.release_label({"name": name, "period": None})

    # ------------------------------------------------------------ scenarios, limitations
    def scenarios(self) -> list[dict]:
        return [{"id": s["id"], "name": pick(s["name"], self.loc),
                 "rows": {k: pick(s["rows"][k], self.loc) for k in SCENARIO_ROWS}}
                for s in self.p.get("scenarios") or []]

    def scenario_table_html(self) -> str:
        sc = self.scenarios()
        if not sc:
            return ""
        head = "".join(f"<th>{escape(s['name'])}</th>" for s in sc)
        rows = "".join(
            f"<tr><th scope=\"row\">{escape(self.t('scenario.row.' + k))}</th>"
            + "".join(f"<td>{escape(s['rows'][k])}</td>" for s in sc) + "</tr>" for k in SCENARIO_ROWS)
        return (f'<div class="tablewrap scenario"><table class="scenarios"><thead><tr><th></th>{head}</tr></thead>'
                f"<tbody>{rows}</tbody></table></div>")

    def limitations(self) -> list[str]:
        return [pick(x, self.loc) for x in self.p.get("limitations") or []]

    # ------------------------------------------------------------ data sources
    def sources_status(self) -> list[dict]:
        out = []
        for s in (self.m.get("sources") or {}).get("sources", []):
            if s.get("show") is False:
                continue
            out.append({"id": s["id"], "name": pick(s["name"], self.loc), "status": s["status"],
                        "label": self.t(f"source_status.{s['status']}"), "url": s.get("url"),
                        "note": pick(s.get("note"), self.loc) or ""})
        return out
