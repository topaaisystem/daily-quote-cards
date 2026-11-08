"""무료 공개 출처 수집: 위키인용집(명언), 위키백과/위키미디어 커먼스(초상·배경), MyMemory(한국어 번역).
유료 API·API 키 없음. 요청에는 식별 가능한 User-Agent를 붙이고 호출 사이에 짧게 쉽니다.
"""
import json
import re
import time
import urllib.parse
import urllib.request

UA = 'DailyQuoteCard/0.1 (personal non-commercial project)'
THEMES = {
    'courage': ['Courage', 'Bravery', 'Fear'],
    'strength': ['Strength', 'Perseverance', 'Determination', 'Resilience'],
    'joy': ['Happiness', 'Joy', 'Optimism', 'Gratitude'],
    'success': ['Success', 'Achievement', 'Hope', 'Confidence'],
}
BAD_SECTIONS = re.compile(r'disputed|misattributed|quotes about|external links|see also|references|further reading|sources|about\b', re.I)
PD_LICENSE = re.compile(r'public domain|^pd\b|^pd-|cc0|cc-zero', re.I)


def _get(url, tries=4):
    last = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': UA}), timeout=30) as r:
                return r.read()
        except Exception as exc:  # 네트워크 오류·429(요청 과다)는 점점 길게 쉬고 재시도
            last = exc
            time.sleep(6 * (i + 1) if '429' in str(exc) else 1.5 * (i + 1))
    raise RuntimeError(f'요청 실패: {url[:90]} ({last})')


def api(base, **params):
    params.update({'format': 'json', 'formatversion': 2})
    time.sleep(0.8)
    return json.loads(_get(f'{base}?' + urllib.parse.urlencode(params)).decode('utf-8'))


WQ = 'https://en.wikiquote.org/w/api.php'
WP = 'https://en.wikipedia.org/w/api.php'
KO = 'https://ko.wikipedia.org/w/api.php'
CM = 'https://commons.wikimedia.org/w/api.php'


def wikitext(page):
    try:
        return api(WQ, action='parse', page=page, prop='wikitext', redirects=1)['parse']['wikitext']
    except Exception:
        return ''


def clean(text):
    text = re.sub(r'<ref[^>]*>.*?</ref>|<ref[^>]*/>', '', text, flags=re.S)
    text = re.sub(r'<br\s*/?>', ' ', text, flags=re.I)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\{\{[^{}]*\}\}', '', text)
    text = re.sub(r'\[\[(?:File|Image|Category):[^\]]*\]\]', '', text, flags=re.I)
    text = re.sub(r'\[\[[^\]|]*\|([^\]]*)\]\]', r'\1', text)
    text = re.sub(r'\[\[([^\]]*)\]\]', r'\1', text)
    text = re.sub(r'\[https?://\S+\s+([^\]]*)\]', r'\1', text)
    text = re.sub(r'\[https?://\S+\]', '', text)
    text = re.sub(r"'{2,}", '', text)
    return re.sub(r'\s+', ' ', text).strip()


def theme_people(theme):
    """주제 문서(Courage 등)에서 '~ [[인물]]'로 표시된 인물 이름을 모읍니다."""
    names = []
    for page in THEMES[theme]:
        text = wikitext(page)
        for m in re.finditer(r'~\s*\[\[([^\]|#]+)', text):
            n = m.group(1).strip()
            if n and n not in names:
                names.append(n)
    return names


THEME_WORDS = {
    'courage': r'courag|brave|bold|fear|dare|valor|heart',
    'strength': r'strength|strong|persever|persist|endur|resil|fall|rise|never give|determin|patience',
    'joy': r'happi|joy|smile|laugh|gratitude|grateful|cheer|delight|content|optimis|sunshine',
    'success': r'success|achiev|hope|confiden|dream|goal|believe|work|effort|victory|win',
}


def on_theme(text, theme):
    return re.search(THEME_WORDS[theme], text, re.I) is not None


