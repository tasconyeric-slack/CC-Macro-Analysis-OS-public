"""Append-only inbox/reviews and point-in-time readers for the static site."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

BEIJING = timezone(timedelta(hours=8))
PUBLIC_STATUSES = {"verified", "analyst_approved"}


def stamp(value: str) -> datetime:
    result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return result.replace(tzinfo=BEIJING) if result.tzinfo is None else result


def rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def append(path: Path, records: list[dict]) -> None:
    if not records:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def raw_items(events_dir: Path) -> list[dict]:
    return [r for path in sorted((events_dir / "inbox").glob("*.jsonl")) for r in rows(path)]


def load_items(events_dir: Path, *, as_of: str) -> list[dict]:
    """Fold reviews and document revisions without leaking future collection/review."""
    cutoff = stamp(as_of)
    items = {r["item_id"]: dict(r) for r in raw_items(events_dir) if stamp(r["first_seen_at"]) <= cutoff}
    for review in rows(events_dir / "reviews.jsonl"):
        if stamp(review["reviewed_at"]) <= cutoff and review["item_id"] in items:
            items[review["item_id"]].update(status=review["status"], review=review)
    latest = {}
    for item in items.values():
        key = item["canonical_url"]
        if key not in latest or stamp(item["first_seen_at"]) >= stamp(latest[key]["first_seen_at"]):
            latest[key] = item
    return sorted(latest.values(), key=lambda r: (r.get("published_at") or "", r["item_id"]), reverse=True)


def load_public_items(events_dir: Path, *, as_of: str) -> list[dict]:
    cutoff = stamp(as_of)
    return [r for r in load_items(events_dir, as_of=as_of)
            if r["status"] in PUBLIC_STATUSES and r.get("published_at")
            and stamp(r["published_at"]) <= cutoff and not r.get("archived")]


def load_source_status(events_dir: Path, *, as_of: str) -> list[dict]:
    cutoff, latest = stamp(as_of), {}
    for run in rows(events_dir / "source_status.jsonl"):
        if stamp(run["retrieved_at"]) <= cutoff:
            latest[run["source"]] = run
    return list(latest.values())


def review_item(events_dir: Path, item_id: str, status: str, *, reviewer: str, reason: str, now: str) -> dict:
    if status not in {"verified", "rejected", "analyst_approved"}:
        raise ValueError("unsupported review status")
    if not reviewer.strip() or not reason.strip():
        raise ValueError("reviewer and reason are required")
    item = next((r for r in load_items(events_dir, as_of=now) if r["item_id"] == item_id), None)
    if item is None:
        raise ValueError("item does not exist at the review time or is superseded")
    if status in PUBLIC_STATUSES and (not item.get("published_at") or stamp(item["published_at"]) > stamp(now)):
        raise ValueError("a trustworthy, nonfuture publication date is required")
    if status == "analyst_approved" and item["status"] not in PUBLIC_STATUSES:
        raise ValueError("verify the official source before analyst approval")
    review = {"item_id": item_id, "status": status, "reviewer": reviewer.strip(),
              "reason": reason.strip(), "reviewed_at": now}
    append(events_dir / "reviews.jsonl", [review])
    return review
