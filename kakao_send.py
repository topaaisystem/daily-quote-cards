"""카카오톡 '나에게 보내기'(피드 템플릿) 발송. 표준 라이브러리만 사용.

환경 변수(GitHub Secrets): KAKAO_REST_KEY, KAKAO_REFRESH_TOKEN, (선택) KAKAO_CLIENT_SECRET
  python kakao_send.py            # 오늘(KST) 카드를 발송
  python kakao_send.py --dry-run  # 요청 본문만 출력, 네트워크 호출 없음

중복 방지: data/status.json 에 날짜별 pending/sent 를 기록하고, 발송 '전에' 저장·커밋합니다.
타임아웃 등으로 성공 여부를 알 수 없으면 pending 으로 남기고 재발송하지 않습니다.
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import free_pipeline as fp

ROOT = Path(__file__).resolve().parent
STATUS = ROOT / 'data' / 'status.json'
PAGES = os.environ.get('PAGES_BASE', 'https://topaaisystem.github.io/daily-quote-cards').rstrip('/')


def card_url(day):
    return f'{PAGES}/cards/{day}.jpg'


def template(record, day):
    url = card_url(day)
    return {
        'object_type': 'feed',
        'content': {
            'title': record['person']['name'],
            'description': record['quote']['ko'],
            'image_url': url, 'image_width': 1536, 'image_height': 1536,
            'link': {'web_url': url, 'mobile_web_url': url},
        },
        'button_title': '카드 크게 보기',
    }


def load_status():
    return json.loads(STATUS.read_text(encoding='utf-8')) if STATUS.exists() else {}


def save_status(status):
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    STATUS.write_text(json.dumps(status, indent=2, sort_keys=True), encoding='utf-8')


def commit(paths, message):
    """Actions 환경(CI_COMMIT=1)에서만 상태를 저장소에 커밋·푸시. 실패하면 발송하지 않음."""
    if os.environ.get('CI_COMMIT') != '1':
        return
    run = lambda *a: subprocess.run(a, cwd=ROOT, check=True)
    run('git', 'config', 'user.name', 'daily-quote-bot')
    run('git', 'config', 'user.email', 'daily-quote-bot@users.noreply.github.com')
    run('git', 'add', *paths)
    if subprocess.run(['git', 'diff', '--cached', '--quiet'], cwd=ROOT).returncode:
        run('git', 'commit', '-m', message)
        run('git', 'pull', '--rebase', '-q')
        run('git', 'push', '-q')


def wait_for_image(url, timeout=420):
    """Pages 배포가 끝나 이미지가 공개 접근 가능해질 때까지 대기(카카오 서버가 가져갈 수 있어야 함)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'dq'}), timeout=20) as r:
                if r.status == 200 and r.headers.get('Content-Type', '').startswith('image/') and len(r.read()) > 10000:
                    return
        except (urllib.error.URLError, TimeoutError):
            pass
        time.sleep(15)
    raise RuntimeError(f'이미지가 공개되지 않았습니다: {url}')


def post(url, data, token=None):
    headers = {'Content-Type': 'application/x-www-form-urlencoded;charset=utf-8'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(), headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def refresh_access_token():
    data = {'grant_type': 'refresh_token', 'client_id': os.environ['KAKAO_REST_KEY'],
            'refresh_token': os.environ['KAKAO_REFRESH_TOKEN']}
    if os.environ.get('KAKAO_CLIENT_SECRET'):
        data['client_secret'] = os.environ['KAKAO_CLIENT_SECRET']
    try:
        result = post('https://kauth.kakao.com/oauth/token', data)
    except urllib.error.HTTPError as exc:               # 응답 본문(토큰 포함 가능)은 출력하지 않음
        raise RuntimeError(f'토큰 갱신 실패 HTTP {exc.code}: 카카오 키/refresh token 을 확인하세요.') from None
    if not result.get('access_token'):
        raise RuntimeError('토큰 갱신 응답에 access_token 이 없습니다.')
    return result['access_token'], bool(result.get('refresh_token'))


def main(argv):
    dry = '--dry-run' in argv
    day = fp.today()
    record = json.loads((fp.OUT / day / 'record.json').read_text(encoding='utf-8'))
    body = template(record, day)
    if dry:
        print(json.dumps(body, ensure_ascii=False, indent=2))
        return 0
    status = load_status()
    if status.get(day) in ('pending', 'sent'):
        print(f'{day} 처리 기록: {status[day]}. 중복 발송하지 않습니다.')
        return 0
    wait_for_image(card_url(day))
    access, rotated = refresh_access_token()
    status[day] = 'pending'                              # 발송 의도를 먼저 기록·커밋
    save_status(status)
    commit(['data/status.json'], f'status {day}: pending')
    try:
        result = post('https://kapi.kakao.com/v2/api/talk/memo/default/send',
                      {'template_object': json.dumps(body, ensure_ascii=False)}, access)
    except urllib.error.HTTPError as exc:
        print(f'카카오 오류 HTTP {exc.code}. 수신 여부를 확인하세요(자동 재시도 안 함).', file=sys.stderr)
        return 2
    except (urllib.error.URLError, TimeoutError):
        print('네트워크 오류: 성공 여부 불명. 카카오톡 수신을 확인하세요(자동 재시도 안 함).', file=sys.stderr)
        return 2
    if result.get('result_code') != 0:
        print('성공 응답이 아닙니다. 수신 여부를 확인하세요.', file=sys.stderr)
        return 2
    status[day] = 'sent'
    save_status(status)
    fp.mark_sent(record)
    commit(['data/status.json', 'data/history.json'], f'status {day}: sent')
    print(f'{day} 나에게 보내기 API 성공(휴대폰 수신은 직접 확인).')
    if rotated:
        print('경고: 카카오가 새 refresh token 을 발급했습니다. 로컬에서 토큰을 다시 발급해 '
              'KAKAO_REFRESH_TOKEN 시크릿을 교체하세요.', file=sys.stderr)
        return 3
    return 0


if __name__ == '__main__':
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding='utf-8')
    sys.exit(main(sys.argv[1:]))
