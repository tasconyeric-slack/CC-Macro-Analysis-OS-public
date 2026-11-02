"""Locale support for the static site: UI strings, dates, periods, calendar names.

Two locales are built from the SAME research state. This module only decides how things are
written in a language; it never touches a number, a claim id, an evidence outcome, a threshold or
the thesis state. A missing UI key raises (the build fails) instead of rendering a blank or a
fallback language, so the two UI files can never drift unnoticed.
"""
from __future__ import annotations

import re
from pathlib import Path
from string import Formatter

import pandas as pd
import yaml
from markupsafe import Markup, escape

LOCALES = ("en", "zh")
DEFAULT_LOCALE = "en"
HREFLANG = {"en": "en", "zh": "zh-Hans"}
OG_LOCALE = {"en": "en_US", "zh": "zh_CN"}
I18N_DIR = Path(__file__).resolve().parent / "i18n"
HTML_SUFFIX = "_html"          # keys ending in _html hold trusted markup; their arguments are escaped

MONTHS_EN = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
MONTHS_LONG_EN = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
                  "October", "November", "December"]
QUARTER_ZH = {"1": "一", "2": "二", "3": "三", "4": "四"}


def load_strings(locale: str) -> dict:
    return yaml.safe_load((I18N_DIR / f"{locale}.yaml").read_text(encoding="utf-8")) or {}


def flatten(node: dict, prefix: str = "") -> dict[str, str]:
    """{'a': {'b': 'x'}} -> {'a.b': 'x'}; lists of strings become 'a.b.0', 'a.b.1'."""
    out: dict[str, str] = {}
    for k, v in node.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(flatten(v, key + "."))
        elif isinstance(v, list):
            out.update({f"{key}.{i}": x for i, x in enumerate(v)})
        else:
            out[key] = v
    return out


def placeholders(text: str) -> set[str]:
    return {f for _, f, _, _ in Formatter().parse(text) if f}


class Translator:
    """Look up a dotted key (nav.overview gives 'Overview'); keyword arguments fill {placeholders}."""

    def __init__(self, locale: str, strings: dict | None = None):
        self.locale = locale
        self.flat = flatten(strings if strings is not None else load_strings(locale))

    def __call__(self, key: str, **kw):
        try:
            text = self.flat[key]
        except KeyError:
            raise KeyError(f"[{self.locale}] missing UI string {key!r}") from None
        if key.endswith(HTML_SUFFIX):
            return Markup(text).format(**kw) if kw else Markup(text)
        return text.format(**kw) if kw else text

    def has(self, key: str) -> bool:
        return key in self.flat

    def items(self, prefix: str) -> list[tuple[str, str]]:
        """All (suffix, text) pairs under a key prefix, e.g. every 'status.*'."""
        p = prefix + "."
        return [(k[len(p):], v) for k, v in self.flat.items() if k.startswith(p)]


# ---------------------------------------------------------------- dates and periods
def _stamp(value) -> pd.Timestamp | None:
    return pd.Timestamp(str(value)) if value else None


def fmt_date(value, loc: str) -> str:
    """'2026-10-14' -> '14 Oct 2026' | '2026年10月14日'."""
    t = _stamp(value)
    if t is None:
        return "–"
    return f"{t.year}年{t.month}月{t.day}日" if loc == "zh" else f"{t.day} {MONTHS_EN[t.month - 1]} {t.year}"


def fmt_when(value, loc: str) -> str:
    """'2026-10-14T09:30:00+08:00' -> '14 Oct 2026, 09:30 Beijing' | '2026年10月14日 09:30 北京时间'."""
    t = _stamp(value)
    if t is None:
        return "–"
    s = fmt_date(t, loc)
    if t.hour or t.minute:
        clock = t.strftime("%H:%M")
        if t.tzinfo is not None:
            off = t.utcoffset().total_seconds()
            zone = ({"en": " Beijing", "zh": " 北京时间"} if off == 8 * 3600 else
                    {"en": " UTC", "zh": " UTC"} if off == 0 else
                    {"en": f" ({t.strftime('%z')})", "zh": f" UTC{t.strftime('%z')}"})[loc]
        else:
            zone = " UTC"
        s += f", {clock}{zone}" if loc == "en" else f" {clock}{zone}"
    return s


