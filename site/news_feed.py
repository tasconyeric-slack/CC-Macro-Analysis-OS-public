"""Reader-facing News: ranked events, the full feed, daily editions and the monthly archive."""
from datetime import datetime, timezone
import json
from pathlib import Path
import localization as L
from cnmacro.news_feed import TOPICS, classify
from cnmacro.news_rank import score, BROWSE_FLOOR
from cnmacro import news_ai
from cnmacro.events.store import stamp, BEIJING
ROOT = Path(__file__).resolve().parents[1]
NEWS = ROOT / 'data/news'
LABELS = {
    'zh': dict(title='宏观要闻', intro='中国宏观的数据发布、政策动作与市场变化，按重要性与热度排序，每小时自动更新。',
               top='精选', all='全部动态', editions='日报', archive='往期归档', search='搜索新闻', search_ph='搜索标题与摘要',
               all_topics='全部主题', sources_n='{n} 个来源', more='查看全部要闻', hot='热', official='官方',
               updated='更新于', empty='暂无内容。', edition_title='{date} 宏观日报', edition_window='覆盖 {start} 至 {end}（北京时间）',
               quick='快讯', open_edition='进行中', archive_title='{month} 新闻归档', items_n='{n} 条', also='同一事件',
               policy='政策文件对比', calendar='发布日历', why='为什么重要', ai_tag='AI', original='原题',
               ai_note='AI 生成的解读，不是原始来源的内容，可能有误；请以所链接的原文为准。'),
    'en': dict(title='Macro news', intro='China macro data releases, policy actions and market moves, ranked by importance and coverage, updated hourly.',
               top='Top stories', all='All updates', editions='Daily editions', archive='Archive', search='Search news', search_ph='Search headlines and summaries',
               all_topics='All topics', sources_n='{n} sources', more='See all news', hot='Hot', official='Official',
               updated='Updated', empty='Nothing yet.', edition_title='Daily edition · {date}', edition_window='Covers {start} to {end} Beijing time',
               quick='Briefly', open_edition='in progress', archive_title='News archive · {month}', items_n='{n} items', also='Also reported by',
               policy='Policy wording compared', calendar='Release calendar', why='Why it matters', ai_tag='AI', original='Original',
               ai_note='AI-generated interpretation, not primary-source content. It can be wrong; rely on the linked original.')}


def _load(name):
    f = NEWS / name
    return json.loads(f.read_text(encoding='utf-8')) if f.exists() else None


def enabled(model):
    return not model.get('preview') and not model.get('banner') and \
        Path(model.get('case_dir', ROOT / 'research/cases/cn-nominal')).resolve() == (ROOT / 'research/cases/cn-nominal').resolve()


def _when(iso, loc):
    at = stamp(iso).astimezone(BEIJING)
    return at.strftime('%m-%d %H:%M') if 'T' in iso else at.strftime('%m-%d')


def _ai_on():
    """The Owner's display switch as written by the last news run. Missing means off."""
    return bool((_load('latest.json') or {}).get('ai_display'))


def _ai_text(ai, loc, show):
    """(English headline or None, why-it-matters text) from stored model text. Nothing at all unless the display switch is on."""
    ai = ai if show and isinstance(ai, dict) else {}
    return (ai.get('title_en') or None) if loc == 'en' else None, ai.get('why_en' if loc == 'en' else 'why_zh') or ''


def _headline(zh, ai, loc, show):
    """Title fields: the English headline when there is one, else the Chinese original (marked as Chinese on English pages)."""
    en, why = _ai_text(ai, loc, show)
    return {'title': en or L.tidy(zh, loc), 'title_is_zh': loc == 'en' and not en, 'orig': L.tidy(zh, loc) if en else '', 'why': why}


def _topic(key, loc):
    return TOPICS.get(key, ('', ''))[0 if loc == 'zh' else 1]


def _related(model, topic, loc):
    links = []
    for mid in TOPICS.get(topic, ('', '', '', []))[3][:2]:
        m = model.get('metrics', {}).get(mid)
        if m is not None and getattr(m, 'category', None):
            links.append({'name': L.tidy(m.name_zh if loc == 'zh' else m.name, loc), 'url': f'data-{m.category}.html#metric-{mid}'})
    return links


def _official_events(model, cutoff):
    """Items from the existing official intake (NBS, PBOC, gov.cn policy library)."""
    try:
        from cnmacro.events.store import load_grouped_public_items
        rows = load_grouped_public_items(ROOT / 'data/events', as_of=cutoff)
    except Exception:
        return []
    out = []
    for r in rows:
        topic = r.get('topic') or classify(r.get('title_zh', '') + ' ' + r.get('summary_zh', ''))
        if topic not in TOPICS or not r.get('published_at'):
            continue
        item = {**r, 'topic': topic, 'source_tier': 'T1', 'source': r.get('source', 'official')}
        item['content_type'], item['score'] = score(item)
        out.append(item)
    return out


