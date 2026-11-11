"""Research input bundle (#56): real captured records in, hypothesis-linked research inputs out.

The sandbox is assembled from records already in the repository (append-only intake), selected by id,
so the test exercises real sources without depending on how far the live feeds have rolled forward."""
import json
import shutil
from pathlib import Path

import pytest

from cnmacro.events.store import stamp

from cnmacro.research_inputs import (BundleError, build_bundle, latest_bundle, load_bundle, material_items,
                                     validate_bundle, write_bundle)

ROOT = Path(__file__).resolve().parents[1]
CASE = "research/cases/cn-nominal"
AS_OF = "2026-11-10T16:00:00Z"
CPI, PPI = "item_6022c78c7a6e631fbe06a524", "item_cf6bd6a21159001e7a993cf6"          # NBS first prints, 2026-11-09
SEP_CPI = "item_a426dd73791c564759995978"                                            # NBS Sep-2026 CPI print, 2026-10-14
NEWS_EVENTS = ("release-ppi-2026-10", "evt-3a136a4d76f8")   # media coverage of the PPI print; ECB member on French GDP
LATE_REP = "evt-4b3edd7f558f"      # tariff notice: a media member held 08:19Z, the official representative only at 11:36Z
NEWS_FIXTURE = ROOT / "tests/fixtures/research_inputs/news_latest.json"   # real records, frozen (the live feed rolls)


def _rows(path):
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