def fmt_period(p, loc: str, long: bool = False) -> str:
    """'2026-08' -> 'Aug 2026' ('August 2026' if long) | '2026年8月'; '2026Q2' -> '2026 Q2' | '2026年二季度'."""
    if not p:
        return "–"
    p = str(p)
    if "Q" in p:
        return f"{p[:4]}年{QUARTER_ZH[p[5]]}季度" if loc == "zh" else f"{p[:4]} {p[4:]}"
    if re.fullmatch(r"\d{4}-\d{2}", p):
        y, m = int(p[:4]), int(p[5:])
        if loc == "zh":
            return f"{y}年{m}月"
        return f"{(MONTHS_LONG_EN if long else MONTHS_EN)[m - 1]} {y}"
    return f"{p}年" if loc == "zh" and re.fullmatch(r"\d{4}", p) else p


def fmt_periods(periods: list[str], loc: str, long: bool = False, max_list: int = 4) -> str:
    """A short list of periods, or 'first – last' once the list is long (a streak of 13 quarters)."""
    if len(periods) > max_list:
        ordered = sorted(periods)
        return f"{fmt_period(ordered[0], loc, long)} – {fmt_period(ordered[-1], loc, long)}"
    sep = "、" if loc == "zh" else ", "
    return sep.join(fmt_period(p, loc, long) for p in periods)


CJK_GAP = re.compile(r"(?<=[\u3000-\u303f\u4e00-\u9fff\uff00-\uffef]) +(?=[\u3000-\u303f\u4e00-\u9fff\uff00-\uffef])")


def tidy(text, loc: str):
    """YAML folds a wrapped line into 'word word'. Chinese has no spaces between characters, so a fold
    that landed between two Chinese characters is removed; spaces next to Latin text stay."""
    if loc != "zh" or not isinstance(text, str):
        return text
    return CJK_GAP.sub("", " ".join(text.split()))


def pct(p) -> str:
    return "–" if p is None else f"{round(float(p) * 100):d}%"


# ---------------------------------------------------------------- calendar names
CJK = re.compile(r"[一-鿿]")
TRAILING_CJK = re.compile(r"\s*[（(]([^()（）]*[一-鿿][^()（）]*)[)）]\s*$")


def calendar_label(entry: dict, loc: str, zh_names: dict | None = None) -> str:
    """A release's name in the reader's language.

    Calendar entries taken from the NBS agenda read '2026-09 property ... (房地产...月度报告)': the
    English part and the official Chinese title sit together. Hand-written entries are English
    and are mapped in presentation.yaml (calendar_names_zh). Anything unmapped falls back to the
    English name, which the build reports so it can be fixed.
    """
    name = str(entry["name"])
    m = TRAILING_CJK.search(name)
    if loc == "en":
        return TRAILING_CJK.sub("", name).strip() if m else name
    if m:
        return f"{fmt_period(entry.get('period'), 'zh')}{m.group(1)}"
    return (zh_names or {}).get(name, name)


def calendar_label_is_localized(entry: dict, loc: str, zh_names: dict | None = None) -> bool:
    name = str(entry["name"])
    return loc == "en" or bool(TRAILING_CJK.search(name)) or name in (zh_names or {})


# ---------------------------------------------------------------- eval details
EVAL_DETAIL_PATTERNS = [
    (re.compile(r"^(?P<m>\w+): not in public build \((?P<r>\w+)\); private mode only$"), "eval.detail.not_public"),
    (re.compile(r"^(?P<m>\w+): no observations$"), "eval.detail.no_obs"),
    (re.compile(r"^(?P<m>\w+): (?P<n>\d+) gap\(s\), e\.g\. \[(?P<p>.*)\]$"), "eval.detail.gaps"),
]


def localize_eval_detail(detail: str, t: Translator, metric_name) -> str | None:
    """Known engine messages in the reader's language; None if the message is not one of them."""
    for rx, key in EVAL_DETAIL_PATTERNS:
        m = rx.match(detail)
        if m:
            g = m.groupdict()
            periods = ", ".join(re.findall(r"\d{4}-\d{2}", g.get("p", "")))
            return t(key, metric=metric_name(g["m"]), n=g.get("n", ""), periods=periods,
                     redistribution=t(f"eval.redistribution.{g['r']}") if "r" in g and
                     t.has(f"eval.redistribution.{g['r']}") else g.get("r", ""))
    return None
