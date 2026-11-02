"""Locale helpers: dates, periods, calendar names, escaping, and the memo lint in both languages."""
import pytest

import localization as L
from cnmacro.checks import Check, lint_memo
from cnmacro.claims import period_tokens


def test_dates_and_times_are_written_in_each_languages_convention():
    assert L.fmt_when("2026-10-14T09:30:00+08:00", "en") == "14 Oct 2026, 09:30 Beijing"
    assert L.fmt_when("2026-10-14T09:30:00+08:00", "zh") == "2026年10月14日 09:30 北京时间"
    assert L.fmt_when("2026-10-04T06:00:00Z", "en") == "4 Oct 2026, 06:00 UTC"
    assert L.fmt_when("2026-10-04T06:00:00Z", "zh") == "2026年10月4日 06:00 UTC"
    assert L.fmt_when("2026-09-09", "zh") == "2026年9月9日" and L.fmt_date("2026-09-09", "en") == "9 Sep 2026"
    assert L.fmt_when(None, "zh") == "–" == L.fmt_when("", "en")


def test_periods():
    assert [L.fmt_period(p, "en") for p in ("2026-08", "2026Q2", "2025")] == ["Aug 2026", "2026 Q2", "2025"]
    assert [L.fmt_period(p, "zh") for p in ("2026-08", "2026Q2", "2025")] == ["2026年8月", "2026年二季度", "2025年"]
    assert L.fmt_period("2026-09", "en", long=True) == "September 2026"
    quarters = [f"{y}Q{q}" for y in (2024, 2025) for q in (1, 2, 3, 4)]
    assert L.fmt_periods(quarters, "en") == "2024 Q1 – 2025 Q4"          # a long run is a span
    assert L.fmt_periods(quarters, "zh") == "2024年一季度 – 2025年四季度"
    assert L.fmt_periods(["2026-08", "2025-12"], "zh") == "2026年8月、2025年12月"


def test_calendar_names():
    agenda = {"name": "2026-09 industrial profits (工业经济效益月度报告)", "period": "2026-09"}
    assert L.calendar_label(agenda, "en") == "2026-09 industrial profits"
    assert L.calendar_label(agenda, "zh") == "2026年9月工业经济效益月度报告"
    hand = {"name": "September 2026 CPI and PPI", "period": "2026-09"}
    assert L.calendar_label(hand, "en") == "September 2026 CPI and PPI"
    assert L.calendar_label(hand, "zh", {"September 2026 CPI and PPI": "2026年9月CPI和PPI"}) == "2026年9月CPI和PPI"
    assert not L.calendar_label_is_localized(hand, "zh", {})


def test_yaml_folding_leaves_no_gaps_inside_chinese_but_keeps_latin_spacing():
    assert L.tidy("出厂价格和 隐含GDP平减指数", "zh") == "出厂价格和隐含GDP平减指数"
    assert L.tidy("涨幅集中在生产资料，\n 生活资料价格", "zh") == "涨幅集中在生产资料，生活资料价格"
    assert L.tidy("核心 CPI 回落", "zh") == "核心 CPI 回落"
    assert L.tidy("two  words", "en") == "two  words"


def test_html_keys_escape_their_arguments():
    t = L.Translator("en", {"a_html": "<b>{x}</b>", "b": "{x}"})
    assert str(t("a_html", x="<script>")) == "<b>&lt;script&gt;</b>"
    assert t("b", x="<script>") == "<script>"      # plain keys are escaped later, by the template


def test_period_tokens_read_both_languages_alike():
    assert period_tokens("in 2026-05, 2026-06 and 2026Q2 against 2025") == {"2026-05", "2026-06", "2026Q2", "2025"}
    assert period_tokens("2026年5月为{a}，6月为{b}，二季度，2025年全年") == {"2026-05", "2026-06", "2026Q2", "2025"}
    assert period_tokens("自5月以来，2026年8月") == {"2026-08"}      # a month with no year before it is not guessed


@pytest.mark.parametrize("loc,line,fails", [
    ("en", "PPI rose to {x} in 2026-08.", False),
    ("en", "PPI rose 3.8% in August.", True),
    ("zh", "2026年8月PPI同比为{x}。", False),
    ("zh", "PPI同比上涨3.8%。", True),
    ("zh", "全年增长达到12%左右", True),
])
def test_memo_lint_catches_typed_numbers_in_both_languages(tmp_path, loc, line, fails):
    memo = tmp_path / f"memo.{loc}.md.j2"
    memo.write_text(f"## T\n\n{line}\n", encoding="utf-8")
    c = Check("E1", "x")
    lint_memo(memo, c, set(), loc)
    assert (c.status == "fail") == fails, c.details


def test_memo_lint_catches_an_unknown_claim(tmp_path):
    memo = tmp_path / "memo.zh.md.j2"
    memo.write_text('{{ c("NOPE-1") }}\n', encoding="utf-8")
    c = Check("E1", "x")
    lint_memo(memo, c, {"C-T-01"}, "zh")
    assert c.status == "fail" and "NOPE-1" in c.details[0]
