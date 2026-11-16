import unittest
from unittest.mock import patch

import wiki_free as w

SAMPLE = """== Sourced ==
* Courage is not the absence of fear, but the triumph over it.
** ''Letters'' (1920), p. 12
* An unsourced quote that has no citation line at all and should be dropped.
=== ''Famous Work'' (1900) ===
* The brave man is he who overcomes not only his enemies but his own fears.
== Disputed ==
* A disputed courage quote that must never be used, because it is disputed here.
** Attributed
== Quotes about Someone ==
* Somebody said this person showed great courage and honest persistence always.
** Someone
"""


class FreeSourceTests(unittest.TestCase):
    def test_only_sourced_quotes_are_kept(self):
        texts = [q['text'] for q in w.sourced_quotes(SAMPLE)]
        self.assertEqual(len(texts), 2)
        self.assertTrue(any('absence of fear' in t for t in texts))
        self.assertTrue(any('brave man' in t for t in texts))

    def test_disputed_and_about_sections_excluded(self):
        joined = ' '.join(q['text'] for q in w.sourced_quotes(SAMPLE))
        self.assertNotIn('disputed courage', joined)
        self.assertNotIn('Somebody said', joined)

    def test_song_lyrics_excluded(self):
        text = "== Sourced ==\n* As I go walking this ribbon of highway the wind keeps saying hope.\n** This Land Is Your Land (song, 1940)\n"
        self.assertEqual(w.sourced_quotes(text), [])

    def test_theme_filter(self):
        self.assertTrue(w.on_theme('He showed great courage', 'courage'))
        self.assertFalse(w.on_theme('The table is brown', 'courage'))

    def test_theme_words_need_word_start(self):
        self.assertFalse(w.on_theme('And all around me the wind keeps saying', 'success'))   # wind != win
        self.assertTrue(w.on_theme('If hard work is not another name for talent', 'success'))
        self.assertFalse(w.on_theme('A fallacy of reason', 'strength'))

    def test_songwriters_are_not_quote_sources(self):
        self.assertTrue(w.NON_QUOTE_PERSON.search('American singer-songwriter (1912–1967)'))
        self.assertFalse(w.NON_QUOTE_PERSON.search('President of the United States in 1881'))

    def test_llm_translation_is_used_when_valid(self):
        reply = {'choices': [{'message': {'content': '"노력은 재능을 대신할 수 있는 최선의 길이다."'}}]}
        with patch.dict('os.environ', {'GROQ_API_KEY': 'k'}), patch.object(w, '_post_json', return_value=reply), \
                patch.object(w, 'mymemory_ko', side_effect=AssertionError('호출 금지')):
            ko, label = w.translate_ko('Hard work is the best substitute for talent.')
        self.assertEqual(ko, '노력은 재능을 대신할 수 있는 최선의 길이다.')
        self.assertIn('AI 번역', label)

    def test_english_or_empty_llm_output_falls_back(self):
        for bad in ({'choices': [{'message': {'content': 'Hard work is the best substitute for talent.'}}]},
                    {'choices': [{'message': {'content': ''}}]}):
            with patch.dict('os.environ', {'GROQ_API_KEY': 'k'}), patch.object(w, '_post_json', return_value=bad), \
                    patch.object(w, 'mymemory_ko', return_value='대체 번역입니다.'):
                ko, label = w.translate_ko('Hard work is the best substitute for talent.')
            self.assertEqual((ko, label), ('대체 번역입니다.', '자동 번역(MyMemory)'))

    def test_api_error_falls_back_and_no_key_skips_llm(self):
        with patch.dict('os.environ', {'GROQ_API_KEY': 'k'}), patch.object(w, '_post_json', side_effect=OSError('x')), \
                patch.object(w, 'mymemory_ko', return_value='대체 번역입니다.'):
            self.assertEqual(w.translate_ko('Hello there my friend.')[0], '대체 번역입니다.')
        with patch.dict('os.environ', {}, clear=True), patch.object(w, '_post_json', side_effect=AssertionError('호출 금지')), \
                patch.object(w, 'mymemory_ko', return_value='대체 번역입니다.'):
            self.assertEqual(w.translate_ko('Hello there my friend.')[1], '자동 번역(MyMemory)')

    def test_batch_scores_parsing_and_failures(self):
        reply = {'choices': [{'message': {'content': 'sure: {"scores": [9, 3]}'}}]}
        with patch.dict('os.environ', {'GROQ_API_KEY': 'k'}), patch.object(w, '_post_json', return_value=reply):
            self.assertEqual(w.llm_scores(['Keep going.', 'War policy.']), [9, 3])
            self.assertEqual(w.llm_score('Keep going.'), None)          # 개수 불일치(2개 응답/1개 질문) → None
        wrong = {'choices': [{'message': {'content': '{"scores": [9]}'}}]}
        with patch.dict('os.environ', {'GROQ_API_KEY': 'k'}), patch.object(w, '_post_json', return_value=wrong):
            self.assertIsNone(w.llm_scores(['a', 'b']))
        with patch.dict('os.environ', {}, clear=True), patch.object(w, '_post_json', side_effect=AssertionError('호출 금지')):
            self.assertIsNone(w.llm_scores(['Keep going.']))
        with patch.dict('os.environ', {'GROQ_API_KEY': 'k'}), patch.object(w, '_post_json', side_effect=OSError('x')):
            self.assertIsNone(w.llm_scores(['Keep going.']))

    def test_rate_uses_scores_then_falls_back_to_keywords(self):
        import free_pipeline as fp
        cands = [{'text': 'Never give up on a dream.'}, {'text': 'There is in world affairs a steady course.'}]
        with patch.object(w, 'llm_scores', return_value=[9, 3]):
            self.assertEqual([s for s, _ in fp.rate(cands, {'left': 5})], [9, 3])
        with patch.object(w, 'llm_scores', return_value=None):      # 키 없음 → 키워드 대체(정치 문장만 탈락)
            self.assertEqual([s for s, _ in fp.rate(cands, {'left': 5})], [8, 3])
        with patch.object(w, 'llm_scores', side_effect=AssertionError('예산 소진 후 호출 금지')):
            self.assertEqual([s for s, _ in fp.rate(cands, {'left': 0})], [8, 3])

    def _patch_world(self, scores, people=('A Person',)):
        import free_pipeline as fp
        info = {'title': 'A Person', 'desc': 'Poet', 'ko': '가나다', 'image': 'x.jpg'}
        quotes = [{'text': f'Courage lives in quote number {i} always.', 'source': 'Book'} for i in range(3)]
        return [patch.object(w, 'theme_people', return_value=list(people)), patch.object(w, 'person_info', return_value=info),
                patch.object(w, 'wikitext', return_value=''), patch.object(w, 'sourced_quotes', return_value=quotes),
                patch.object(w, 'commons_file', return_value={'license': 'Public domain', 'artist': '', 'page': 'p', 'url': 'u'}),
                patch.object(w, 'llm_scores', return_value=scores), patch.object(w, 'translate_ko', return_value=('번역', 'AI 번역'))], fp

    def test_pick_prefers_high_score_and_accepts_relaxed_best(self):
        patches, fp = self._patch_world([9, 4, 6])
        for p in patches: p.start()
        try:
            info, portrait, cand, ko = fp.pick('courage', '2026-11-16', 0, {'people': {}, 'used': []})
            self.assertEqual(cand['text'], 'Courage lives in quote number 0 always.')     # 9점
        finally:
            for p in patches: p.stop()
        patches, fp = self._patch_world([4, 7, 5])                                    # 8점 없음 → 차선책(7점)
        for p in patches: p.start()
        try:
            cand = fp.pick('courage', '2026-11-16', 0, {'people': {}, 'used': []})[2]
            self.assertEqual(cand['text'], 'Courage lives in quote number 1 always.')
        finally:
            for p in patches: p.stop()

    def test_pick_fails_when_everything_scores_low(self):
        patches, fp = self._patch_world([2, 3, 4])
        for p in patches: p.start()
        try:
            with self.assertRaises(RuntimeError):
                fp.pick('courage', '2026-11-16', 0, {'people': {}, 'used': []})
        finally:
            for p in patches: p.stop()

    def test_make_retries_other_themes(self):
        import free_pipeline as fp
        calls = []
        def fake_pick(theme, *a, **k):
            calls.append(theme)
            raise RuntimeError('none')
        with patch.object(fp, 'pick', side_effect=fake_pick), patch.object(fp, 'load_history', return_value={'people': {}, 'used': []}):
            with self.assertRaises(RuntimeError):
                fp.make(day='2026-11-16')
            self.assertEqual(sorted(calls), sorted(w.THEMES))                           # 주제 4개 모두 시도
            calls.clear()
            with self.assertRaises(RuntimeError):
                fp.make(theme='joy', day='2026-11-16')
            self.assertEqual(calls, ['joy'])                                            # 주제를 지정하면 그것만

    def test_double_dash_is_normalized(self):
        text = "== Sourced ==\n* There is -- in this life -- always a way forward for the brave heart.\n** Letters (1900)\n"
        self.assertIn('—', w.sourced_quotes(text)[0]['text'])
        self.assertNotIn('--', w.sourced_quotes(text)[0]['text'])

    def test_sent_day_is_not_regenerated(self):
        import json
        import tempfile
        from pathlib import Path
        import free_pipeline as fp
        with tempfile.TemporaryDirectory() as d, patch.object(fp, 'ROOT', Path(d)):
            self.assertFalse(fp.already_handled('2026-11-09'))
            (Path(d) / 'data').mkdir()
            (Path(d) / 'data' / 'status.json').write_text(json.dumps({'2026-11-09': 'sent', '2026-11-08': 'failed'}))
            self.assertTrue(fp.already_handled('2026-11-09'))
            self.assertFalse(fp.already_handled('2026-11-10'))
            self.assertFalse(fp.already_handled('2026-11-08'))

    def test_clean_markup(self):
        self.assertEqual(w.clean("[[Foo|bar]] '''bold''' <br> {{cite}}[https://x.y link]"), 'bar bold link')


if __name__ == '__main__':
    unittest.main()
