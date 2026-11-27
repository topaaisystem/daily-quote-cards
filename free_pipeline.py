"""무료 일일 명언 카드 파이프라인.
  python free_pipeline.py make [--theme courage|strength|joy|success] [--attempt N]
카드는 output/free/<날짜>/card.jpg + record.json 으로 저장합니다. 발송 전까지 이력(history)은 소모하지 않습니다.
"""
import argparse
import hashlib
import json
import random
import time
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import free_card
import wiki_free as w

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'output' / 'free'
import os
HISTORY = Path(os.environ.get('QUOTE_HISTORY') or ROOT / '.private' / 'free_history.json')  # Actions에서는 data/history.json
CARDS = ROOT / 'cards'
KEEP_CARDS = 90                                   # Pages 용량 관리: 최근 90일 카드만 유지
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
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    HISTORY.write_text(json.dumps(h, ensure_ascii=False, indent=2), encoding='utf-8')


def quote_id(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]


MIN_SCORE = 8            # 10점 만점, 이 점수 이상만 사용
RATING_BUDGET = 25       # 한 번 실행에서 AI 평가 최대 호출 수(무료 한도 보호)


FALLBACK_SCORE = 6       # 8점 이상이 없을 때 차선으로 허용하는 최저 점수
MAX_SECONDS = 600        # 후보 탐색 최대 시간(초)


def rate(cands, budget):
    """후보 명언들을 (점수, 후보)로 평가. AI 평가는 후보 묶음당 1회 호출, 불가하면 키워드 대체 필터(통과 8, 탈락 3)."""
    if cands and budget['left'] > 0:
        scores = w.llm_scores([c['text'] for c in cands])
        if scores:
            budget['left'] -= 1
            for c, sc in zip(cands, scores):
                log(f"  평가 {sc}/10: {c['text'][:70]}")
            return list(zip(scores, cands))
    return [(3 if w.looks_off_topic(c['text']) else 8, c) for c in cands]


def pick(theme, day, attempt, history, limit=80):
    budget = {'left': RATING_BUDGET}
    started = time.monotonic()
    rng = random.Random(f'{day}|{theme}|{attempt}')
    people = w.theme_people(theme)
    rng.shuffle(people)
    log(f'  후보 인물 {len(people)}명')
    best = None                                        # 8점 미만 중 최고(차선책)
    for name in people[:limit]:
        if time.monotonic() - started > MAX_SECONDS:
            log('  탐색 시간 초과')
            break
        if name in history['people']:
            continue                                   # 한 번 보낸 인물은 당분간 제외
        info = w.person_info(name)
        if not info or not info['image'] or 'fiction' in info['desc'].lower() or w.NON_QUOTE_PERSON.search(info['desc']):
            continue
        cands = [q for q in w.sourced_quotes(w.wikitext(info['title']))
                 if w.on_theme(q['text'], theme) and quote_id(q['text']) not in history['used']]
        if not cands:
            continue
        portrait = w.commons_file(info['image'], 700)
        if not portrait:
            log('  초상 라이선스 불충분, 건너뜀:', name)
            continue
        rng.shuffle(cands)
        for score, cand in sorted(rate(cands[:12], budget), key=lambda x: -x[0]):
            if score >= MIN_SCORE:
                ko, label = w.translate_ko(cand['text'])
                if ko:
                    return info, portrait, dict(cand, ko_label=label), ko
            elif score >= FALLBACK_SCORE and (best is None or score > best[0]):
                best = (score, info, portrait, cand)
    if best:
        score, info, portrait, cand = best
        ko, label = w.translate_ko(cand['text'])
        if ko:
            log(f'  차선책 사용({score}/10)')
            return info, portrait, dict(cand, ko_label=label), ko
    raise RuntimeError(f'주제 {theme}: 조건(출처·초상 라이선스·주제)에 맞는 명언을 찾지 못했습니다.')


def _download_or_none(url, label):
    """이미지 한 장을 받아 옵니다. 재시도를 다 거듭해도 429가 풀리지 않으면 None을 돌려 카드 제작을 멈추지 않습니다."""
    try:
        return w.download(url)
    except RuntimeError as exc:
        log(f'  {label} 이미지 실패 → 대체 그림으로 진행: {exc}')
        return None


