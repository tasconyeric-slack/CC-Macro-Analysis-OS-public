"""The two UI string files must stay in step, and every string the site asks for must exist in both."""
import re
from pathlib import Path

import pytest
import yaml

import localization as L
import views
from cnmacro.claims import CLAIM_TYPES
from cnmacro.derive import Deriver
from cnmacro.thesis import CONVICTIONS, DIRECTIONS, STATUSES

ROOT = Path(__file__).resolve().parents[1]
STEMS = ["index", "memo", "evidence", "updates", "charts", "method"]
SOURCES = [ROOT / "site/templates", ROOT / "site/build.py", ROOT / "site/views.py", ROOT / "site/localization.py"]


def flat(loc):
    return L.flatten(L.load_strings(loc))


def test_ui_files_define_exactly_the_same_keys():
    en, zh = set(flat("en")), set(flat("zh"))
    assert not en - zh, f"UI strings missing in zh.yaml: {sorted(en - zh)}"
    assert not zh - en, f"UI strings missing in en.yaml: {sorted(zh - en)}"


@pytest.mark.parametrize("loc", L.LOCALES)
def test_no_ui_string_is_empty(loc):
    empty = [k for k, v in flat(loc).items() if not str(v).strip()]
    assert not empty, f"[{loc}] empty UI strings: {empty}"


def test_placeholders_agree_between_languages():
    en, zh = flat("en"), flat("zh")
    bad = {k: (L.placeholders(en[k]), L.placeholders(zh[k])) for k in en if k in zh
           and L.placeholders(en[k]) != L.placeholders(zh[k])}
    assert not bad, f"placeholders differ: {bad}"


def test_html_keys_are_paired_and_markup_is_balanced():
    for loc in L.LOCALES:
        for k, v in flat(loc).items():
            if "<" in v or ">" in v:
                assert k.endswith(L.HTML_SUFFIX), f"[{loc}] {k} contains markup but is not an *_html key"
            if k.endswith(L.HTML_SUFFIX):
                tags = re.findall(r"<(/?)(\w+)", v)
                opens = [t for s, t in tags if not s and t not in ("br",)]
                closes = [t for s, t in tags if s]
                assert sorted(opens) == sorted(closes), f"[{loc}] {k}: unbalanced markup"


def test_chinese_ui_is_chinese_and_english_ui_is_not():
    """No mixed-language UI: a zh string with no Chinese in it must be a deliberate proper noun or acronym."""
    allowed = {"EN", "CC Macro Analysis OS", "%"}
    mixed = [k for k, v in flat("zh").items()
             if re.search(r"[A-Za-z]", str(v)) and not L.CJK.search(str(v)) and str(v) not in allowed
             # Guojin column cards deliberately pair an English kicker with a Chinese title.
             and not (k.startswith("portal.") and k.endswith("kicker"))]
    assert not mixed, f"zh.yaml strings with no Chinese (untranslated?): {mixed}"
    leaked = [k for k, v in flat("en").items() if L.CJK.search(str(v)) and k not in ("lang.name_zh",)]
    assert not leaked, f"en.yaml strings containing Chinese: {leaked}"


def literal_keys():
    """Every dotted key written as a literal inside t('...') / t.has('...') in the templates and code."""
    found = {}
    call = re.compile(r"""\bt(?:_en|_zh)?(?:\.has)?\(([^()]*(?:\([^()]*\)[^()]*)*)\)""")
    lit = re.compile(r"""['"]([a-z][a-z0-9_]*(?:\.[A-Za-z0-9_]+)+\.?)['"]""")
    for src in SOURCES:
        for f in ([src] if src.is_file() else sorted(src.glob("*.html"))):
            text = f.read_text(encoding="utf-8")
            for m in call.finditer(text):
                for k in lit.findall(m.group(1)):
                    if not k.endswith((".html", ".js", ".", "_")):   # a trailing . or _ marks a built-up key
                        found.setdefault(k, f.name)
    return found


