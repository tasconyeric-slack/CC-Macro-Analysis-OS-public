"""Claims ledger: the only place numbers enter prose.

A claim's text uses placeholders ({name}) bound to refs. `fill` records each
bound value as of the claim's as_of date; rendering uses the recorded value, and
the citation check verifies it against the data. Memo, website and updates cite
claims by id, so no number is ever typed by hand.

Claims are bilingual (`text_en`, `text_zh`) but one record: both texts share the claim id,
the bindings, the refs, the supports and the stance, so a language can never fork the
numbers or the evidence. The checks below enforce that the two texts bind the same
placeholders and mention the same periods.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

CLAIM_TYPES = {"FACT", "DERIVED", "EXTERNAL_VIEW", "INFERENCE"}
STANCES = {"for", "against", "context"}
LOCALES = ("en", "zh")
PLACEHOLDER = re.compile(r"\{(\w+)\}")
# A "bare number" is a decimal, a percentage / bp figure, or an integer > 12 that is not a
# year or period label. Small integers ("3-month", "2 quarters") are allowed. ASCII-only word
# boundaries, so a figure glued to Chinese text ("同比3.8%") is still seen.
BARE_NUMBER = re.compile(r"(?<![A-Za-z0-9_{.])(-?\d+\.\d+|-?\d+\s?(?:%|bp|pp)|\d{2,})(?![A-Za-z0-9_}])")
ALLOWED_TOKEN = re.compile(r"^(19|20)\d{2}$")

# Units that are shown in the reader's language. The number itself is never touched.
UNIT_LABELS = {"zh": {" USD": "美元"}}
CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4}


@dataclass
class Binding:
    ref: str
    fmt: str = ".1f"
    suffix: str = ""
    recorded: float | None = None


@dataclass
class Claim:
    id: str
    type: str
    text_en: str
    text_zh: str
    as_of: str
    hypotheses: list[str]
    stance: str = "context"
    values: dict[str, Binding] = field(default_factory=dict)
    refs: list[str] = field(default_factory=list)       # refs cited without a printed value
    supports: list[str] = field(default_factory=list)   # for INFERENCE
    source: dict | None = None                          # for EXTERNAL_VIEW
    public: bool = True                                 # False if it cites private-only evidence

    @property
    def text(self) -> str:
        """The English text (what the ledger held before claims were bilingual)."""
        return self.text_en

    def all_refs(self) -> list[str]:
        return [b.ref for b in self.values.values()] + list(self.refs)

    def render(self, withheld: set[str] | None = None, locale: str = "en") -> str:
        withheld = withheld or set()
        units = UNIT_LABELS.get(locale, {})

        def sub(m):
            b = self.values[m.group(1)]
            if b.ref in withheld:
                return WITHHELD[locale]
            if b.recorded is None:
                return "[unfilled]"
            return f"{b.recorded:{b.fmt}}{units.get(b.suffix, b.suffix)}"
        return PLACEHOLDER.sub(sub, getattr(self, f"text_{locale}"))


WITHHELD = {"en": "[licensed data, withheld]", "zh": "[授权数据，未公开]"}


def bare_numbers(text: str, locale: str = "en") -> list[str]:
    stripped = PLACEHOLDER.sub("", text)
    if locale == "zh":
        # 2026年8月 / 2026年二季度 / 10年期 / 3个月 / 8月 / 12日: period words, not figures
        stripped = re.sub(r"\d{1,4}\s?(年期|年|个月|月|日|季度)", "", stripped)
        stripped = re.sub(r"(?<![A-Za-z0-9])(19|20)\d{2}(Q[1-4])?(?![A-Za-z0-9])", "", stripped)
        stripped = re.sub(r"(?<![A-Za-z0-9])H[0-4](?![A-Za-z0-9])|(?<![A-Za-z0-9])\d{1,2}[MY](?![A-Za-z0-9])", "", stripped)
    else:
        stripped = re.sub(r"\b(19|20)\d{2}(Q[1-4]|-\d{2}(-\d{2})?)?\b", "", stripped)  # periods
        stripped = re.sub(r"\bH[0-4]\b|\b\d{1,2}[MY]\b", "", stripped)                  # H1, 3M, 10Y
        stripped = re.sub(r"\b\d{1,2}-(year|month|quarter|day)s?\b", "", stripped)      # 10-year, 3-month
    return [m.group(0) for m in BARE_NUMBER.finditer(stripped) if not ALLOWED_TOKEN.match(m.group(0))]


def period_tokens(text: str) -> set[str]:
    """The periods a text mentions, normalised: '2026-08', '2026Q2', '2025' (a whole year).
    English writes 2026-08 / 2026Q2; Chinese writes 2026年8月 / 2026年二季度, and may drop the year
    of a later month or quarter in the same sentence ('2026年6月、7月'), which inherits the last
    year named. Used to prove the two texts of a claim talk about the same periods."""
    text = PLACEHOLDER.sub("", text)
    toks: set[str] = set()
    pat = re.compile(
        r"(?P<ym>(?P<y1>(?:19|20)\d{2})-(?P<m1>\d{2}))(?!\d)"
        r"|(?P<yq>(?P<y2>(?:19|20)\d{2})Q(?P<q2>[1-4]))"
        r"|(?P<zym>(?P<y3>(?:19|20)\d{2})年(?P<m3>\d{1,2})月)"
        r"|(?P<zyq>(?P<y4>(?:19|20)\d{2})年第?(?P<q4>[一二三四1-4])季度)"
        r"|(?P<zy>(?P<y5>(?:19|20)\d{2})年)"
        r"|(?P<zm>(?<![\d年])(?P<m6>\d{1,2})月)"
        r"|(?P<zq>第?(?P<q7>[一二三四])季度)"
        r"|(?P<ey>(?<![\d-])(?P<y8>(?:19|20)\d{2})(?![\d年Q-]))")
    year = None
    for m in pat.finditer(text):
        if m.group("ym"):
            year = m.group("y1"); toks.add(f"{year}-{m.group('m1')}")
        elif m.group("yq"):
            year = m.group("y2"); toks.add(f"{year}Q{m.group('q2')}")
        elif m.group("zym"):
            year = m.group("y3"); toks.add(f"{year}-{int(m.group('m3')):02d}")
        elif m.group("zyq"):
            year = m.group("y4"); q = m.group("q4"); toks.add(f"{year}Q{CN_NUM.get(q) or q}")
        elif m.group("zy"):
            year = m.group("y5"); toks.add(year)
        elif m.group("zm") and year:
            toks.add(f"{year}-{int(m.group('m6')):02d}")
        elif m.group("zq") and year:
            toks.add(f"{year}Q{CN_NUM[m.group('q7')]}")
        elif m.group("ey"):
            year = m.group("y8"); toks.add(year)
    return toks


def validate_claim(c: Claim) -> list[str]:
    errs = []
    if c.type not in CLAIM_TYPES:
        errs.append(f"{c.id}: unknown type {c.type}")
    if c.stance not in STANCES:
        errs.append(f"{c.id}: unknown stance {c.stance}")
    for loc in LOCALES:
        text = getattr(c, f"text_{loc}")
        if not (text or "").strip():
            errs.append(f"{c.id}: missing text_{loc}")
            continue
        names = set(PLACEHOLDER.findall(text))
        if names != set(c.values):
            errs.append(f"{c.id}: text_{loc} placeholders {sorted(names)} != bindings {sorted(c.values)}")
        for n in bare_numbers(text, loc):
            errs.append(f"{c.id}: bare number '{n}' in text_{loc}; bind it to a ref")
    if c.text_en.strip() and c.text_zh.strip():
        en, zh = period_tokens(c.text_en), period_tokens(c.text_zh)
        if en != zh:
            errs.append(f"{c.id}: periods differ between languages (en {sorted(en)} vs zh {sorted(zh)})")
    refs = c.all_refs()
    if c.type == "FACT" and not any(r.startswith("obs:") for r in refs):
        errs.append(f"{c.id}: FACT must cite at least one observation")
    if c.type == "DERIVED" and not any(r.startswith("drv:") for r in refs):
        errs.append(f"{c.id}: DERIVED must cite at least one derived ref")
    if c.type == "INFERENCE" and not c.supports:
        errs.append(f"{c.id}: INFERENCE must list supporting claims")
    if c.type == "EXTERNAL_VIEW" and not (c.source and {"institution", "date"} <= set(c.source)):
        errs.append(f"{c.id}: EXTERNAL_VIEW needs source.institution and source.date")
    return errs


def load_claims(path: str | Path) -> list[Claim]:
    claims = []
    for i, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        raw = json.loads(line)
        if "text" in raw:                      # a ledger written before claims were bilingual
            raw["text_en"] = raw.pop("text")
        raw.setdefault("text_zh", "")
        raw["values"] = {k: Binding(**v) for k, v in raw.get("values", {}).items()}
        claims.append(Claim(**raw))
    ids = [c.id for c in claims]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ValueError(f"duplicate claim ids: {sorted(dupes)}")
    return claims


def save_claims(claims: list[Claim], path: str | Path) -> None:
    lines = [json.dumps(asdict(c), ensure_ascii=False) for c in claims]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
