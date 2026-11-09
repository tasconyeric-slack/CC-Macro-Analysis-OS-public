"""Explicit policy comparison and review commands, isolated from refresh-public."""
import json
from pathlib import Path

from . import policy_delta as delta
from .copilot import records
from .copilot.llm import DEFAULT_MODEL, DeepSeekClient, ModelUnavailable
from .ingest import now_iso


def _pair(args):
    pairs = delta.load_comparisons(Path(args.events_dir), Path(args.lexicon), as_of=now_iso())
    return next((p for p in pairs if p["comparison_id"] == args.comparison), None)


def execute(args):
    root = Path(args.events_dir) / "policy_copilot"
    try:
        if args.policy_action in {"diff", "run"}:
            pair = _pair(args)
            if pair is None: raise ValueError("comparison is unavailable at the current as-of time")
            if args.policy_action == "diff": result = pair
            else:
                client, unavailable = None, "no model requested"
                try:
                    client = DeepSeekClient(model=args.model, max_tokens=16000, timeout=120)
                except ModelUnavailable as ex: unavailable = ex.kind
                rec, directory = delta.run_interpretation(delta.interpretation_context(pair), root, client=client, unavailable=unavailable)
                result = {"run_id": rec["run_id"], "status": rec["status"], "genuine_model_run": rec["genuine_model_run"],
                          "validation": rec["validation"], "directory": str(directory), "content": "private candidate; use policy-delta show for explicit review"}
        else:
            directory = records.find_run(root, args.run_id)
            if args.policy_action == "show": result = records.load_run(directory)[0]
            else:
                edited = json.loads(Path(args.edited).read_text(encoding="utf-8")) if args.edited else None
                out = delta.review_run(directory, args.action, reviewer=args.reviewer, reason=args.reason, edited=edited)
                result = {"review": str(out), "action": args.action, "thesis_changed": False}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, records.RecordError) as ex:
        print(json.dumps({"error": str(ex)}, ensure_ascii=False))
        return 1


def register(sub):
    parser = sub.add_parser("policy-delta", help="compare sourced official policy text; append explicit analyst reviews")
    actions = parser.add_subparsers(dest="policy_action", required=True)
    for name in ("diff", "run", "show", "review"):
        p = actions.add_parser(name)
        p.add_argument("--events-dir", default="data/events")
        p.set_defaults(f=execute)
        if name in {"diff", "run"}:
            p.add_argument("--comparison", default="pboc-mpc-2026q2-to-q3")
            p.add_argument("--lexicon", default="data/dictionary/policy_lexicon.yaml")
        if name == "run": p.add_argument("--model", default=DEFAULT_MODEL)
        if name in {"show", "review"}: p.add_argument("run_id")
        if name == "review":
            p.add_argument("--action", choices=sorted(delta.ACTIONS), required=True)
            p.add_argument("--reviewer", required=True)
            p.add_argument("--reason", required=True)
            p.add_argument("--edited", help="JSON file containing the complete edited interpretation; action=edit only")
