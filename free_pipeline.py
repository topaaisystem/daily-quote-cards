"""무료 일일 명언 카드 파이프라인.
  python free_pipeline.py make [--theme courage|strength|joy|success] [--attempt N]
카드는 output/free/<날짜>/card.jpg + record.json 으로 저장합니다. 발송 전까지 이력(history)은 소모하지 않습니다.
"""
import argparse
import hashlib
import json
import random
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import free_card
import wiki_free as w

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'output' / 'free'
HISTORY = ROOT / '.private' / 'free_history.json'
KST = ZoneInfo('Asia/Seoul')
LABELS = {'courage': 'Courage', 'strength': 'Strength', 'joy': 'Joy', 'success': 'Success'}
log = lambda *a: print(*a, file=sys.stderr, flush=True)


def today():
    return datetime.now(KST).date().isoformat()


def load_history():
    return json.loads(HISTORY.read_text(encoding='utf-8')) if HISTORY.exists() else {'used': [], 'people': {}}


def mark_sent(record):
    """발송 성공 후에만 호출: 같은 명언·최근 같은 인물이 다시 나오지 않게 기록."""
    h = load_history()
    h['used'].append(record['quote']['id'])
    h['people'][record['person']['name']] = record['day']
    HISTORY.parent.mkdir(exist_ok=True)
    HISTORY.write_text(json.dumps(h, ensure_ascii=False, indent=2), encoding='utf-8')


def quote_id(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]


def pick(theme, day, attempt, history, limit=30):
    rng = random.Random(f'{day}|{theme}|{attempt}')
    people = w.theme_people(theme)
    rng.shuffle(people)
    for name in people[:limit]:
        if name in history['people']:
            continue                                   # 한 번 보낸 인물은 당분간 제외
        info = w.person_info(name)
        if not info or not info['image'] or 'fiction' in info['desc'].lower():
            continue
        portrait = w.commons_file(info['image'], 700)
        if not portrait:
            log('  초상 라이선스 불충분, 건너뜀:', name)
            continue
        cands = [q for q in w.sourced_quotes(w.wikitext(info['title']))
                 if w.on_theme(q['text'], theme) and quote_id(q['text']) not in history['used']]
        if not cands:
            continue
        rng.shuffle(cands)
        for cand in cands[:3]:
            ko = w.translate_ko(cand['text'])
            if ko:
                return info, portrait, cand, ko
    raise RuntimeError('조건(출처·초상 라이선스·주제)에 맞는 명언을 찾지 못했습니다. 다시 시도하세요.')


def make(theme=None, attempt=0, day=None):
    day = day or today()
    history = load_history()
    themes = list(w.THEMES)
    theme = theme or themes[int(hashlib.sha256(day.encode()).hexdigest(), 16) % len(themes)]
    log('주제:', theme)
    info, portrait, cand, ko = pick(theme, day, attempt, history)
    seed = int(hashlib.sha256(f'{day}{attempt}'.encode()).hexdigest(), 16) % 1000
    bg = w.background(seed)
    if not bg:
        raise RuntimeError('퍼블릭 도메인 배경을 찾지 못했습니다.')
    record = {
        'day': day, 'theme': theme, 'theme_label': LABELS[theme],
        'quote': {'id': quote_id(cand['text']), 'en': cand['text'], 'ko': ko, 'source': cand['source'],
                  'ko_note': 'MyMemory 자동 번역(검수 전)', 'wikiquote': 'https://en.wikiquote.org/wiki/' + info['title'].replace(' ', '_')},
        'person': {'name': info['title'], 'ko': info['ko'], 'desc': info['desc'],
                   'wikipedia': 'https://en.wikipedia.org/wiki/' + info['title'].replace(' ', '_')},
        'portrait': {k: portrait[k] for k in ('license', 'artist', 'page')},
        'background': {k: bg[k] for k in ('title', 'license', 'page')},
        'attempt': attempt,
    }
    folder = OUT / day
    free_card.render(record, w.download(portrait['url']), w.download(bg['url']), folder / 'card.jpg')
    (folder / 'record.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    return record


if __name__ == '__main__':
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding='utf-8')
    p = argparse.ArgumentParser()
    p.add_argument('command', choices=['make'])
    p.add_argument('--theme', choices=list(w.THEMES))
    p.add_argument('--attempt', type=int, default=0)
    a = p.parse_args()
    r = make(a.theme, a.attempt)
    print(json.dumps({'card': str(OUT / r['day'] / 'card.jpg'), 'person': r['person']['name'], 'en': r['quote']['en'], 'ko': r['quote']['ko']}, ensure_ascii=False, indent=2))