@pytest.fixture()
def root(tmp_path):
    shutil.copytree(ROOT / "data/dictionary", tmp_path / "data/dictionary")
    for p in ("preregistered", "case.yaml"):
        src = ROOT / CASE / p
        (shutil.copytree if src.is_dir() else shutil.copy)(src, tmp_path / CASE / p)
    (tmp_path / CASE / "refreshes").mkdir(parents=True)
    shutil.copy(ROOT / CASE / "refreshes/2026-11-09T0223Z.json", tmp_path / CASE / "refreshes")
    ev = tmp_path / "data/events"
    (ev / "inbox").mkdir(parents=True)
    items = [r for p in sorted((ROOT / "data/events/inbox").glob("*.jsonl")) for r in _rows(p) if r["item_id"] in (CPI, PPI)]
    (ev / "inbox/2026-11.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in items), encoding="utf-8")
    events = [r for r in _rows(ROOT / "data/events/events.jsonl") if set(r["member_item_ids"]) & {CPI, PPI}]
    (ev / "events.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in events), encoding="utf-8")
    feed = json.loads(NEWS_FIXTURE.read_text(encoding="utf-8"))
    keep = [e for e in feed["events"] if e["event_id"] in NEWS_EVENTS]
    ids = {i for e in keep for i in e["items"]}
    news = {**feed, "events": keep, "items": [i for i in feed["items"] if i["item_id"] in ids]}
    (tmp_path / "data/news/archive").mkdir(parents=True)
    (tmp_path / "data/news/latest.json").write_text(json.dumps(news, ensure_ascii=False), encoding="utf-8")
    assert len(items) == 2 and events and len(keep) == 2
    return tmp_path


def test_release_material_duplicate_and_noise_are_separated(root):
    b = build_bundle(root, AS_OF)
    by_id = {x["event_id"]: x for x in b["items"]}
    material = material_items(b)
    # the two official first prints are the research inputs: real URLs, tests and observations they changed
    assert {x["evidence_kind"] for x in material} == {"official_release"} and len(material) == 2
    ppi = next(x for x in material if "cn_ppi_yoy" in x["linked_metrics"])
    assert ppi["triage"] == "research_needed" and ppi["source_url"].startswith("https://www.stats.gov.cn/")
    assert "H1" in ppi["hypotheses"] and "obs:cn_ppi_yoy@2026-10" in ppi["observation_refs"]
    assert ppi["refresh_records"] == ["2026-11-09T0223Z.json"] and ppi["tests"]
    assert not any(ch.isdigit() for ch in ppi["why_relevant"].replace("T-H", "").split("tests")[0])
    # media coverage of the same print is a repetition, not a second economic change
    copy = by_id["release-ppi-2026-10"]
    assert copy["repetition_of"] == ppi["event_id"] and copy not in material
    # heat is not materiality: a multi-publisher foreign item is filtered
    ecb = by_id["evt-3a136a4d76f8"]
    assert ecb["coverage"] >= 3 and ecb["triage"] == "irrelevant" and ecb["hypotheses"] == []
    c = b["counts"]
    assert c["considered"] == c["research_needed"] + c["monitor"] + c["irrelevant"] + c["repetition"] == 4
    assert validate_bundle(b) == []


def test_bundle_is_written_once_and_loaded_point_in_time(root):
    b = build_bundle(root, AS_OF)
    p = write_bundle(root / CASE, b)
    with pytest.raises(FileExistsError):
        write_bundle(root / CASE, b)
    assert load_bundle(p)["bundle_id"] == "2026-11-10"
    assert latest_bundle(root / CASE, "2026-11-09T00:00:00Z") is None            # nothing before the bundle exists
    early = build_bundle(root, "2026-11-09T02:00:00Z")                            # before the prints were captured
    assert material_items(early) == []
    bad = {**b, "items": [{**b["items"][0], "available_at": "2026-12-01T00:00:00Z"}]}
    assert validate_bundle(bad)
    (root / CASE / "inputs/2026-11-30.json").write_text(json.dumps({**b, "kind": "x"}), encoding="utf-8")
    with pytest.raises(BundleError):
        latest_bundle(root / CASE, AS_OF)


def test_committed_bundle_is_valid_and_traceable():
    b = load_bundle(ROOT / CASE / "inputs/2026-11-10.json")
    material = material_items(b)
    assert any(x["evidence_kind"] == "official_release" and x["triage"] == "research_needed" for x in material)
    assert all(x["source_url"].startswith("https://") and x["hypotheses"] for x in material)
    assert b["counts"]["irrelevant"] > 0 and b["counts"]["repetition"] > 0


def test_a_release_gets_only_the_observations_of_its_own_print(root):
    """Two CPI prints in one window: each is credited with its own reference period, never the other's."""
    shutil.copy(ROOT / CASE / "refreshes/2026-10-14T0701Z.json", root / CASE / "refreshes")
    sep = [r for r in _rows(ROOT / "data/events/events.jsonl") if r["member_item_ids"] == [SEP_CPI]]   # Sep-2026 CPI print
    assert sep
    with open(root / "data/events/events.jsonl", "a", encoding="utf-8") as f:
        f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in sep)
    members = {i for r in sep for i in r["member_item_ids"]}
    rows = [r for p in sorted((ROOT / "data/events/inbox").glob("*.jsonl")) for r in _rows(p) if r["item_id"] in members]
    with open(root / "data/events/inbox/2026-11.jsonl", "a", encoding="utf-8") as f:
        f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    b = build_bundle(root, AS_OF, window_days=35)
    cpi = {x["published_at"][:7]: x["observation_refs"] for x in b["items"]
           if x["evidence_kind"] == "official_release" and x["triage"] == "research_needed" and "cn_cpi_yoy" in x["linked_metrics"]}
    assert cpi["2026-10"] and all(r.endswith("@2026-09") for r in cpi["2026-10"])
    assert cpi["2026-11"] and all(r.endswith("@2026-10") for r in cpi["2026-11"])


def test_a_news_group_never_shows_metadata_collected_after_as_of(root):
    feed = json.loads(NEWS_FIXTURE.read_text(encoding="utf-8"))
    ev = next(e for e in feed["events"] if e["event_id"] == LATE_REP)
    items = [i for i in feed["items"] if i["item_id"] in ev["items"]]
    (root / "data/news/latest.json").write_text(json.dumps({**feed, "events": [ev], "items": items}, ensure_ascii=False), encoding="utf-8")
    b = build_bundle(root, "2026-11-09T10:00:00Z", window_days=7)
    x = next(i for i in b["items"] if i["event_id"] == LATE_REP)
    assert "mof.gov.cn" in ev["url"]                         # the group's representative is the later official source...
    assert "mof.gov.cn" not in x["source_url"] and x["evidence_kind"] == "media_report"   # ...which the bundle never shows
    assert all(stamp(i["first_seen_at"]) <= stamp("2026-11-09T10:00:00Z") for i in items if i["canonical_url"] == x["source_url"])