def test_every_key_the_code_asks_for_exists_in_both_languages():
    keys = literal_keys()
    assert len(keys) > 150, "the key scan found almost nothing; the pattern is broken"
    en, zh = flat("en"), flat("zh")
    missing = sorted((k, f) for k, f in keys.items() if k not in en or k not in zh)
    assert not missing, f"UI keys used but not defined in both languages: {missing}"


def test_keys_built_from_data_exist_in_both_languages(model):
    metrics = model["metrics"]
    want = set()
    want |= {f"units.{m.unit}" for m in metrics.values()}
    want |= {f"tier.{t}" for t in ("core", "diagnostic")}
    want |= {f"status.{s}" for s in STATUSES | {"PROPOSED", "DRAFT"}}
    want |= {f"confidence.{c}" for c in CONVICTIONS} | {f"direction.{d}" for d in DIRECTIONS}
    want |= {f"direction.suggested.{d}" for d in ("toward_thesis", "against_thesis", "neutral")}
    want |= {f"outcome.{o}" for o in ("true", "false", "insufficient_data")}
    want |= {f"hyp.short.H{i}" for i in range(5)} | {f"state.{s}" for s in views.STATE_TONE}
    want |= {f"lens.{x}" for x in views.LENSES} | {f"claim_type.{x}" for x in CLAIM_TYPES}
    want |= {f"policy.category.{x}" for x in views.POLICY_CATEGORIES} | {f"policy.stage.{x}" for x in views.STAGES}
    want |= {f"policy.scope.{x}" for x in ("in_baseline", "before_baseline", "after_baseline")}
    want |= {f"rules.name.{n}" for n, r in model["case"]["terminal_rules"].items() if isinstance(r, dict) and r.get("when")}
    want |= {f"scenario.row.{x}" for x in views.SCENARIO_ROWS}
    want |= {f"source_status.{s['status']}" for s in model["sources"]["sources"]}
    want |= {f"derived.{fn}" for fn in Deriver.FUNCS}
    want |= {f"eval.{kind}.E{i}" for kind in ("name", "what") for i in range(6)}
    want |= {k for _, k in L.EVAL_DETAIL_PATTERNS} | {"eval.mode.public", "eval.mode.private"}
    want |= {f"eval.redistribution.{r}" for r in ("unclear", "private_only", "public")}
    want |= {f"nav.{s}" for s in STEMS} | {f"page.{s}.{x}" for s in STEMS for x in ("title", "description")}
    want |= {f"kind.{k}" for k in ("baseline", "amendment", "data", "update", "next")}
    want |= {"lang.name_en", "lang.name_zh", "rules.all", "rules.any", "home.set_in_update", "rules.test_fails"}
    en, zh = flat("en"), flat("zh")
    assert not sorted(k for k in want if k not in en or k not in zh), \
        sorted(k for k in want if k not in en or k not in zh)


def test_a_missing_key_fails_the_build_instead_of_rendering_blank():
    with pytest.raises(KeyError, match="missing UI string"):
        L.Translator("zh")("no.such.key")
    with pytest.raises(KeyError):
        L.Translator("en", {"a": {"b": "x"}})("a.c")


def test_metric_and_calendar_text_is_localized(model):
    """Every metric has a Chinese name and role; every calendar entry resolves to Chinese."""
    for m in model["metrics"].values():
        assert m.name_zh and m.role_zh, f"{m.metric_id} needs name_zh and role_zh"
    zh_names = model["presentation"]["calendar_names_zh"]
    cal = yaml.safe_load((ROOT / "data/dictionary/release_calendar.yaml").read_text(encoding="utf-8"))["releases"]
    for r in cal:
        assert L.calendar_label_is_localized(r, "zh", zh_names), f"no Chinese name for calendar entry {r['name']!r}"
        assert L.CJK.search(L.calendar_label(r, "zh", zh_names))
        assert not L.CJK.search(L.calendar_label(r, "en", zh_names)), r["name"]