def news_context(model, loc):
    lab = LABELS[loc]
    if not enabled(model):
        return {'enabled': False, 'labels': lab, 'events': [], 'home_events': [], 'items': [], 'editions': [], 'months': [], 'topics': []}
    snap = _load('latest.json') or {'events': [], 'items': [], 'as_of': None, 'sources': []}
    show = bool(snap.get('ai_display'))
    cutoff = model.get('built_at') or datetime.now(timezone.utc).isoformat()
    items = [x for x in snap.get('items', []) if stamp(x['published_at']) <= stamp(cutoff)]
    seen = {x['canonical_url'] for x in items}
    items += [x for x in _official_events(model, cutoff) if x['canonical_url'] not in seen]
    by_id = {x['item_id']: x for x in items}
    events = []
    for e in snap.get('events', []):
        if not e.get('selected') or stamp(e['first_at']) > stamp(cutoff):
            continue
        members = [by_id[i] for i in e['items'] if i in by_id]
        others, named = [], {e['publisher']}
        for x in members:  # one link per other publisher
            if x['canonical_url'] != e['url'] and x['publisher'] not in named:
                others.append({'publisher': x['publisher'], 'url': x['canonical_url']}); named.add(x['publisher'])
        is_release = any(x.get('content_type') == 'data_release' for x in members)
        events.append({'id': e['event_id'], **_headline(e['title_zh'], e.get('ai'), loc, show), 'summary': e.get('summary_zh', '') if e.get('summary_zh') != e['title_zh'] else '',
                       'url': e['url'], 'publisher': e['publisher'], 'n_sources': len(e['publishers']), 'official': e['official'],
                       'hot': e['heat'] >= 1.5, 'topic': e['topic'], 'topic_name': _topic(e['topic'], loc), 'time': _when(e['last_at'], loc),
                       'last_at': e['last_at'], 'importance': e['importance'], 'others': others[:6], 'related': _related(model, e['topic'], loc) if is_release else [],
                       'zh_only': loc == 'en'})
    # top stories: the last 48 hours by importance, then older selected events
    recent = [e for e in events if (stamp(cutoff) - stamp(e['last_at'])).total_seconds() <= 48 * 3600]
    older = sorted([e for e in events if e not in recent], key=lambda e: e['last_at'], reverse=True)
    top = sorted(recent, key=lambda e: -e['importance']) + older
    feed = sorted([x for x in items if x.get('score', 0) >= BROWSE_FLOOR], key=lambda x: stamp(x['published_at']), reverse=True)
    feed = [{'title': L.tidy(x['title_zh'], loc), 'url': x['canonical_url'], 'publisher': x['publisher'], 'topic': x['topic'],
             'topic_name': _topic(x['topic'], loc), 'time': _when(x['published_at'], loc), 'day': stamp(x['published_at']).astimezone(BEIJING).date().isoformat(),
             'official': x.get('source_tier') == 'T1'} for x in feed]
    eds = sorted((NEWS / 'editions').glob('*.json'), reverse=True) if (NEWS / 'editions').exists() else []
    editions = [{'date': f.stem, 'file': f'news-edition-{f.stem}.html'} for f in eds]
    months = sorted([f.stem for f in (NEWS / 'archive').glob('*.json')], reverse=True) if (NEWS / 'archive').exists() else []
    return {'enabled': True, 'labels': lab, 'updated_at': snap.get('as_of'), 'events': top[:40], 'home_events': top[:6], 'items': feed[:200],
            'editions': editions[:30], 'months': [{'month': m, 'file': f'news-archive-{m}.html'} for m in months],
            'topics': [{'id': k, 'name': v[0 if loc == 'zh' else 1]} for k, v in TOPICS.items()]}


def edition_context(day, loc):
    ed = json.loads((NEWS / 'editions' / f'{day}.json').read_text(encoding='utf-8'))
    lab = LABELS[loc]
    fmt = lambda iso: stamp(iso).astimezone(BEIJING).strftime('%m-%d %H:%M')
    show = _ai_on()
    row = lambda r: {**_headline(r['title_zh'], r.get('ai'), loc, show), 'summary': r.get('summary_zh', '') if r.get('summary_zh') != r['title_zh'] else '',
                     'url': r['url'], 'publisher': r['publisher'], 'n_sources': len(r['publishers']), 'topic_name': _topic(r['topic'], loc)}
    return {'date': day, 'final': ed.get('final', False), 'title': lab['edition_title'].format(date=day),
            'window': lab['edition_window'].format(start=fmt(ed['window'][0]), end=fmt(ed['window'][1])),
            'body': [row(r) for r in ed['body']], 'quick': [row(r) for r in ed['quick']], 'labels': lab}


def archive_context(month, loc):
    rows = json.loads((NEWS / 'archive' / f'{month}.json').read_text(encoding='utf-8'))
    lab = LABELS[loc]
    show = _ai_on()
    index = news_ai.index_cache(news_ai.load_cache(NEWS)) if show else {}
    ai_of = lambda x: news_ai.shown_fields(index.get((x['item_id'], news_ai.content_hash(news_ai.source_input(x))), {}))
    rows = [{'id': x['item_id'], **_headline(x['title_zh'], ai_of(x), loc, show), 'url': x['canonical_url'], 'publisher': x['publisher'], 'topic_name': _topic(x.get('topic'), loc),
             'time': _when(x['published_at'], loc), 'summary': x.get('summary_zh', '') if x.get('summary_zh') != x['title_zh'] else ''}
            for x in rows if x.get('topic') in TOPICS]
    return {'month': month, 'title': lab['archive_title'].format(month=month), 'rows': rows, 'count': lab['items_n'].format(n=len(rows)), 'labels': lab}


def edition_days():
    d = NEWS / 'editions'
    return sorted(f.stem for f in d.glob('*.json')) if d.exists() else []


def archive_months():
    d = NEWS / 'archive'
    return sorted(f.stem for f in d.glob('*.json')) if d.exists() else []
