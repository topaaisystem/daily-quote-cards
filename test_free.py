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

    def test_clean_markup(self):
        self.assertEqual(w.clean("[[Foo|bar]] '''bold''' <br> {{cite}}[https://x.y link]"), 'bar bold link')


if __name__ == '__main__':
    unittest.main()
