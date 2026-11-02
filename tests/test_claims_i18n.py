"""One claim, two languages: same id, bindings, refs, supports and evidence; only the words differ."""
import copy
import hashlib
import re
import subprocess

import pytest
import yaml

from cnmacro.claims import LOCALES, Binding, Claim, bare_numbers, load_claims, period_tokens, validate_claim
from conftest import CASE, ROOT

CLAIMS = CASE / "claims.jsonl"


@pytest.fixture(scope="module")
def claims():
    return load_claims(CLAIMS)


def test_every_public_claim_exists_in_both_languages(claims):
    assert len(claims) >= 27
    for c in claims:
        for loc in LOCALES:
            assert getattr(c, f"text_{loc}").strip(), f"{c.id} has no text_{loc}"


def test_all_claims_validate_in_both_languages(claims):
    assert [e for c in claims for e in validate_claim(c)] == []


def test_both_languages_bind_the_same_numbers(claims):
    """The placeholders are the bindings, and each bound value is printed, identically, in each language."""
    for c in claims:
        for loc in LOCALES:
            names = set(re.findall(r"\{(\w+)\}", getattr(c, f"text_{loc}")))
            assert names == set(c.values), f"{c.id}: text_{loc} binds {sorted(names)}, expected {sorted(c.values)}"
        en, zh = c.render(locale="en"), c.render(locale="zh")
        for name, b in c.values.items():
            assert b.recorded is not None, f"{c.id}.{name} not filled"
            shown = f"{b.recorded:{b.fmt}}"
            assert shown in en and shown in zh, f"{c.id}.{name}: {shown} not printed in both languages"


def test_both_languages_cite_the_same_periods(claims):
    for c in claims:
        assert period_tokens(c.text_en) == period_tokens(c.text_zh), c.id


def test_inference_support_and_stance_are_single_sourced(claims):
    """supports / refs / stance / hypotheses are fields of the one record, never per-language."""
    fields = set(Claim.__dataclass_fields__)
    assert not {f for f in fields if f.endswith(("_en", "_zh"))} - {"text_en", "text_zh"}
    ids = {c.id for c in claims}
    for c in claims:
        assert set(c.supports) <= ids, c.id


def test_the_validator_rejects_a_claim_that_diverges_between_languages(claims):
    base = next(c for c in claims if c.id == "C-H1-01")
    zh_wrong_period = copy.deepcopy(base); zh_wrong_period.text_zh = base.text_zh.replace("2025年12月", "2025年11月")
    zh_extra_binding = copy.deepcopy(base); zh_extra_binding.text_zh += "{ghost}"
    zh_typed_number = copy.deepcopy(base); zh_typed_number.text_zh = base.text_zh.replace("{p}", "3.8%")
    zh_missing = copy.deepcopy(base); zh_missing.text_zh = ""
    en_missing = copy.deepcopy(base); en_missing.text_en = ""
    for bad in (zh_wrong_period, zh_extra_binding, zh_typed_number, zh_missing, en_missing):
        assert validate_claim(bad), bad.text_zh or bad.text_en
    assert validate_claim(base) == []


def test_chinese_bare_numbers_are_caught_even_when_glued_to_characters():
    assert bare_numbers("同比上涨3.8%", "zh") and bare_numbers("上升12%", "zh") and bare_numbers("达到104美元", "zh")
    assert not bare_numbers("2026年8月同比为{p}，较2025年12月回落，三个月均值", "zh")


def test_units_are_the_only_thing_shown_in_the_readers_language(claims):
    c = next(c for c in claims if c.id == "C-H0-01")
    assert "美元" in c.render(locale="zh") and "USD" in c.render(locale="en") and "USD" not in c.render(locale="zh")
    assert c.values["b5"].suffix == " USD"                   # the binding itself is untouched


