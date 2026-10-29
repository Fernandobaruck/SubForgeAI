from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ollama_script as O
import profile_manager as P
from glossary_support import Glossary


class TranslateGemmaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        path = self.root / 'glossary.json'; path.write_text('{}', encoding='utf-8')
        for name, value in [('GLOSSARY', Glossary(path)), ('REVIEW_MODE', 'disabled'),
                            ('ACTIVE_SOURCE_LANGUAGE', 'en'), ('SOURCE_LANGUAGE', 'auto')]:
            mocked = patch.object(O, name, value); mocked.start(); self.addCleanup(mocked.stop)

    def test_all_profiles_use_new_model(self):
        self.assertEqual({p['ollama_model'] for p in P.KEY_TO_PROFILE.values()}, {'translategemma:12b'})
        self.assertEqual(O.MODELO_OLLAMA, 'translategemma:12b')

    def test_direct_single_user_prompt_and_tag_preservation(self):
        with patch.object(O, '_ollama_call', return_value='Olá') as call:
            result = O._translate_batch('translategemma:12b', ['<i>Hello</i>'])
        self.assertEqual(result, ['<i>Olá</i>'])
        messages = call.call_args.args[1]
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]['role'], 'user')
        self.assertIn('English (en)', messages[0]['content'])
        self.assertIn('(pt-BR)', messages[0]['content'])
        self.assertIn('\n\n\nHello', messages[0]['content'])
        self.assertNotIn('⟦TAG', messages[0]['content'])
        self.assertNotIn('<<<1>>>', messages[0]['content'])

    def test_display_breaks_do_not_split_translation(self):
        with patch.object(O, '_ollama_call', return_value='Primeira e segunda.') as call:
            self.assertEqual(O._translategemma_item('translategemma:12b', 'First\nSecond'), 'Primeira e segunda.')
        self.assertEqual(call.call_count, 1)
        self.assertTrue(call.call_args.args[1][0]['content'].endswith('First Second'))

    def test_glossary_is_restored_with_format_in_source_order(self):
        path = self.root / 'terms.json'; path.write_text(json.dumps({'Orphen': 'Orphen', 'sword': 'espada'}), encoding='utf-8')
        with patch.object(O, 'GLOSSARY', Glossary(path)), patch.object(O, '_ollama_call') as call:
            def translate(model, messages):
                self.assertIn('"sword" -> "espada"', messages[0]['content'])
                self.assertIn('adapt grammar', messages[0]['content'])
                return 'A espada pertence a Orphen.'
            call.side_effect = translate
            self.assertEqual(O._translategemma_item('translategemma:12b', '<i>The sword belongs to Orphen.</i>'),
                             '<i>A espada pertence a Orphen.</i>')

    def test_invented_tags_and_incomplete_output_are_rejected(self):
        for reply in ['<i>Oi</i>', 'Oi\nOutra fala', '', '<<<1>>>Oi']:
            with patch.object(O, '_ollama_call', return_value=reply):
                with self.assertRaises(O.InvalidModelOutput):
                    O._translategemma_item('translategemma:12b', 'Hello')

    def test_language_detection_and_override(self):
        self.assertEqual(O._detect_source_language('あなたは何をしているのですか。'), 'ja')
        self.assertEqual(O._detect_source_language('You must be careful because they are looking for us. ' * 8), 'en')
        self.assertEqual(O._detect_source_language('Je ne sais pas pourquoi vous êtes ici. ' * 8), 'fr')
        with patch.object(O, 'SOURCE_LANGUAGE', 'es'):
            self.assertEqual(O._detect_source_language('Hello'), 'es')

    def test_cache_separates_languages_and_models(self):
        path = self.root / 'source.srt'
        en = O._cache_context(path, 'translategemma:12b', ['Hello'], 'srt')
        old = O._cache_context(path, 'qwen2.5:14b', ['Hello'], 'srt')
        with patch.object(O, 'ACTIVE_SOURCE_LANGUAGE', 'ja'):
            ja = O._cache_context(path, 'translategemma:12b', ['Hello'], 'srt')
        self.assertEqual(len({en, old, ja}), 3)

    def test_legacy_review_migrates_and_resume_preserves_cache(self):
        source = self.root / 'sample.srt'
        source.write_text('1\n00:00:00,000 --> 00:00:01,000\n<i>Hello</i>\n', encoding='utf-8')
        with patch.object(O, 'REVIEW_MODE', 'enabled_plus'), patch.object(O, 'SOURCE_LANGUAGE', 'en'):
            with patch.object(O, '_ollama_call', return_value='Olá') as call:
                first = O.translate_paths([source], self.root / 'out')
                self.assertEqual(call.call_count, 1)
            with patch.object(O, '_ollama_call', side_effect=AssertionError('cache was lost')):
                second = O.translate_paths([source], self.root / 'out')
        self.assertEqual(first[0].read_text(encoding='utf-8'), second[0].read_text(encoding='utf-8'))
        self.assertIn('<i>Olá</i>', first[0].read_text(encoding='utf-8'))

    def test_auto_review_rejects_untranslated_english(self):
        with patch.object(O, 'REVIEW_MODE', 'auto'), patch.object(O, '_ollama_call', return_value='The cat is here.'):
            with self.assertRaises(O.InvalidModelOutput):
                O._translate_batch('translategemma:12b', ['The cat is here.'])


if __name__ == '__main__': unittest.main()
