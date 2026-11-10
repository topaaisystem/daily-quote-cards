import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import kakao_send as ks

RECORD = {'person': {'name': 'Test Person'}, 'quote': {'ko': '테스트 명언입니다.', 'id': 'abc'}, 'day': '2026-11-09'}


class KakaoSendTests(unittest.TestCase):
    def test_feed_template_matches_kakao_spec(self):
        t = ks.template(RECORD, '2026-11-09')
        self.assertEqual(t['object_type'], 'feed')
        c = t['content']
        self.assertTrue(c['image_url'].startswith('https://'))
        self.assertTrue(c['image_url'].endswith('/cards/2026-11-09.jpg'))
        self.assertEqual((c['image_width'], c['image_height']), (1536, 1536))
        self.assertIn('web_url', c['link'])          # 카카오 문서: link 필수
        self.assertTrue(len(t['button_title']) <= 8)  # 버튼 제목 8자 이내 권장

    def test_status_roundtrip_and_duplicate_guard(self):
        with tempfile.TemporaryDirectory() as d, patch.object(ks, 'STATUS', Path(d) / 'data' / 'status.json'):
            self.assertEqual(ks.load_status(), {})
            ks.save_status({'2026-11-09': 'pending'})
            self.assertEqual(ks.load_status()['2026-11-09'], 'pending')

    def test_pending_day_is_never_sent_again(self):
        with tempfile.TemporaryDirectory() as d, patch.object(ks, 'STATUS', Path(d) / 's.json'), \
                patch.object(ks.fp, 'today', return_value='2026-11-09'), \
                patch.object(ks.fp, 'OUT', Path(d)), \
                patch.object(ks, 'post', side_effect=AssertionError('네트워크 호출 금지')), \
                patch.object(ks, 'wait_for_image', side_effect=AssertionError('호출 금지')):
            (Path(d) / '2026-11-09').mkdir()
            (Path(d) / '2026-11-09' / 'record.json').write_text(json.dumps(RECORD), encoding='utf-8')
            ks.save_status({'2026-11-09': 'pending'})
            self.assertEqual(ks.main([]), 0)

    def test_sent_day_exits_cleanly_without_record_file(self):
        with tempfile.TemporaryDirectory() as d, patch.object(ks, 'STATUS', Path(d) / 's.json'), \
                patch.object(ks.fp, 'today', return_value='2026-11-09'), patch.object(ks.fp, 'OUT', Path(d) / 'none'):
            ks.save_status({'2026-11-09': 'sent'})
            self.assertEqual(ks.main([]), 0)      # record.json 이 없어도 오류 없이 종료

    def test_waits_until_send_time_only_when_early(self):
        from datetime import datetime
        kst = ks.fp.KST
        slept = []
        with patch.dict('os.environ', {'SEND_AT': '08:30'}):
            ks.wait_until_send_time(datetime(2026, 11, 10, 7, 30, tzinfo=kst), sleep=slept.append)
            self.assertEqual(slept, [3600])                                 # 1시간 전 → 3600초 대기
            ks.wait_until_send_time(datetime(2026, 11, 10, 13, 41, tzinfo=kst), sleep=slept.append)
            self.assertEqual(slept, [3600])                                 # 이미 지났으면 즉시
            ks.wait_until_send_time(datetime(2026, 11, 10, 5, 0, tzinfo=kst), sleep=slept.append)
            self.assertEqual(slept, [3600])                                 # 90분 넘게 이르면 대기하지 않음
        with patch.dict('os.environ', {}, clear=True):
            ks.wait_until_send_time(datetime(2026, 11, 10, 7, 30, tzinfo=kst), sleep=slept.append)
            self.assertEqual(slept, [3600])                                 # SEND_AT 없으면 즉시(수동 실행)

    def test_dry_run_makes_no_network_call(self):
        with tempfile.TemporaryDirectory() as d, patch.object(ks.fp, 'today', return_value='2026-11-09'), \
                patch.object(ks.fp, 'OUT', Path(d)), patch.object(ks, 'post', side_effect=AssertionError('호출 금지')):
            (Path(d) / '2026-11-09').mkdir()
            (Path(d) / '2026-11-09' / 'record.json').write_text(json.dumps(RECORD), encoding='utf-8')
            self.assertEqual(ks.main(['--dry-run']), 0)


if __name__ == '__main__':
    unittest.main()
