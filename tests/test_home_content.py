"""The homepage answers 'what is the view?' first and keeps system detail progressive."""
import re

import pytest

from conftest import LOCALES
from htmlutil import parse


@pytest.mark.parametrize("loc", LOCALES)
def test_the_view_comes_before_the_system(built, loc):
    text = parse(built / loc / "index.html").text()
    t = {"en": dict(view="Current view", states="Where each hypothesis stands", evidence="Key evidence", system="How this view is kept honest",
                    prereg="Preregistered at", audit="Audit trail", ev="Deterministic eval|deterministic eval"),
         "zh": dict(view="当前判断", states="各假设目前的状态", evidence="关键证据", system="这一判断如何保持严谨",
                    prereg="预先登记：概率", audit="审计轨迹", ev="确定性评估")}[loc]
    order = [text.index(t["view"]), text.index(t["states"]), text.index(t["evidence"])]
    assert order == sorted(order), order
    raw = (built / loc / "index.html").read_text(encoding="utf-8")
    assert '<details class="system reader-method">' in raw
    # Technical material is accessible in the collapsed secondary layer.
    for later in (t["prereg"], t["audit"]):
        assert raw.index(later) > raw.index(t["system"]), later
    assert re.search(t["ev"], raw) and re.search(t["ev"], raw).start() > raw.index(t["system"])


def test_first_screen_shows_the_required_figures_and_the_probability_label(built):
    en = parse(built / "en/index.html").text()
    head = en[: en.index("Where each hypothesis stands")]
    for needle in ("Current macro view", "Is China forming a sustainable turning point in nominal growth?",
                   "The price side has turned, but broad domestic-demand confirmation is still absent",
                   "more consistent with an upstream- and external-price-led nominal rebound than with a durable, demand-led reflation",
                   "Analyst probability 30%", "Judgment confidence LOW", "Status ACTIVE", "Evidence as of", "Latest data refresh",
                   "Discretionary analyst judgment on a 5ppt grid; not a statistically calibrated model probability."):
        assert needle in head, needle
    zh = parse(built / "zh/index.html").text()
    head = zh[: zh.index("各假设目前的状态")]
    for needle in ("中国名义增长是否正在形成可持续拐点？", "价格端已经转向，但内需尚未出现广泛的确认", "分析师概率 30%",
                   "判断置信度 低", "状态 进行中", "证据截至", "最近一次数据刷新",
                   "分析师主观判断，以5个百分点为刻度；并非经统计校准的模型概率。"):
        assert needle in head, needle


@pytest.mark.parametrize("loc", LOCALES)
def test_the_five_hypotheses_are_shown_with_a_state_each(built, loc):
    text = parse(built / loc / "index.html").text()
    for h in ("H1", "H2", "H3", "H4", "H0"):
        assert re.search(rf"\b{h}\b", text)
    html = (built / loc / "index.html").read_text(encoding="utf-8")
    assert len(re.findall(r'class="hcell tone-', html)) == 5
    assert len(re.findall(r'class="pill tone-', html)) == 5


@pytest.mark.parametrize("loc", LOCALES)
def test_technical_refs_and_source_codes_are_not_shown_by_default(built, loc):
    """obs:/drv: refs, long source codes and commit hashes belong in collapsed technical lineage."""
    page = parse(built / loc / "index.html")
    visible = page.text(include_details=False)
    assert not re.search(r"\b(obs|drv|nbs):", visible), re.findall(r".{20}\b(?:obs|drv|nbs):.{20}", visible)[:3]
    assert not re.search(r"[0-9a-f]{32}", visible)
    # ... but they are all still there on request
    full = page.text(include_details=True)
    assert re.search(r"obs:cn_ppi_yoy@2026-08", full) and re.search(r"nbs:[0-9a-f]{32}", full)
    # human-readable provenance is what is shown instead
    if loc == "en":
        assert "National Bureau of Statistics · PPI YoY" in visible and "released 9 Sep 2026" in visible
    else:
        assert "国家统计局 · 工业生产者出厂价格指数同比" in visible and "2026年9月9日发布" in visible


