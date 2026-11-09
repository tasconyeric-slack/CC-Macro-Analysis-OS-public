"""Policy text is an event: deterministic differences never approve a thesis change."""
import json
from pathlib import Path

import pytest

from cnmacro import policy_delta as pd

ROOT = Path(__file__).resolve().parents[1]


def test_punctuation_noise_is_unchanged_and_text_is_preserved():
    old = '增强政策前瞻性灵活性针对性,保持流动性充裕。'
    new = '增强政策前瞻性灵活性针对性， 保持流动性充裕。'
    rows = pd.sentence_diff(old, new, {})
    assert all(r['tag'] == 'unchanged' for r in rows)
    assert rows[0]['before'] != rows[0]['after']  # original punctuation remains inspectable


def test_strength_requires_a_matching_lexicon_substitution():
    lexicon = {'families': [{'terms': [{'phrase': '保持', 'weight': 1}, {'phrase': '加大', 'weight': 2}]}]}
    assert pd.sentence_diff('保持支持力度。', '加大支持力度。', lexicon)[0]['tag'] == 'strengthened'
    assert pd.sentence_diff('加大支持力度。', '保持支持力度。', lexicon)[0]['tag'] == 'weakened'
    rows = pd.sentence_diff('关注需求。', '关注需求和科技创新。', lexicon)
    assert {r['tag'] for r in rows} == {'added', 'removed'}


def test_real_documents_have_an_unchanged_control_and_a_sourced_added_clause():
    comparisons = pd.load_comparisons(ROOT / 'data/events', ROOT / 'data/dictionary/policy_lexicon.yaml', as_of='2026-12-31T00:00:00Z')
    pair = comparisons[0]
    assert any(r['tag'] == 'unchanged' and '货币政策保持适度宽松' in r['after'] for r in pair['rows'])
    assert any(r['tag'] == 'added' and '综合运用并适时调整货币政策工具' in r['after'] for r in pair['rows'])
    assert pair['before']['canonical_url'].startswith('https://www.pbc.gov.cn/')
    assert pair['after']['text_sha256']


def test_document_hash_tamper_fails_closed(tmp_path):
    import shutil
    shutil.copytree(ROOT / 'data/events/texts', tmp_path / 'texts')
    shutil.copy(ROOT / 'data/events/policy_documents.json', tmp_path / 'policy_documents.json')
    (tmp_path / 'texts/pboc-mpc-2026q3.txt').write_text('altered', encoding='utf-8')
    with pytest.raises(ValueError, match='hash'):
        pd.load_comparisons(tmp_path, ROOT / 'data/dictionary/policy_lexicon.yaml', as_of='2026-12-31T00:00:00Z')


def one_context():
    pair = {'comparison_id': 'test-pair', 'rows': pd.sentence_diff('保持支持力度。', '加大支持力度。', {}),
            'before': {'text_sha256': 'old'}, 'after': {'text_sha256': 'new'}, 'as_of': '2026-01-01T00:00:00Z'}
    return pd.interpretation_context(pair)


def good_result(ctx):
    return {'interpretations': [{'row_id': r['row_id'], 'intent': '支持需求', 'tool': '政策工具', 'stage': 'announced',
        'transmission_channel': '信用传导', 'hypothesis': 'H2', 'impact': 'uncertain',
        'counter_reading': '措辞不等于执行', 'next_confirmation': '核对下一次官方发布', 'research_need': '执行是否改善需求',
        'evidence_refs': [r['ref']]} for r in ctx['rows']]}


def test_interpretation_rejects_numbers_unknown_refs_and_thesis_fields():
    ctx = one_context()
    obj = good_result(ctx)
    obj['interpretations'][0]['intent'] = '增长10%'
    assert any(e['gate'] == 'numeric_grounding' for e in pd.validate_interpretation(obj, ctx))
    obj = good_result(ctx); obj['interpretations'][0]['evidence_refs'] = ['untrusted']
    assert any(e['gate'] == 'invalid_evidence_ref' for e in pd.validate_interpretation(obj, ctx))
    obj = good_result(ctx); obj['probability'] = 0.9
    assert any(e['gate'] == 'schema' for e in pd.validate_interpretation(obj, ctx))


def test_missing_model_is_recorded_and_cannot_be_published(tmp_path):
    ctx = one_context()
    rec, directory = pd.run_interpretation(ctx, tmp_path, client=None)
    assert rec['status'] == 'model_unavailable' and not rec['genuine_model_run']
    assert (directory / 'record.json').is_file() and (directory / 'context.json').is_file()
    assert pd.accepted_interpretation(tmp_path, ctx, as_of='2026-12-31T00:00:00Z') is None
    with pytest.raises(ValueError, match='validated'):
        pd.review_run(directory, 'accept', reviewer='test', reason='test')


def test_review_is_append_only_and_only_accepted_validated_output_is_public(tmp_path):
    from cnmacro.copilot.llm import Reply
    ctx = one_context()
    class ControlledTestClient:
        genuine = True
        def identity(self): return {'provider': 'controlled-unit-test'}
        def call(self, system, user): return Reply(json.dumps(good_result(ctx)), {'fixture': True}, {'input_tokens': 1, 'output_tokens': 1})
    rec, directory = pd.run_interpretation(ctx, tmp_path, client=ControlledTestClient())
    cutoff = '2099-01-01T00:00:00Z'
    assert rec['validation']['ok'] and pd.accepted_interpretation(tmp_path, ctx, as_of=cutoff) is None
    p1 = pd.review_run(directory, 'accept', reviewer='unit-test-reviewer', reason='test only')
    original = p1.read_bytes()
    assert pd.accepted_interpretation(tmp_path, ctx, as_of=cutoff)['interpretations']
    pd.review_run(directory, 'keep_unresolved', reviewer='unit-test-reviewer', reason='test only')
    assert p1.read_bytes() == original
    assert pd.accepted_interpretation(tmp_path, ctx, as_of=cutoff) is None
    p1.write_text('{}', encoding='utf-8')
    assert pd.accepted_interpretation(tmp_path, ctx, as_of=cutoff) is None


def test_real_pair_is_visible_without_an_ai_interpretation(built):
    page = (built / "zh/policy.html").read_text(encoding="utf-8")
    assert 'id="pboc-mpc-2026q2-to-q3"' in page
    assert '2026070818273311767' in page and '2026092416074632670' in page
    assert '综合运用并适时调整货币政策工具' in page
    assert '未变化表述' in page
    assert 'policy-reading' not in page  # no approved interpretation was manufactured
