"""Deterministic official occurrence grouping and excerpt-backed candidate triage."""
from __future__ import annotations

import hashlib
import itertools
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from .relations import resolve_pair
from .store import append, load_items, raw_items, rows, stamp

RULES = Path(__file__).resolve().parents[3] / "data/dictionary/event_rules.yaml"


def normalized(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKC", text) if c.isalnum()).lower()


def text(item):
    return item["title_zh"] + " " + (item.get("summary_zh") or "")


def is_roundup(item, rules):
    return bool(re.search(rules["roundup_pattern"], normalized(item["title_zh"])))


def document_names(item):
    return [normalized(s) for s in re.findall(r"《([^》]+)》", text(item)) if len(normalized(s)) >= 8]


def relation(a, b, rules):
    """Return a safe exact decision, or AMBIGUOUS without merging."""
    if a["canonical_url"] == b["canonical_url"]:
        return "SAME_OCCURRENCE", "same official document URL"
    ta, tb = normalized(a["title_zh"]), normalized(b["title_zh"])
    days = abs((stamp(a["published_at"]) - stamp(b["published_at"])).days)
    broad_a, broad_b = is_roundup(a, rules), is_roundup(b, rules)
    if ta == tb and len(ta) >= 12 and days <= 45:
        return "SAME_OCCURRENCE", "same specific title within the republication window"
    ba, bb = normalized(a.get("summary_zh") or ""), normalized(b.get("summary_zh") or "")
    if len(ba) >= 80 and ba == bb and days <= 7 and not (broad_a or broad_b):
        return "SAME_OCCURRENCE", "matching substantial source excerpt within the release window"
    period_a = re.search(r"(\d{1,2})月份?国民经济", a["title_zh"])
    period_b = re.search(r"(\d{1,2})月份?国民经济", b["title_zh"])
    if period_a and period_b and period_a[1] == period_b[1] and days <= 2:
        if any("答记者问" in r["title_zh"] for r in (a, b)):
            return "SAME_STORY", "source explicitly names the same monthly economic release in its follow-up Q&A"
    shared_name = next((name for name in document_names(a) if name in normalized(text(b))), None)
    shared_name = shared_name or next((name for name in document_names(b) if name in normalized(text(a))), None)
    if shared_name and days <= 180:
        if broad_a or broad_b:
            return "ROUNDUP", "a composite source includes the specific policy document"
        if re.search(rules["followup_pattern"], a["title_zh"] + b["title_zh"]):
            return "SAME_STORY", "explicit shared document with a source-stated follow-up or interpretation"
        return "AMBIGUOUS", "shared policy document, occurrence versus follow-up unresolved"
    if (broad_a or broad_b) and days <= 1:
        # A broad economic/fiscal briefing is composite, never an identity bridge.
        common = any(re.search(r["pattern"], text(a)) and re.search(r["pattern"], text(b)) for r in rules["hypotheses"])
        release_batch = (a["source"] == b["source"] == "nbs"
                         and abs((stamp(a["published_at"]) - stamp(b["published_at"])).total_seconds()) <= 300
                         and bool(a.get("metric_ids") or b.get("metric_ids")))
        if common or release_batch:
            return "ROUNDUP", "same-date composite briefing and a related single-topic item"
    if ta == tb or (len(ta) >= 16 and len(tb) >= 16 and (ta in tb or tb in ta) and days <= 45):
        return "AMBIGUOUS", "similar document title without sufficient occurrence identity"
    return "UNRELATED", "no explicit shared occurrence or directly supported follow-up"


def triage(item, rules):
    body = text(item)
    if re.search(rules["irrelevant"]["pattern"], body):
        return {"hypotheses": [], "triage": "irrelevant", "reason_zh": rules["irrelevant"]["reason_zh"],
                "reason_en": rules["irrelevant"]["reason_en"], "mechanism": [], "next_confirmation": []}
    links, mechanism, next_confirmation = [], [], []
    for rule in rules["hypotheses"]:
        match = re.search(rule["pattern"], body)
        if match:
            excerpt = body[max(0, match.start() - 25): min(len(body), match.end() + 60)]
            links.append({"hypothesis": rule["id"], "item_id": item["item_id"], "quote_zh": excerpt,
                          "rule_id": rules["version"] + ":" + rule["id"]})
            mechanism.append({"hypothesis": rule["id"], "zh": rule["mechanism_zh"], "en": rule["mechanism_en"]})
            next_confirmation.append({"hypothesis": rule["id"], "zh": rule["next_zh"], "en": rule["next_en"]})
    action = re.search(r"加力|上调|降准|降息|通知|印发|决定|下达", body)
    result = "research_needed" if links and action and item["kind"] != "data_release" else "monitor" if links else "irrelevant"
    return {"hypotheses": links, "triage": result, "mechanism": mechanism, "next_confirmation": next_confirmation,
            "reason_zh": "原文涉及研究假设；需确认后续数据与传导，尚非分析师结论。" if links else "原文未出现当前假设规则对应的工具或观测，保留来源但不纳入研究信号。",
            "reason_en": "The source touches a thesis mechanism; subsequent evidence and transmission remain to be checked." if links else "No current hypothesis rule matches a specific source tool or observation; retained as source context."}


def event_rows(events_dir, *, as_of):
    latest, retired = {}, set()
    for row in rows(events_dir / "events.jsonl"):
        if stamp(row["generated_at"]) <= stamp(as_of):
            latest[row["event_id"]] = row
            retired.update(row.get("supersedes", []))
    return [row for key, row in latest.items() if key not in retired]


def group_events(events_dir: Path, rules_path: Path = RULES, *, as_of: str | None = None, dry_run=False, client=None):
    as_of = as_of or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    rules = yaml.safe_load(rules_path.read_text(encoding="utf-8"))
    items = [r for r in raw_items(events_dir) if stamp(r["first_seen_at"]) <= stamp(as_of)
             and r.get("published_at") and stamp(r["published_at"]) <= stamp(as_of)]
    items.sort(key=lambda r: (r["first_seen_at"], r["canonical_url"], r["item_id"]))
    parent = list(range(len(items)))
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    related, ambiguous = [], []
    calls = 0
    for i, j in itertools.combinations(range(len(items)), 2):
        decision, why = relation(items[i], items[j], rules)
        if decision == "AMBIGUOUS":
            resolved = resolve_pair(client, events_dir, items[i], items[j], as_of=as_of) if client and not dry_run and calls < 10 else None
            if client and not dry_run and calls < 10:
                calls += 1
            if resolved:
                decision, why = resolved["relation"], resolved["reason"]
            else:
                ambiguous.append((i, j, why))
        if decision == "SAME_OCCURRENCE":
            parent[find(j)] = find(i)
        elif decision in {"SAME_STORY", "ROUNDUP"}:
            related.append((i, j, decision, why))
    groups = {}
    for i, item in enumerate(items):
        groups.setdefault(find(i), []).append(item)
    previous = event_rows(events_dir, as_of=as_of)
    current_ids = {r["item_id"] for r in load_items(events_dir, as_of=as_of)}
    old_by_member = {mid: r["event_id"] for r in previous for mid in r["member_item_ids"]}
    event_by_item, output = {}, []
    for members in groups.values():
        old_ids = sorted({old_by_member[m["item_id"]] for m in members if m["item_id"] in old_by_member})
        event_id = old_ids[0] if old_ids else "event_" + hashlib.sha256(members[0]["canonical_url"].encode()).hexdigest()[:20]
        for m in members:
            event_by_item[m["item_id"]] = event_id
        # Prefer the issuer's NBS/PBOC page over a gov.cn republication.
        primary = min(members, key=lambda m: (urlsplit(m["canonical_url"]).hostname == "www.gov.cn",
                                             m["item_id"] not in current_ids, -stamp(m["first_seen_at"]).timestamp(), m["canonical_url"]))
        info = triage(primary, rules)
        stage = "observed_impact" if primary["kind"] == "data_release" else next((s for s, pattern in rules["stages"].items() if re.search(pattern, text(primary))), "signal")
        event = {"event_id": event_id, "member_item_ids": sorted(m["item_id"] for m in members),
                 "primary_item_id": primary["item_id"], "source_urls": sorted({m["canonical_url"] for m in members}),
                 "relation": "SAME_OCCURRENCE" if len(members) > 1 else "ROUNDUP" if is_roundup(primary, rules) else "UNRELATED",
                 "stage": stage, **info, "figures": [], "related_events": [], "ambiguous_pairs": [],
                 "status": "candidate", "rules_version": rules["version"], "supersedes": old_ids[1:]}
        output.append(event)
    lookup = {r["event_id"]: r for r in output}
    for i, j, decision, why in related:
        a, b = event_by_item[items[i]["item_id"]], event_by_item[items[j]["item_id"]]
        if a != b:
            for left, right in ((a, b), (b, a)):
                edge = {"event_id": right, "relation": decision, "reason": why}
                if edge not in lookup[left]["related_events"]:
                    lookup[left]["related_events"].append(edge)
    for i, j, why in ambiguous:
        for left, right in ((i, j), (j, i)):
            pair = {"item_id": items[right]["item_id"], "reason": why, "status": "model_unavailable" if not client else "unresolved"}
            lookup[event_by_item[items[left]["item_id"]]]["ambiguous_pairs"].append(pair)
    prior = {r["event_id"]: r for r in previous}
    additions = []
    for event in output:
        old = {k: v for k, v in prior.get(event["event_id"], {}).items() if k != "generated_at"}
        if old != event:
            additions.append({**event, "generated_at": as_of})
    if not dry_run:
        append(events_dir / "events.jsonl", additions)
    return {"as_of": as_of, "items": len(items), "events": len(output), "new_revisions": len(additions),
            "ambiguous_pairs": len(ambiguous), "model_calls": calls}