def make(theme=None, attempt=0, day=None, allow_fallback=False):
    day = day or today()
    history = load_history()
    themes = list(w.THEMES)
    theme_forced = bool(theme)
    theme = theme or themes[int(hashlib.sha256(day.encode()).hexdigest(), 16) % len(themes)]
    order = [theme] if theme_forced else [theme] + [t for t in themes if t != theme]   # 실패하면 다른 주제로 재시도
    last = None
    for theme in order:
        log('주제:', theme)
        try:
            info, portrait, cand, ko = pick(theme, day, attempt, history)
            break
        except RuntimeError as exc:
            last = exc
            log('  실패:', exc)
    else:
        raise last
    seed = int(hashlib.sha256(f'{day}{attempt}'.encode()).hexdigest(), 16) % 1000
    bg = w.background(seed)
    if not bg:
        raise RuntimeError('퍼블릭 도메인 배경을 찾지 못했습니다.')
    record = {
        'day': day, 'theme': theme, 'theme_label': LABELS[theme],
        'quote': {'id': quote_id(cand['text']), 'en': cand['text'], 'ko': ko, 'source': cand['source'],
                  'ko_note': cand['ko_label'] + ' (검수 전)', 'ko_label': cand['ko_label'], 'wikiquote': 'https://en.wikiquote.org/wiki/' + info['title'].replace(' ', '_')},
        'person': {'name': info['title'], 'ko': info['ko'], 'desc': info['desc'],
                   'wikipedia': 'https://en.wikipedia.org/wiki/' + info['title'].replace(' ', '_')},
        'portrait': {k: portrait[k] for k in ('license', 'artist', 'page')},
        'background': {k: bg[k] for k in ('title', 'license', 'page')},
        'attempt': attempt,
    }
    folder = OUT / day
    portrait_bytes = _download_or_none(portrait['url'], '초상') if allow_fallback else w.download(portrait['url'])
    if portrait_bytes is None:
        record['portrait'] = {'license': '없음(글자 배지)', 'artist': '', 'page': ''}
    background_bytes = _download_or_none(bg['url'], '배경') if allow_fallback else w.download(bg['url'])
    if background_bytes is None:
        record['background'] = {'title': 'generated gradient', 'license': 'own work', 'page': ''}
    record['fallback'] = {'portrait': portrait_bytes is None, 'background': background_bytes is None}
    free_card.render(record, portrait_bytes, background_bytes, folder / 'card.jpg')
    (folder / 'record.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    return record


def already_handled(day):
    """오늘 이미 발송했거나(pending 포함) 발송 중인 날짜면 True → 카드 재생성·덮어쓰기 금지."""
    status = ROOT / 'data' / 'status.json'
    return status.exists() and json.loads(status.read_text(encoding='utf-8')).get(day) in ('pending', 'sent')


def publish(day):
    """카드를 Pages가 서빙하는 cards/<날짜>.jpg 로 복사하고 오래된 카드를 정리."""
    import shutil
    CARDS.mkdir(exist_ok=True)
    shutil.copy2(OUT / day / 'card.jpg', CARDS / f'{day}.jpg')
    for old in sorted(CARDS.glob('*.jpg'))[:-KEEP_CARDS]:
        old.unlink()
    return CARDS / f'{day}.jpg'


if __name__ == '__main__':
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding='utf-8')
    p = argparse.ArgumentParser()
    p.add_argument('command', choices=['make'])
    p.add_argument('--theme', choices=list(w.THEMES))
    p.add_argument('--attempt', type=int, default=0)
    p.add_argument('--publish', action='store_true', help='cards/<날짜>.jpg 로 복사(Pages용)')
    p.add_argument('--allow-fallback', action='store_true',
                   help='초상·배경 이미지가 429로 끝내 막히면 글자 배지·그라데이션 카드로라도 발송(예비 실행용)')
    a = p.parse_args()
    if a.publish and already_handled(today()):
        log(f'{today()} 는 이미 발송 처리됨. 카드를 다시 만들지 않습니다.')
        sys.exit(0)
    r = make(a.theme, a.attempt, allow_fallback=a.allow_fallback)
    if a.publish:
        log('게시용 복사:', publish(r['day']))
    print(json.dumps({'card': str(OUT / r['day'] / 'card.jpg'), 'person': r['person']['name'], 'en': r['quote']['en'], 'ko': r['quote']['ko']}, ensure_ascii=False, indent=2))
