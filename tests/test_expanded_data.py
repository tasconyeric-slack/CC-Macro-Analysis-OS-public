from pathlib import Path
import pytest
from cnmacro.expanded_data import NEW_METRICS,parse_pboc_m2
from cnmacro.store import load_dictionary,load_observations
ROOT=Path(__file__).resolve().parents[1]

def test_original_pboc_m2_is_not_the_tsf_growth_rate():
    fixture=(ROOT/'tests/fixtures/expanded/pboc_m2_202609.html').read_text(encoding='utf8')
    row=parse_pboc_m2(fixture,'https://www.pbc.gov.cn/original')
    assert (row['period'],row['value'],row['release_date']) == ('2026-09',7.2,'2026-10-14')
    with pytest.raises(ValueError,match='M2 month-end'):
        parse_pboc_m2(fixture.replace('M2','M9'),'https://www.pbc.gov.cn/original')

def test_nine_new_metrics_have_real_history_and_public_metadata():
    metrics=load_dictionary(ROOT/'data/dictionary/metrics.yaml')
    obs=load_observations(ROOT/'data/demo/observations')
    assert len(NEW_METRICS)==9
    for mid in NEW_METRICS:
        m=metrics[mid];rows=obs[obs.metric_id==mid]
        assert len(rows)>=60 and rows.reference_period.nunique()>=60
        assert m.redistribution=='public' and m.category
        assert rows.source_class.eq('public').all() and rows.source_code.ne('').all()
        assert rows.retrieved_at.ne('').all()
    m2=obs[obs.metric_id=='cn_m2_yoy']
    assert any(str(code).startswith('https://www.pbc.gov.cn/') for code in m2.source_code)
    assert any(str(code).startswith('nbs:') for code in m2.source_code)
