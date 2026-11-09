"""Explicit source verification is separate from analyst approval."""
import json
from datetime import datetime, timezone
from pathlib import Path

from .intake import intake
from .store import review_item


def cmd_intake(args):
    summary = intake(Path(args.events_dir), dry_run=args.dry_run, include_gov=args.gov)
    text = json.dumps(summary, indent=2, ensure_ascii=False)
    print(text)
    if args.summary:
        Path(args.summary).write_text(text + "\n", encoding="utf-8")
    return 1 if any(not r["ok"] for r in summary["sources"]) else 0


def cmd_review(args):
    status = "verified" if args.verify else "rejected" if args.reject else "analyst_approved"
    result = review_item(Path(args.events_dir), args.item_id, status, reviewer=args.reviewer,
                         reason=args.reason, now=datetime.now(timezone.utc).replace(microsecond=0).isoformat())
    print(json.dumps(result, ensure_ascii=False))
    return 0


def cmd_group(args):
    from .grouping import RULES, group_events
    client = None
    if args.model:
        from cnmacro.copilot.llm import DeepSeekClient, ModelUnavailable
        try:
            client = DeepSeekClient(model=args.model, max_tokens=1200, timeout=90)
        except ModelUnavailable:
            print("Model unavailable; ambiguous pairs remain separate and flagged.")
    summary = group_events(Path(args.events_dir), Path(args.rules) if args.rules else RULES,
                           dry_run=args.dry_run, client=client)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def register(sub):
    parser = sub.add_parser("intake", help="collect official text candidates, separate from observations")
    parser.add_argument("--events-dir", default="data/events")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--gov", action="store_true", help="also query the authorized gov.cn policy library")
    parser.add_argument("--summary")
    parser.set_defaults(f=cmd_intake)
    parser = sub.add_parser("events", help="append official-source verification or analyst-review decisions")
    actions = parser.add_subparsers(dest="events_action", required=True)
    review = actions.add_parser("review")
    review.add_argument("item_id")
    review.add_argument("--events-dir", default="data/events")
    choice = review.add_mutually_exclusive_group(required=True)
    choice.add_argument("--verify", action="store_true", help="source/date verification only; not analyst judgment")
    choice.add_argument("--reject", action="store_true")
    choice.add_argument("--approve", action="store_true", help="analyst approval after source verification")
    review.add_argument("--reviewer", required=True)
    review.add_argument("--reason", required=True)
    review.set_defaults(f=cmd_review)
    group = actions.add_parser("group", help="group official occurrences and attach candidate triage")
    group.add_argument("--events-dir", default="data/events")
    group.add_argument("--rules")
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--model", choices=["deepseek-flash", "deepseek-v4-pro"], help="optional bounded tie-break; never required")
    group.set_defaults(f=cmd_group)
