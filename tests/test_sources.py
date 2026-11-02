"""Data sources are stated as they are today: Wind is active only in local Private Research Mode, never in the public data path."""
import re

import yaml

from htmlutil import parse
from cnmacro.store import load_dictionary
from conftest import ROOT

SOURCES = yaml.safe_load((ROOT / "data/dictionary/sources.yaml").read_text(encoding="utf-8"))["sources"]
BY_ID = {s["id"]: s for s in SOURCES}


def test_every_metric_source_is_listed():
    for m in load_dictionary(ROOT / "data/dictionary/metrics.yaml").values():
        assert m.source_primary in BY_ID, f"{m.metric_id}: source {m.source_primary} is not in sources.yaml"


def test_status_values():
    assert {s["status"] for s in SOURCES} <= {"active", "private_pending"}
    for sid in ("NBS", "PBOC", "GACC", "FRED"):
        assert BY_ID[sid]["status"] == "active"
    assert BY_ID["Wind"]["status"] == "private_pending" and BY_ID["Wind"]["since"] == "V1.2"
    assert "planned" not in BY_ID["Wind"]           # delivered locally since V1.2, no longer a roadmap item


def test_only_active_sources_have_observations_in_the_public_store():
    import pandas as pd
    obs = pd.concat([pd.read_csv(f, dtype=str) for f in (ROOT / "data/demo/observations").glob("*.csv")])
    assert "Wind" not in set(obs["source"])
    assert set(obs["source"]) <= {s["id"] for s in SOURCES if s["status"] == "active"}


def test_pages_state_the_wind_public_private_boundary(built):
    for f in built.rglob("*.html"):
        text = f.read_text(encoding="utf-8")
        assert "Research runs privately with licensed data (Wind)" not in text, f
        assert "私下使用" not in text
    en = (built / "en/method.html").read_text(encoding="utf-8")
    assert "local-only V1.2 Phase 1 integration" in en
    assert "This public site is built only from official and open sources" in en
    zh = (built / "zh/method.html").read_text(encoding="utf-8")
    assert "已通过V1.2 Phase 1在本地接入万得（Wind）及授权研究资料" in zh
    assert "本公开站点仅基于官方和开放来源" in zh


def test_no_page_describes_delivered_wind_work_as_planned(built):
    """Wind private mode (V1.2 Phase 1 and 2) exists locally. The Method page, the Deep Dive and the data-source
    notes are written by hand in several files, so guard the rendered pages against the old 'planned for V1.2' claim."""
    stale = re.compile(r"planned.{0,60}V1\.2|V1\.2.{0,20}planned|计划在\s*V1\.2|规划中的私有研究模式|接入计划在", re.I)
    for f in built.rglob("*.html"):
        found = stale.search(parse(f).text(include_details=True))
        assert not found, f"{f.relative_to(built)}: stale Wind roadmap wording {found.group(0)!r}"


def test_data_sources_status_display(built):
    from htmlutil import parse
    for loc, pending in (("en", "private / local only"), ("zh", "私有 / 仅本地")):
        for page in ("index.html", "method.html"):
            text = parse(built / loc / page).text()
            for src in ("NBS", "PBOC", "GACC", "FRED"):
                assert re.search(rf"\b{src}\b.{{0,70}}?\b(active|运行中)", text), (loc, page, src)
            assert re.search(rf"\bWind\b.{{0,70}}?{pending}", text), (loc, page)
    # Nothing may imply that Wind is active in the public data path.
    for f in built.rglob("*.html"):
        text = parse(f).text(include_details=True)
        assert not re.search(r"Wind\s+(active|connected|运行中)", text), f
        assert "Wind public integration is active" not in text
