"""Authoring script for the claims ledger (claims.jsonl).

Claims are written here as code so that every number is a bound ref, never typed. Each claim
is ONE record with two texts (text_en, text_zh): ids, bindings, refs, supports and stance are
shared, so a language can never fork the evidence. Units are the only thing shown in the reader's
language (" USD" -> 美元); the numbers are the same.

Run: python research/cases/cn-nominal/build_claims.py --as-of <ISO time> [--post-baseline-as-of <ISO time>]
then: python -m cnmacro fill-claims --public
New claims after the baseline are appended with their own, later as_of; ids are never reused.
A baseline-era claim keeps its English text exactly as the baseline fingerprinted it; better wording
goes in presentation.yaml, or in a NEW claim id with a later as_of (tests/test_claims_i18n.py enforces it).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
from cnmacro.claims import Binding, Claim, save_claims  # noqa: E402

DEFL = "deflator_yoy(cn_ngdp_q,cn_rgdp_yoy)"
PCT = dict(fmt="+.1f", suffix="%")
PCT_PLAIN = dict(fmt=".1f", suffix="%")
IDX = dict(fmt=".1f", suffix="")

def b(ref, **fmt):
    return Binding(ref=ref, **(fmt or PCT))


def claims(as_of: str, post_as_of: str) -> list[Claim]:
    C = lambda **k: Claim(as_of=k.pop("as_of", as_of), **k)  # noqa: E731
    neg_quarters = [f"drv:{DEFL}@{y}Q{q}" for y in range(2023, 2027) for q in range(1, 5)
                    if (y, q) >= (2023, 2) and (y, q) <= (2026, 1)]
    return [
        # ---------------- target / H1 ----------------
        C(id="C-T-01", type="DERIVED", hypotheses=["H1"], stance="for",
          text_en="The implied GDP deflator turned positive at {q2} year on year in 2026Q2, from {q1} in 2026Q1, "
                  "after negative readings in every quarter from 2023Q2 to 2026Q1.",
          text_zh="隐含GDP平减指数同比在2026年二季度转正，为{q2}，2026年一季度为{q1}；此前2023年二季度至2026年一季度各季均为负值。",
          values={"q2": b(f"drv:{DEFL}@2026Q2"), "q1": b(f"drv:{DEFL}@2026Q1")}, refs=neg_quarters),
        C(id="C-T-02", type="FACT", hypotheses=["H1", "H2"], stance="context",
          text_en="Real GDP grew {rg} year on year in 2026Q2, down from {rg1} in 2026Q1.",
          text_zh="2026年二季度实际GDP同比增长{rg}，较一季度的{rg1}有所回落。",
          values={"rg": b("obs:cn_rgdp_yoy@2026Q2", **PCT_PLAIN), "rg1": b("obs:cn_rgdp_yoy@2026Q1", **PCT_PLAIN)}),
        C(id="C-H1-01", type="FACT", hypotheses=["H1"], stance="for",
          text_en="PPI was {p} year on year in 2026-08, against {p0} in 2025-12: factory-gate prices have moved "
                  "from deflation to inflation within the year.",
          text_zh="2026年8月PPI同比为{p}，2025年12月为{p0}：出厂价格已在一年之内由通缩转为通胀。",
          values={"p": b("obs:cn_ppi_yoy@2026-08"), "p0": b("obs:cn_ppi_yoy@2025-12")}),
        C(id="C-H1-02", type="FACT", hypotheses=["H1"], stance="against",
          text_en="Month-on-month PPI momentum has faded: {m4} in 2026-04, then {m6} in 2026-06, {m7} in 2026-07 "
                  "and {m8} in 2026-08.",
          text_zh="PPI环比动能有所减弱：2026年4月为{m4}，6月为{m6}，7月为{m7}，8月为{m8}。",
          values={"m4": b("obs:cn_ppi_mom@2026-04"), "m6": b("obs:cn_ppi_mom@2026-06"),
                  "m7": b("obs:cn_ppi_mom@2026-07"), "m8": b("obs:cn_ppi_mom@2026-08")}),
        C(id="C-H1-03", type="FACT", hypotheses=["H1"], stance="for",
          text_en="Industrial profits were {pr} year on year, year to date, in 2026-08, after {pr0} for 2025 as a whole.",
          text_zh="截至2026年8月，规模以上工业企业利润累计同比为{pr}，2025年全年为{pr0}。",
          values={"pr": b("obs:cn_ind_profit_ytd_yoy@2026-08"), "pr0": b("obs:cn_ind_profit_ytd_yoy@2025-12")}),
        C(id="C-H1-05", type="FACT", hypotheses=["H1"], stance="for",
          text_en="The PMI output price index rose to {op} in 2026-09 from {op7} in 2026-07, a sign that factory-gate "
                  "momentum picked up again going into the September PPI release.",
          text_zh="制造业PMI出厂价格指数由2026年7月的{op7}升至9月的{op}，显示在9月PPI公布前出厂价格动能再度回升。",
          values={"op": b("obs:cn_pmi_output_price@2026-09", **IDX), "op7": b("obs:cn_pmi_output_price@2026-07", **IDX)}),
        C(id="C-H1-04", type="FACT", hypotheses=["H1", "H2"], stance="context",
          text_en="Consumer prices remain subdued: CPI was {c} and core CPI {k} year on year in 2026-08.",
          text_zh="消费价格仍然偏弱：2026年8月CPI同比为{c}，核心CPI同比为{k}。",
          values={"c": b("obs:cn_cpi_yoy@2026-08"), "k": b("obs:cn_core_cpi_yoy@2026-08")}),
        # ---------------- H0 supply-led ----------------
        C(id="C-H0-01", type="FACT", hypotheses=["H0"], stance="for",
          text_en="Brent averaged {b5} a barrel in 2026-05 and {b7} in 2026-07, against {b0} in 2025-12.",
          text_zh="布伦特原油均价2026年5月为{b5}/桶，7月为{b7}/桶，2025年12月为{b0}/桶。",
          values={"b5": b("obs:gl_brent_usd@2026-05", fmt=".0f", suffix=" USD"),
                  "b7": b("obs:gl_brent_usd@2026-07", fmt=".0f", suffix=" USD"),
                  "b0": b("obs:gl_brent_usd@2025-12", fmt=".0f", suffix=" USD")}),
        C(id="C-H0-02", type="FACT", hypotheses=["H0"], stance="for",
          text_en="The PPI rise is upstream: producer-goods PPI was {pg} year on year in 2026-08 while "
                  "consumer-goods PPI was still {cg}.",
          text_zh="PPI的上涨集中在上游：2026年8月生产资料PPI同比为{pg}，而生活资料PPI同比仍为{cg}。",
          values={"pg": b("obs:cn_ppi_producer_yoy@2026-08"), "cg": b("obs:cn_ppi_consumer_yoy@2026-08")}),
        C(id="C-H0-03", type="FACT", hypotheses=["H0"], stance="for",
          text_en="Copper averaged {cu} a tonne in 2026-07, against {cu0} a year earlier.",
          text_zh="2026年7月铜价均值为{cu}/吨，上年同期为{cu0}/吨。",
          values={"cu": b("obs:gl_copper_usd@2026-07", fmt=",.0f", suffix=" USD"),
                  "cu0": b("obs:gl_copper_usd@2025-07", fmt=",.0f", suffix=" USD")}),
        C(id="C-H0-04", type="FACT", hypotheses=["H0", "H1"], stance="for",
          text_en="The largest PPI gains coincided with the oil spike: PPI moved {m3} and {m4} month on month in "
                  "2026-03 and 2026-04, when Brent averaged {b3} and {b4}.",
          text_zh="PPI涨幅最大的月份与油价飙升同步：2026年3月和4月PPI环比分别为{m3}和{m4}，同期布伦特原油均价分别为{b3}/桶和{b4}/桶。",
          values={"m3": b("obs:cn_ppi_mom@2026-03"), "m4": b("obs:cn_ppi_mom@2026-04"),
                  "b3": b("obs:gl_brent_usd@2026-03", fmt=".0f", suffix=" USD"),
                  "b4": b("obs:gl_brent_usd@2026-04", fmt=".0f", suffix=" USD")}),
        # ---------------- H2 domestic demand ----------------
        C(id="C-H2-01", type="FACT", hypotheses=["H2"], stance="against",
          text_en="Property sales area was {ps} year on year, year to date, in 2026-08: a steeper decline than the "
                  "{ps0} recorded for 2025 as a whole.",
          text_zh="截至2026年8月，商品房销售面积累计同比为{ps}，降幅较2025年全年的{ps0}进一步扩大。",
          values={"ps": b("obs:cn_property_sales_area_ytd_yoy@2026-08", fmt=".1f", suffix="%"),
                  "ps0": b("obs:cn_property_sales_area_ytd_yoy@2025-12", fmt=".1f", suffix="%")}),
        C(id="C-H2-02", type="DERIVED", hypotheses=["H2"], stance="against",
          text_en="Net new medium and long-term household loans were {jun} in 2026-06, {jul} in 2026-07 and "
                  "{aug} in 2026-08 (CNY 100m, derived from PBOC balances): mortgage books are still shrinking on balance.",
          text_zh="住户中长期贷款当月净新增：2026年6月为{jun}，7月为{jul}，8月为{aug}（单位：亿元，由中国人民银行存量余额推算）；"
                  "按揭贷款余额总体上仍在收缩。",
          values={"jun": b("drv:single(cn_loans_hh_mlt_ytd)@2026-06", fmt=",.0f", suffix=""),
                  "jul": b("drv:single(cn_loans_hh_mlt_ytd)@2026-07", fmt=",.0f", suffix=""),
                  "aug": b("drv:single(cn_loans_hh_mlt_ytd)@2026-08", fmt=",.0f", suffix="")}),
        C(id="C-H2-03", type="FACT", hypotheses=["H2"], stance="against",
          text_en="Retail sales grew {r} year on year in 2026-08, against {r0} a year earlier.",
          text_zh="2026年8月社会消费品零售总额同比增长{r}，上年同期为{r0}。",
          values={"r": b("obs:cn_retail_sales_yoy@2026-08", **PCT_PLAIN),
                  "r0": b("obs:cn_retail_sales_yoy@2025-08", **PCT_PLAIN)}),
        C(id="C-H2-04", type="FACT", hypotheses=["H2"], stance="against",
          text_en="M1 growth was {m} in 2026-08, down from {m0} in 2026-02.",
          text_zh="2026年8月M1同比增速为{m}，较2026年2月的{m0}回落。",
          values={"m": b("obs:cn_m1_yoy@2026-08", **PCT_PLAIN), "m0": b("obs:cn_m1_yoy@2026-02", **PCT_PLAIN)}),
        C(id="C-H2-05", type="FACT", hypotheses=["H2"], stance="against",
          text_en="Core CPI was {k} in 2026-08, no higher than the {k0} of 2025-12: no sign yet of demand-pull "
                  "inflation.",
          text_zh="2026年8月核心CPI同比为{k}，未高于2025年12月的{k0}：尚无需求拉动型通胀的迹象。",
          values={"k": b("obs:cn_core_cpi_yoy@2026-08"), "k0": b("obs:cn_core_cpi_yoy@2025-12")}),
        C(id="C-H2-06", type="DERIVED", hypotheses=["H2"], stance="against",
          text_en="The manufacturing PMI new orders index was {no} in 2026-09, but its three-month average was {avg}: "
                  "orders are hovering at the expansion line rather than expanding.",
          text_zh="2026年9月制造业PMI新订单指数为{no}，但三个月均值为{avg}：订单在荣枯线附近徘徊，尚未形成扩张。",
          values={"no": b("obs:cn_pmi_new_orders@2026-09", **IDX),
                  "avg": b("drv:ma(cn_pmi_new_orders,3)@2026-09", fmt=".1f", suffix="")}),
        # ---------------- H3 policy impulse ----------------
        C(id="C-H3-01", type="FACT", hypotheses=["H3"], stance="against",
          text_en="Total social financing stock growth slowed to {t} in 2026-08 from {t0} in 2025-12.",
          text_zh="社会融资规模存量同比增速由2025年12月的{t0}放缓至2026年8月的{t}。",
          values={"t": b("obs:cn_tsf_stock_yoy@2026-08", **PCT_PLAIN), "t0": b("obs:cn_tsf_stock_yoy@2025-12", **PCT_PLAIN)}),
        C(id="C-H3-02", type="FACT", hypotheses=["H3"], stance="against",
          text_en="General budget expenditure grew only {e} year to date in 2026-07.",
          text_zh="截至2026年7月，一般公共预算支出累计同比仅增长{e}。",
          values={"e": b("obs:cn_budget_exp_ytd_yoy@2026-07", **PCT_PLAIN)}),
        C(id="C-H3-03", type="FACT", hypotheses=["H3"], stance="context",
          text_en="The US 10-year Treasury yield averaged {u} in 2026-09, up from {u0} in 2025-12, while the "
                  "renminbi strengthened to {fx} per dollar from {fx0}.",
          text_zh="美国10年期国债收益率2026年9月均值为{u}，较2025年12月的{u0}上行；同期人民币升值至每美元{fx}元，2025年12月为{fx0}元。",
          values={"u": b("obs:gl_ust10y@2026-09", fmt=".2f", suffix="%"), "u0": b("obs:gl_ust10y@2025-12", fmt=".2f", suffix="%"),
                  "fx": b("obs:gl_usdcny@2026-09", fmt=".2f", suffix=""), "fx0": b("obs:gl_usdcny@2025-12", fmt=".2f", suffix="")}),
        # ---------------- H4 external ----------------
        C(id="C-H4-01", type="FACT", hypotheses=["H4"], stance="for",
          text_en="Exports grew {x} year on year in dollar terms in 2026-08, after {x7} in 2026-07.",
          text_zh="2026年8月以美元计价的出口同比增长{x}，7月为{x7}。",
          values={"x": b("obs:cn_exports_usd_yoy@2026-08", **PCT_PLAIN), "x7": b("obs:cn_exports_usd_yoy@2026-07", **PCT_PLAIN)}),
        C(id="C-H4-02", type="FACT", hypotheses=["H4"], stance="context",
          text_en="The PMI new export orders index was {neo} in 2026-09, at the expansion line, so the export strength "
                  "is not yet showing up as broad new orders.",
          text_zh="2026年9月制造业PMI新出口订单指数为{neo}，恰在荣枯线上，出口的强劲表现尚未转化为广泛的新增订单。",
          values={"neo": b("obs:cn_pmi_new_export_orders@2026-09", **IDX)}),
        # ---------------- inferences ----------------
        C(id="I-01", type="INFERENCE", hypotheses=["H0", "H1"], stance="against",
          text_en="So far the price turn looks supply-led. It is concentrated in producer goods, it coincides with the "
                  "oil and metals shock, and it lost momentum when oil eased. That fits H0 better than a demand-led recovery.",
          text_zh="到目前为止，价格拐点更像是供给端驱动：涨幅集中在生产资料，与油价和金属价格冲击同步，并在油价回落后失去动能。"
                  "这与H0的吻合程度高于需求拉动型复苏。",
          supports=["C-H0-01", "C-H0-02", "C-H0-04", "C-H1-02"]),
        C(id="I-02", type="INFERENCE", hypotheses=["H2"], stance="against",
          text_en="Private domestic demand has not turned. Property sales, mortgage flow, M1 and core CPI are all weak. "
                  "The demand tests that pass do so on marginal second-derivative readings, not on strength.",
          text_zh="私人部门内需尚未转向。商品房销售、按揭贷款、M1和核心CPI均偏弱。已通过的需求检验靠的是边际上的二阶导数式读数，"
                  "而非强劲的表现。",
          supports=["C-H2-01", "C-H2-02", "C-H2-03", "C-H2-04", "C-H2-05", "C-H2-06"]),
        C(id="I-03", type="INFERENCE", hypotheses=["H3"], stance="against",
          text_en="Policy impulse is fading rather than building: credit growth is decelerating and on-budget spending "
                  "is barely growing, so policy is not yet bridging the gap left by private demand.",
          text_zh="政策力度是在减弱而非累积：信贷增速放缓，预算内支出增长乏力，政策尚未填补私人需求留下的缺口。",
          supports=["C-H3-01", "C-H3-02"]),
        C(id="I-04", type="INFERENCE", hypotheses=["H4"], stance="for",
          text_en="Exports are a genuine support for nominal growth. But external demand cannot by itself make the "
                  "turn sustainable under this thesis, which requires domestic demand confirmation.",
          text_zh="出口对名义增长构成实实在在的支撑。但按照本命题的定义，仅靠外需无法使这一拐点具备可持续性，仍需内需的确认。",
          supports=["C-H4-01", "C-H4-02"]),
        C(id="I-05", type="INFERENCE", hypotheses=["H1"], stance="for",
          text_en="The price leg of the thesis is more likely than not to hold through 2027Q1. The factory-gate price "
                  "level is well above a year earlier, so the deflator would turn negative again only if commodity "
                  "prices fell back sharply.",
          text_zh="命题中的价格一环在2027年一季度前维持的可能性大于不维持。出厂价格水平明显高于上年同期，"
                  "因此只有大宗商品价格大幅回落，平减指数才会再度转负。",
          supports=["C-T-01", "C-H1-01", "C-H0-01"]),
        # ---------------- added after the baseline (V1.1): marginal momentum behind cumulative figures ----------------
        C(id="C-H1-06", type="FACT", hypotheses=["H1"], stance="against", as_of=post_as_of,
          text_en="Year-to-date industrial profit growth has slowed in every month since May: {m5} in 2026-05, "
                  "{m6} in 2026-06, {m7} in 2026-07 and {m8} in 2026-08.",
          text_zh="规模以上工业企业利润累计同比增速自5月以来逐月放缓：2026年5月为{m5}，6月为{m6}，7月为{m7}，8月为{m8}。",
          values={"m5": b("obs:cn_ind_profit_ytd_yoy@2026-05", **PCT_PLAIN), "m6": b("obs:cn_ind_profit_ytd_yoy@2026-06", **PCT_PLAIN),
                  "m7": b("obs:cn_ind_profit_ytd_yoy@2026-07", **PCT_PLAIN), "m8": b("obs:cn_ind_profit_ytd_yoy@2026-08", **PCT_PLAIN)}),
        C(id="I-06", type="INFERENCE", hypotheses=["H1"], stance="against", as_of=post_as_of,
          text_en="Because year-to-date profit growth has been falling since May, growth in the latest single month is "
                  "running below the cumulative rate. The headline year-to-date figure therefore overstates current "
                  "profit momentum.",
          text_zh="由于累计利润增速自5月以来持续回落，最新单月的利润增速低于累计增速。累计同比这一头条数字因此高估了当前的利润动能。",
          supports=["C-H1-06", "C-H1-03"]),
        C(id="C-H2-07", type="FACT", hypotheses=["H2"], stance="against", as_of=post_as_of,
          text_en="The year-to-date decline in property sales area has widened in every month since April: {a4} in "
                  "2026-04, {a5} in 2026-05, {a6} in 2026-06, {a7} in 2026-07 and {a8} in 2026-08.",
          text_zh="商品房销售面积累计同比降幅自4月以来逐月扩大：2026年4月为{a4}，5月为{a5}，6月为{a6}，7月为{a7}，8月为{a8}。",
          values={"a4": b("obs:cn_property_sales_area_ytd_yoy@2026-04", fmt=".1f", suffix="%"),
                  "a5": b("obs:cn_property_sales_area_ytd_yoy@2026-05", fmt=".1f", suffix="%"),
                  "a6": b("obs:cn_property_sales_area_ytd_yoy@2026-06", fmt=".1f", suffix="%"),
                  "a7": b("obs:cn_property_sales_area_ytd_yoy@2026-07", fmt=".1f", suffix="%"),
                  "a8": b("obs:cn_property_sales_area_ytd_yoy@2026-08", fmt=".1f", suffix="%")}),
        C(id="I-07", type="INFERENCE", hypotheses=["H2"], stance="against", as_of=post_as_of,
          text_en="Because the cumulative decline has widened every month since April, sales in the latest single months "
                  "are weaker than the year-to-date rate. The change-based property test that passes compares August "
                  "with the weak January-February starting point, so that pass reflects the weak early-year starting "
                  "point more than a recent improvement.",
          text_zh="累计降幅自4月以来逐月扩大，意味着最近几个单月的销售弱于累计降幅所显示的水平。已通过的那项基于变化的房地产检验，"
                  "是把8月与年初（1—2月）偏弱的起点相比较，因此这一通过更多反映年初起点偏弱，而非近期改善。",
          supports=["C-H2-07", "C-H2-01"]),
        C(id="I-08", type="INFERENCE", hypotheses=["H2"], stance="against", as_of=post_as_of,
          text_en="Broad domestic-demand confirmation is still absent. By level, property sales, household mortgage "
                  "flow, M1 and core CPI remain weak. The demand tests that do pass do so on marginal changes from weak "
                  "levels, and the one forward-looking improvement, September manufacturing new orders above the "
                  "expansion line, is not yet confirmed by its three-month average.",
          text_zh="内需的广泛确认仍然缺位。从水平看，商品房销售、住户按揭贷款、M1和核心CPI依然偏弱；已通过的需求检验"
                  "多来自弱势水平上的边际改善；而唯一的前瞻性改善——9月制造业新订单升至荣枯线上方——尚未得到三个月均值的确认。",
          supports=["C-H2-01", "C-H2-02", "C-H2-03", "C-H2-04", "C-H2-05", "C-H2-06", "C-H2-07"]),
    ]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--as-of", required=True, help="as_of of the claims preregistered with the baseline")
    ap.add_argument("--post-baseline-as-of", default="2026-10-04T13:00:00Z",
                    help="as_of of claims added after the baseline (marginal-momentum claims)")
    a = ap.parse_args()
    out = ROOT / "research/cases/cn-nominal/claims.jsonl"
    save_claims(claims(a.as_of, a.post_baseline_as_of), out)
    print(f"wrote {out}")