@pytest.mark.parametrize("loc", LOCALES)
def test_evidence_and_chart_pages_hide_codes_by_default_too(built, loc):
    for name in ("evidence.html", "charts.html", "memo.html"):
        visible = parse(built / loc / name).text(include_details=False)
        assert not re.search(r"\b(obs|drv|nbs):", visible), (loc, name)
        assert not re.search(r"[0-9a-f]{32}", visible), (loc, name)


@pytest.mark.parametrize("loc", LOCALES)
def test_terminal_rules_are_words_first_and_json_is_collapsed(built, loc):
    page = parse(built / loc / "evidence.html")
    visible = page.text(include_details=False)
    assert '"when"' not in visible and '"test"' not in visible and "{" not in visible.split("rules")[-1][:2000]
    full = page.text(include_details=True)
    assert '"when"' in full and '"at_least"' in full                   # the raw rule is still there on request
    if loc == "en":
        for needle in ("Confirmed", "Falsified", "Falsified early", "At least 3 of these 6 hold", "Test fails", "Test passes", "satisfied so far"):
            assert needle in visible, needle
    else:
        for needle in ("确认", "证伪", "提前证伪", "以下 6 项中至少 3 项成立", "检验未通过", "检验通过", "目前已满足"):
            assert needle in visible, needle


def test_deep_dive_has_no_internal_project_language_and_no_recommendations(built):
    en = parse(built / "en/memo.html").text(include_details=True)
    zh = parse(built / "zh/memo.html").text(include_details=True)
    for banned in ("downstream bank model", "the downstream bank", "Duration should not", "is better tied to"):
        assert banned not in en, banned
    assert "下游银行模型" not in zh
    for must in ("conditional research implications", "not recommendations", "China rates", "CNY", "Banks",
                 "Confirming evidence", "Falsifying evidence"):
        assert must in en, must
    for must in ("研究含义（有条件）", "既不是投资建议", "中国利率", "人民币", "银行", "确认性证据", "证伪性证据"):
        assert must in zh, must
    assert "Strongest evidence" not in parse(built / "en/index.html").text(include_details=True)


def test_deep_dive_surfaces_marginal_momentum_behind_cumulative_figures(built):
    en = parse(built / "en/memo.html").text(include_details=True)
    assert "latest single month is running below the cumulative rate" in en
    assert "overstates current profit momentum" in en
    assert "Year-to-date industrial profit growth has slowed in every month since May" in en


def test_deep_dive_reads_as_numbered_references_not_claim_ids(built):
    html = (built / "en/memo.html").read_text(encoding="utf-8")
    body = html[html.index('<article class="memo">'): html.index("</article>")]
    assert not re.search(r"\[(C|I)-", body), "claim ids leak into the article text"
    assert len(re.findall(r'<sup class="cite"><a href="#ref-\d+"', body)) >= 25
    refs = parse(built / "en/memo.html")
    assert len([i for i in refs.ids if i.startswith("ref-")]) >= 25


def policy_events():
    import yaml
    from conftest import CASE
    return yaml.safe_load((CASE / "policy_events.yaml").read_text(encoding="utf-8"))["events"]


def test_chinese_pages_contain_no_stray_spaces_inside_sentences(built):
    """YAML line-folding must not leave 'word word' gaps inside Chinese text."""
    for f in (built / "zh").glob("*.html"):
        html = re.sub(r"<(script|style)\b.*?</\1>", "", f.read_text(encoding="utf-8"), flags=re.S)
        html = re.sub(r"<q\b[^>]*>.*?</q>", "", html, flags=re.S)  # preserve literal official excerpts
        for e in policy_events():                      # an official headline may contain its own space
            html = html.replace(e["official_headline_zh"], "")
        html = re.sub(r"<q\b[^>]*>.*?</q>", "", html, flags=re.S)  # Literal source excerpts preserve original spacing.
        hits = re.findall(r".{6}[\u4e00-\u9fff] [\u4e00-\u9fff].{6}", html)
        assert not hits, (f.name, hits[:3])
