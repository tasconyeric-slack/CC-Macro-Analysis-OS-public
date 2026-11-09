import json
from pathlib import Path
from types import SimpleNamespace

import yaml

from cnmacro.events.grouping import RULES, event_rows, group_events, relation, text, triage
from cnmacro.events.relations import resolve_pair
from cnmacro.events.store import append, load_grouped_public_items, review_item

FIXTURES = Path(__file__).parent / "fixtures/events"
RULE_TABLE = yaml.safe_load(RULES.read_text(encoding="utf-8"))
NOW = "2026-11-09T04:00:00Z"


def gold_cases():
    return [json.loads(line) for line in (FIXTURES / "relation-gold.jsonl").read_text(encoding="utf-8").splitlines()]


def test_four_relations_use_actual_inbox_records():
    corpus = {r["item_id"]: r for r in [json.loads(line) for line in
              (Path(__file__).parents[1] / "data/events/inbox/2026-11.jsonl").read_text(encoding="utf-8").splitlines()]}
    assert {case["gold"]["relation"] for case in gold_cases()} == {"SAME_OCCURRENCE", "SAME_STORY", "UNRELATED", "ROUNDUP"}
    for case in gold_cases():
        assert case["a"] == corpus[case["a"]["item_id"]]
        assert case["b"] == corpus[case["b"]["item_id"]]
        assert relation(case["a"], case["b"], RULE_TABLE)[0] == case["gold"]["relation"]


def test_duplicate_event_is_idempotent_and_public_reader_cannot_leak_unreviewed_source(tmp_path):
    case = gold_cases()[0]
    append(tmp_path / "inbox/2026-11.jsonl", [case["a"], case["b"]])
    result = group_events(tmp_path, as_of=NOW)
    assert result["events"] == 1
    before = (tmp_path / "events.jsonl").read_bytes()
    assert group_events(tmp_path, as_of="2026-11-09T04:01:00Z")["new_revisions"] == 0
    assert (tmp_path / "events.jsonl").read_bytes() == before
    assert not load_grouped_public_items(tmp_path, as_of=NOW)


def test_announced_policy_and_implementation_stay_distinct(tmp_path):
    # Explicit synthetic mutations test a stage boundary; never used as real gold/public items.
    base = gold_cases()[0]["a"]
    a = {**base, "item_id": "synthetic-announcement", "title_zh": "关于印发《特定财政支持政策》的通知", "summary_zh": "特定财政支持政策发布", "canonical_url": "https://www.gov.cn/policy-a", "published_at": "2026-10-01"}
    b = {**base, "item_id": "synthetic-implementation", "title_zh": "《特定财政支持政策》实施细则", "summary_zh": "特定财政支持政策的实施细则", "canonical_url": "https://www.gov.cn/policy-b", "published_at": "2026-10-02"}
    assert relation(a, b, RULE_TABLE)[0] == "SAME_STORY"
    append(tmp_path / "inbox/2026-11.jsonl", [a, b])
    assert group_events(tmp_path, as_of=NOW)["events"] == 2
    events = event_rows(tmp_path, as_of=NOW)
    assert {r["stage"] for r in events} == {"announced", "implementation"}
    assert all(r["related_events"][0]["relation"] == "SAME_STORY" for r in events)


def test_all_hypothesis_links_are_literal_and_irrelevance_has_reason():
    for case in gold_cases():
        for item in (case["a"], case["b"]):
            result = triage(item, RULE_TABLE)
            assert result["reason_zh"] and result["reason_en"]
            for h in result["hypotheses"]:
                assert h["quote_zh"] in text(item)
                assert h["hypothesis"] in {"H0", "H1", "H2", "H3", "H4"}
    meeting = gold_cases()[2]["b"]
    assert triage(meeting, RULE_TABLE)["triage"] == "irrelevant"


def test_issuer_page_preferred_but_both_links_preserved(tmp_path):
    a = gold_cases()[2]["a"]
    b = {**a, "item_id": "synthetic-republication", "publisher": "gov.cn", "canonical_url": "https://www.gov.cn/republication", "source": "gov_fiscal"}
    append(tmp_path / "inbox/2026-11.jsonl", [a, b])
    group_events(tmp_path, as_of=NOW)
    event = event_rows(tmp_path, as_of=NOW)[0]
    assert event["primary_item_id"] == a["item_id"]
    assert len(event["source_urls"]) == 2
    review_item(tmp_path, a["item_id"], "verified", reviewer="source-check", reason="synthetic test verification", now=NOW)
    public = load_grouped_public_items(tmp_path, as_of=NOW)
    assert len(public) == 1 and public[0]["canonical_url"] == a["canonical_url"]
    assert all(h["item_id"] == a["item_id"] for h in public[0]["hypothesis_links"])


def test_ambiguous_pair_is_not_merged_without_a_model(tmp_path):
    a = gold_cases()[0]["a"]
    a = {**a, "item_id": "synthetic-old", "published_at": "2026-01-01"}
    b = {**a, "item_id": "synthetic-new", "published_at": "2026-10-01", "canonical_url": "https://www.gov.cn/other"}
    append(tmp_path / "inbox/2026-11.jsonl", [a, b])
    result = group_events(tmp_path, as_of=NOW)
    assert result["events"] == 2 and result["ambiguous_pairs"] == 1 and result["model_calls"] == 0
    assert all(r["ambiguous_pairs"][0]["status"] == "model_unavailable" for r in event_rows(tmp_path, as_of=NOW))


def test_model_tie_records_schema_failure_and_success_separately(tmp_path):
    class Client:
        genuine = False
        def __init__(self, response): self.response = response
        def identity(self): return {"requested_id": "synthetic-test-client"}
        def call(self, system, user):
            return SimpleNamespace(text=json.dumps(self.response), raw={"synthetic": True}, usage={}, latency_ms=0)
    a, b = gold_cases()[2]["a"], gold_cases()[2]["b"]
    assert resolve_pair(Client({"relation": "UNRELATED", "reason": "独立发生"}), tmp_path, a, b, as_of=NOW)
    assert resolve_pair(Client({"relation": "SAME_OCCURRENCE", "reason": "发生了2次"}), tmp_path, a, b, as_of=NOW) is None
    records = list((tmp_path / "relation_model/samples").glob("*/record.json"))
    assert len(records) == 2
    assert {json.loads(p.read_text(encoding="utf-8"))["validation"]["passed"] for p in records} == {True, False}


def test_background_mention_of_implementation_does_not_create_a_followup():
    a = {**gold_cases()[0]["a"], "canonical_url": "https://www.gov.cn/a", "title_zh": "关于《特定政策文件名称》的通知", "summary_zh": "贯彻落实有关部署"}
    b = {**a, "canonical_url": "https://www.gov.cn/b", "title_zh": "《特定政策文件名称》", "summary_zh": "贯彻落实有关部署"}
    assert relation(a, b, RULE_TABLE)[0] == "AMBIGUOUS"
