import json
from pathlib import Path

import pytest

from cnmacro.events.intake import MAX_BYTES, SOURCES, intake, parse_gov, parse_nbs, parse_pboc, plain, publication
from cnmacro.events.store import load_items, load_public_items, load_source_status, raw_items, review_item

FIXTURES = Path(__file__).parent / "fixtures/events"
NOW = "2026-11-09T03:00:00+00:00"


def body(source):
    return (FIXTURES / {"nbs": "nbs-rss.xml", "pboc": "pboc-news.html", "gov_fiscal": "gov-policy.json"}[source]).read_bytes()


def reader(url):
    return body(next(k for k, v in SOURCES.items() if v[0] == url))


def snapshot(root):
    return {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_real_official_dates_and_metrics():
    records = parse_nbs(body("nbs"), NOW)
    prices = [r for r in records if "cn_cpi_yoy" in r["metric_ids"] or "cn_ppi_yoy" in r["metric_ids"]]
    assert len(prices) >= 2
    assert all(r["published_at"].startswith("2026-11-09T09:30:") and r["published_at"].endswith("+08:00") for r in prices)
    assert all(r["status"] == "raw_candidate" and not r["archived"] for r in prices)
    assert all(len(r["summary_zh"]) <= 300 and r["tier"] == "EVENT" for r in records)
    pboc = parse_pboc(body("pboc"), NOW)
    assert len(pboc) == 15
    assert pboc[0]["published_at"] == "2026-11-05T16:26:23+08:00"
    assert pboc[0]["archived"]
    gov = parse_gov(body("gov_fiscal"), NOW, "gov_fiscal")
    assert len(gov) == 8 and gov[0]["publication_precision"] == "date"
    assert plain("2024年我国研究与试验发展（R&D）经费超过3.6万亿元").startswith("2024年我国研究")


def test_repeat_run_changes_no_artifacts(tmp_path):
    first = intake(tmp_path, now=NOW, reader=reader)
    original = snapshot(tmp_path)
    second = intake(tmp_path, now="2026-11-09T03:10:00Z", reader=reader)
    assert first["new_items"] == len(raw_items(tmp_path)) > 15
    assert second["new_items"] == 0
    assert snapshot(tmp_path) == original
    assert not load_public_items(tmp_path, as_of=NOW)


def test_failure_is_not_empty_success_and_next_run_backfills(tmp_path):
    def fail_nbs(url):
        if url == SOURCES["nbs"][0]:
            raise OSError("simulated source unavailable")
        return reader(url)
    first = intake(tmp_path, now=NOW, reader=fail_nbs)
    assert first["sources"][0]["ok"] is False
    assert "unavailable" in first["sources"][0]["error"]
    assert "nbs" not in json.loads((tmp_path / "cursors.json").read_text())
    second = intake(tmp_path, now="2026-11-09T03:01:00Z", reader=reader)
    assert second["sources"][0]["new_items"] > 0
    assert second["sources"][1]["new_items"] == 0
    assert load_source_status(tmp_path, as_of=NOW)[0]["ok"] is False
    assert load_source_status(tmp_path, as_of="2026-11-09T03:02:00Z")[0]["ok"] is True


def test_review_is_append_only_point_in_time_and_separate_from_judgment(tmp_path):
    intake(tmp_path, now=NOW, reader=reader)
    original = snapshot(tmp_path)
    current = next(r for r in load_items(tmp_path, as_of=NOW) if not r["archived"])
    with pytest.raises(ValueError, match="verify"):
        review_item(tmp_path, current["item_id"], "analyst_approved", reviewer="analyst", reason="test", now=NOW)
    review_item(tmp_path, current["item_id"], "verified", reviewer="source-reviewer", reason="URL and Beijing source date checked", now="2026-11-09T03:01:00Z")
    assert not load_public_items(tmp_path, as_of=NOW)
    public = load_public_items(tmp_path, as_of="2026-11-09T03:02:00Z")
    assert len(public) == 1 and public[0]["status"] == "verified"
    assert all(snapshot(tmp_path)[p] == content for p, content in original.items())
    assert not load_items(tmp_path, as_of="2026-11-08T23:00:00Z")


def test_missing_date_quarantined_and_future_publication_cannot_be_verified(tmp_path):
    data = body("nbs").replace(b"<pubDate>", b"<unknown>").replace(b"</pubDate>", b"</unknown>").replace(b"<pubTime>", b"<unknownTime>").replace(b"</pubTime>", b"</unknownTime>")
    intake(tmp_path, now=NOW, reader=lambda url: data if url == SOURCES["nbs"][0] else body("pboc"))
    r = next(r for r in raw_items(tmp_path) if r["source"] == "nbs")
    assert r["quarantined"] and r["published_at"] is None
    with pytest.raises(ValueError, match="publication date"):
        review_item(tmp_path, r["item_id"], "verified", reviewer="source", reason="not possible", now=NOW)
    assert publication("2026-02-30") == (None, "unknown")
    assert publication("2026-11-09")[1] == "date"


def test_large_feed_and_oversized_response_fail_explicitly(tmp_path):
    real_feed = body("nbs")
    large_feed = real_feed.replace(b"</channel>", b" " * 4_100_000 + b"</channel>")
    assert len(parse_nbs(large_feed, NOW)) == len(parse_nbs(real_feed, NOW))
    result = intake(tmp_path, now=NOW, reader=lambda url: b"x" * (MAX_BYTES + 1))
    assert all(not row["ok"] and "16MB" in row["error"] for row in result["sources"])
    assert not raw_items(tmp_path)


def test_canonical_official_urls_reject_untrusted_sources():
    from cnmacro.events.intake import canonical_url
    assert canonical_url("http://www.stats.gov.cn/release.html?id=1&utm_source=x#top") == "https://www.stats.gov.cn/release.html?id=1"
    with pytest.raises(ValueError):
        canonical_url("https://not-official.example/release")


def test_event_writer_refuses_research_and_history_replacement(monkeypatch):
    scripts = str(Path(__file__).parents[1] / "scripts")
    monkeypatch.syspath_prepend(scripts)
    import commit_official_events as writer
    monkeypatch.setattr(writer.verified, "git", lambda *args: b"A\0data/demo/observations/x.csv\0")
    with pytest.raises(RuntimeError, match="allowlist"):
        writer.staged_changes()
    def git(*args):
        if args[0] == "diff": return b"M\0data/events/inbox/2026-11.jsonl\0"
        if args[0] == "ls-files": return b"100644 hash 0 path"
        return b'{"new":1}\n' if args[1].startswith(":") else b'{"old":1}\n'
    monkeypatch.setattr(writer.verified, "git", git)
    with pytest.raises(RuntimeError, match="append-only"):
        writer.staged_changes()


def test_policy_view_does_not_inject_live_events_into_replay_or_synthetic(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "site"))
    import official_inbox
    def forbidden(*args, **kwargs):
        pytest.fail("replay attempted to read live event artifacts")
    monkeypatch.setattr(official_inbox, "load_grouped_items", forbidden)
    base = {"preview": False, "case_dir": Path("/replay/case"), "built_at": NOW}
    assert official_inbox.policy_inbox(base, "zh")["total"] == 0
    assert official_inbox.policy_inbox({**base, "preview": True}, "en")["total"] == 0