# ---------------------------------------------------------------- the baseline-era ledger is not rewritten
def historic_claims_matching_the_baseline_hash():
    base = yaml.safe_load(next((CASE / "preregistered").glob("*-baseline.yaml")).read_text(encoding="utf-8"))
    try:
        shas = subprocess.run(["git", "log", "--format=%H", "--", "research/cases/cn-nominal/claims.jsonl"], cwd=ROOT,
                              capture_output=True, text=True, check=True).stdout.split()
        for sha in shas:
            blob = subprocess.run(["git", "show", f"{sha}:research/cases/cn-nominal/claims.jsonl"], cwd=ROOT,
                                  capture_output=True, check=True).stdout
            if hashlib.sha256(blob).hexdigest() == base["claims_sha256"]:
                import json
                return base, [json.loads(l) for l in blob.decode("utf-8").splitlines() if l.strip()]
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    return base, None


I02 = ("Private domestic demand has not turned. Property sales, mortgage flow, M1 and core CPI are all weak. "
       "The demand tests that pass do so on marginal second-derivative readings, not on strength.")


def test_baseline_era_claims_are_identical_to_the_baseline_ledger(claims):
    """The baseline fingerprints claims.jsonl (claims_sha256). Adding Chinese changes the file, so prove that
    nothing a baseline-era claim says or means changed: the English text EXACTLY as the baseline ledger has it,
    and id, type, stance, hypotheses, as_of, bindings (refs, formats, recorded values), refs, supports.
    There is no mechanism to reword a baseline-era claim under its id: better wording lives in the
    presentation layer or in a new claim id with a later as_of."""
    base, old = historic_claims_matching_the_baseline_hash()
    if old is None:
        pytest.skip("git history with the baseline-era claims.jsonl is not available (shallow clone)")
    now = {c.id: c for c in claims}
    assert {o["id"] for o in old} <= set(now), "a baseline claim disappeared"
    for o in old:
        c = now[o["id"]]
        assert c.text_en == o["text"], f"{c.id}: English text differs from the baseline ledger"
        for f in ("type", "as_of", "hypotheses", "stance", "refs", "supports", "source", "public"):
            assert getattr(c, f) == o[f], f"{c.id}.{f} changed"
        assert {k: vars(b) for k, b in c.values.items()} == o["values"], f"{c.id}: bindings changed"
    # claims added since carry a later as_of: they are not part of the frozen judgment
    for c in claims:
        if c.id not in {o["id"] for o in old}:
            assert c.as_of > base["as_of"], f"{c.id} claims to predate the baseline"


def test_i02_keeps_its_baseline_wording_and_the_current_wording_is_a_new_claim(claims):
    by_id = {c.id: c for c in claims}
    assert by_id["I-02"].text_en == I02 and by_id["I-02"].as_of == "2026-10-04T06:00:00Z"
    new = by_id["I-08"]
    assert new.text_en.startswith("Broad domestic-demand confirmation is still absent")
    assert new.as_of > by_id["I-02"].as_of and new.type == "INFERENCE" and new.supports
    assert "has not turned" not in new.text_en


def test_there_is_no_mechanism_to_reword_a_claim_in_place():
    from cnmacro import claims as mod
    assert "revision" not in Claim.__dataclass_fields__
    src = (ROOT / "src/cnmacro/claims.py").read_text(encoding="utf-8")
    build = (CASE / "build_claims.py").read_text(encoding="utf-8")
    ledger = CLAIMS.read_text(encoding="utf-8")
    assert "revision" not in src and "revision=" not in build and '"revision"' not in ledger
    with pytest.raises(TypeError):                       # a ledger line with a revision is rejected, not ignored
        import json, tempfile, pathlib
        rec = json.loads(ledger.splitlines()[0]); rec["revision"] = {"note": "x"}
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "c.jsonl"; p.write_text(json.dumps(rec, ensure_ascii=False) + "\n", encoding="utf-8")
            mod.load_claims(p)


def test_property_inference_does_not_say_base_effect(claims):
    c = next(c for c in claims if c.id == "I-07")
    import re
    assert "weak January-February starting point" in c.text_en
    assert not re.search(r"\bbase\b", c.text_en)          # "change-based" is fine; "base" as in base effect is not
    assert "起点" in c.text_zh and "基数" not in c.text_zh