def sourced_quotes(text):
    """출처가 붙은 명언만 반환: '**' 하위 줄에 출처가 있거나 작품명 소제목 아래 있는 항목.
    Disputed/Misattributed/'Quotes about' 구간은 제외."""
    out, section_ok, in_work, work = [], True, False, ''
    lines = text.splitlines()
    for i, line in enumerate(lines):
        h = re.match(r'^(=+)\s*(.*?)\s*=+\s*$', line)
        if h:
            title = h.group(2)
            section_ok = not BAD_SECTIONS.search(title)
            in_work = "''" in title
            work = clean(title)
            continue
        if not section_ok or not line.startswith('* ') or line.startswith('**'):
            continue
        body = clean(line[2:])
        subs = []
        for nxt in lines[i + 1:i + 5]:
            if nxt.startswith('**'):
                subs.append(clean(nxt.lstrip('*')))
            else:
                break
        source = ' '.join(s for s in subs if len(s) > 6)[:160]
        if not source and in_work:
            source = work
        if re.search(r'\bsong\b|lyric|album|single\b|\blyrics\b', source + ' ' + work, re.I):
            continue                                   # 노래 가사는 명언으로 쓰지 않음
        if not source or not (35 <= len(body) <= 170) or not re.search(r'[A-Za-z]{4}', body):
            continue
        if body.startswith('[') or re.search(r'translation\)|\bed\.\b|\bpp?\.', body) or not body.rstrip('"”').endswith(('.', '!', '?')):
            continue  # 편집 표기·번역본 주석·미완결 문장 제외
        if re.search(r'\b(said|wrote|asked)\b[: ,]*$', body):
            continue
        out.append({'text': body.strip('"“” '), 'source': source})
    return out


def person_info(name):
    """위키백과: 한줄 설명, 한국어 이름, 대표 사진 파일명."""
    q = api(WP, action='query', titles=name, redirects=1, prop='pageimages|pageprops|langlinks',
            piprop='name', ppprop='wikibase-shortdesc', lllang='ko', lllimit=1)
    pages = q['query']['pages']
    if not pages or pages[0].get('missing'):
        return None
    p = pages[0]
    return {'title': p['title'], 'desc': p.get('pageprops', {}).get('wikibase-shortdesc', ''),
            'ko': (p.get('langlinks') or [{}])[0].get('title', ''), 'image': p.get('pageimage', '')}


def commons_file(filename, width):
    """커먼스 파일의 라이선스·작가·축소본 주소. 퍼블릭 도메인/CC0가 아니면 None."""
    try:
        q = api(CM, action='query', titles='File:' + filename, prop='imageinfo',
                iiprop='url|extmetadata|size', iiurlwidth=width)
    except RuntimeError:
        return None
    pages = q['query']['pages']
    if not pages or 'imageinfo' not in pages[0]:
        return None
    info = pages[0]['imageinfo'][0]
    meta = info.get('extmetadata', {})
    lic = meta.get('LicenseShortName', {}).get('value', '')
    if not PD_LICENSE.search(lic):
        return None
    return {'license': lic, 'artist': clean(meta.get('Artist', {}).get('value', ''))[:80],
            'page': info.get('descriptionurl', ''), 'url': info.get('thumburl') or info['url'],
            'width': info['width'], 'height': info['height']}


def download(url):
    return _get(url)


def translate_ko(text):
    """MyMemory 무료 번역(키 없음, 일일 한도 있음). 실패하면 빈 문자열."""
    try:
        data = api('https://api.mymemory.translated.net/get', q=text, langpair='en|ko')
        out = data.get('responseData', {}).get('translatedText', '')
        if data.get('responseStatus') == 200 and out and 'MYMEMORY' not in out.upper():
            return out.strip()
    except Exception:
        pass
    return ''


def background(seed, min_width=1800):
    """커먼스에서 퍼블릭 도메인 풍경화를 검색해 하나 고릅니다(시드로 매일 다르게)."""
    terms = ['landscape painting', 'seascape painting', 'mountain painting', 'sunrise painting', 'forest painting']
    term = terms[seed % len(terms)]
    offset = (seed * 7) % 60
    q = api(CM, action='query', generator='search', gsrnamespace=6, gsrlimit=20, gsroffset=offset,
            gsrsearch=f'{term} filetype:bitmap haswbstatement:P6216=Q19652', prop='imageinfo',
            iiprop='url|extmetadata|size', iiurlwidth=1800)
    pool = []
    for p in q.get('query', {}).get('pages', []):
        info = (p.get('imageinfo') or [None])[0]
        if not info or info['width'] < min_width or info['height'] < 1100:
            continue
        meta = info.get('extmetadata', {})
        lic = meta.get('LicenseShortName', {}).get('value', '')
        if PD_LICENSE.search(lic) and info.get('thumburl'):
            pool.append({'title': p['title'].replace('File:', ''), 'license': lic,
                         'page': info.get('descriptionurl', ''), 'url': info['thumburl']})
    return pool[seed % len(pool)] if pool else None
