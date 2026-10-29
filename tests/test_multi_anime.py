"""Regressions found in multiple public anime subtitle formats."""
import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import ollama_script as O
import subtitle_quality as Q
from glossary_support import Glossary
from subtitle_formats import SubtitleTemplate

class MultiAnimeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent);self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);empty=self.root/'glossary.json';empty.write_text('{}',encoding='utf-8')
        for name,value in [('GLOSSARY',Glossary(empty)),('SOURCE_LANGUAGE','en'),('ACTIVE_SOURCE_LANGUAGE','en'),('ACTIVE_SERIES_HINTS',{}),('REVIEW_MODE','disabled')]:
            p=patch.object(O,name,value);p.start();self.addCleanup(p.stop)
    def test_invisible_tags_do_not_split_words(self):
        self.assertEqual(Q.plain(r'Beg{\frz354.2}o{*\frz353.7}n{\frz353.2}e'),'Begone')
        self.assertEqual(Q.plain('H<i>ell</i>o'),'Hello')
        self.assertEqual(Q.plain(r'Hello\Nworld\hagain'),'Hello world again')
    def test_romanized_lyrics_and_english_names_are_distinguished(self):
        self.assertTrue(Q.romanized_japanese('kumo no kirema sagasu'))
        self.assertFalse(Q.romanized_japanese('Sora and Yuki are here.'))
    def test_household_title_requires_evidence_and_respects_context(self):
        self.assertEqual(Q.contextual_address_terms('Young Master!'),{})
        self.assertEqual(Q.contextual_address_terms('Young Master, your father is calling.'),{'Young Master':'jovem senhor'})
        self.assertNotIn('Young Master',Q.detect_terms(['Young Master, your father calls.']*2))
        source=self.root/'household.srt'
        source.write_text('1\n00:00:01,000 --> 00:00:08,000\nYoung Master, your father is calling.\n',encoding='utf-8')
        with patch.object(O,'_ollama_call',return_value='Jovem senhor, seu pai está chamando.'):
            output=O.translate_paths([source],self.root/'out')[0]
        self.assertIn('Jovem senhor',output.read_text(encoding='utf-8'))

    def test_romanized_source_remains_flagged_for_human_review(self):
        source=self.root/'lyrics.srt';source.write_text('1\n00:00:01,000 --> 00:00:08,000\nkumo no kirema sagasu\n',encoding='utf-8')
        with patch.object(O,'_ollama_call',return_value='Procuro uma abertura entre as nuvens.'):
            output=O.translate_paths([source],self.root/'out')[0]
        report=json.loads(Path(str(output)+'.quality.json').read_text(encoding='utf-8'))
        self.assertIn('romanized_source',report['findings'][0]['flags'])

    def test_prepared_glossary_matches_original_rules_and_updates(self):
        from glossary_support import _matches_prepared,_fold
        mapping={'coracao':'coração','オーフェン':'Orphen','cat':'gato','C++':'linguagem'}
        path=self.root/'terms.json';path.write_text(json.dumps(mapping,ensure_ascii=False),encoding='utf-8');glossary=Glossary(path)
        for text in ('O coração dela.','オーフェン chegou.','cat category gato','C++ language','Nothing matches.'):
            for term in (*mapping.keys(),*mapping.values()):
                self.assertEqual(glossary.matches(term,text),_matches_prepared(term,text,_fold(text)))
        self.assertIn('coração',glossary.prompt(['coracao']))
        path.write_text(json.dumps({'novo':'new'}),encoding='utf-8')
        self.assertNotIn('coração',glossary.prompt(['coracao']))
        self.assertIn('novo',glossary.prompt(['new']))

    def test_japanese_caption_boundaries_survive_preparation(self):
        original='ここまでは知ってるよね？\n（フェルン）はい。'
        self.assertTrue(Q.semantic_breaks(original))
        safe,tokens,prefix,suffix=Q.prepare(original)
        self.assertIn('\n',Q.request_text(safe,tokens))
        self.assertEqual(Q.restore(safe,tokens,prefix,suffix),original)
        self.assertFalse(Q.semantic_breaks('長い文章の\n普通の折り返し'))
        with self.assertRaises(ValueError):Q.align_inline(original,'Você sabe disso? Sim.',lambda span:span)
    def test_cached_merge_of_two_japanese_speakers_is_retranslated(self):
        source=self.root/'speakers.srt';source.write_text('1\n00:00:01,000 --> 00:00:08,000\n（甲）おはよう。\n（乙）はい。\n',encoding='utf-8')
        out=self.root/'out';answer='(A) Bom dia.\n(B) Sim.'
        with patch.object(O,'SOURCE_LANGUAGE','ja'),patch.object(O,'_ollama_call',return_value=answer):
            O.translate_paths([source],out)
        checkpoint=out/'_cache_traducao/cache.json';cache=json.loads(checkpoint.read_text(encoding='utf-8'))
        key=next(key for key in cache if key.endswith(':0'));cache[key]='Bom dia. Sim.'
        checkpoint.write_text(json.dumps(cache),encoding='utf-8')
        with patch.object(O,'SOURCE_LANGUAGE','ja'),patch.object(O,'_ollama_call',return_value=answer) as call:
            target=O.translate_paths([source],out)[0]
        self.assertGreater(call.call_count,0)
        self.assertEqual(O.parse_srt(target.read_text(encoding='utf-8'))[0][2],answer)

    def test_music_marks_survive_translation_without_model_cooperation(self):
        source='♪ 歌の言葉'
        safe,tokens,prefix,suffix=Q.prepare(source)
        self.assertNotIn('♪',safe)
        self.assertEqual(Q.restore('Palavras da canção',tokens,prefix,suffix),'♪ Palavras da canção')
    def test_interjection_explanations_are_flagged_but_real_annotations_are_allowed(self):
        bad='Uu... (Expressões de angústia ou sofrimento).'
        self.assertIn('translator_explanation',Q.quality_flags('ううっ うあああ…',bad,5,{},'ja'))
        self.assertNotIn('translator_explanation',Q.quality_flags('（叫び声）','(Som de grito)',5,{},'ja'))

    def test_master_prompt_allows_household_role(self):
        with patch.object(O,'_ollama_call',return_value='Jovem senhor.') as call:
            O._context_call('translategemma:12b','Young Master, your father is calling for you.','','',{})
        prompt=call.call_args.args[1][0]['content']
        self.assertIn('household heir',prompt)
        self.assertNotIn('Master is a form of address for the teacher',prompt)
    def test_exact_requests_reused_but_context_and_feedback_are_not(self):
        token=O.CONTEXT_REQUEST_STATE.set({'cache':{},'hits':0,'calls':0});self.addCleanup(O.CONTEXT_REQUEST_STATE.reset,token)
        with patch.object(O,'_ollama_call',return_value='Aguarde aqui por mim.') as call:
            request=lambda before='',feedback='':O._context_call('translategemma:12b','Wait here for me.',before,'',{},feedback)
            self.assertEqual(request(),request());self.assertEqual(call.call_count,1)
            request(before='Different speaker.');self.assertEqual(call.call_count,2)
            request(feedback='terminology');request(feedback='terminology');self.assertEqual(call.call_count,4)
    def test_request_scope_is_reset_on_failure(self):
        with patch.object(O,'_translate_context_document_impl',side_effect=ValueError('bad file')):
            with self.assertRaises(ValueError):O._translate_context_document(None,None,None,None,None)
        self.assertIsNone(O.CONTEXT_REQUEST_STATE.get())
    def test_repeated_cues_keep_all_times_and_pass_validation(self):
        source=self.root/'repeat.srt'
        source.write_text('\n\n'.join(f'{i}\n00:00:{i*2:02},000 --> 00:00:{i*2+7:02},000\nWait here for me.' for i in range(1,11)),encoding='utf-8')
        with patch.object(O,'_ollama_call',return_value='Aguarde aqui por mim.') as call:
            output=O.translate_paths([source],self.root/'out')[0]
        self.assertEqual(call.call_count,5)
        original=O.parse_srt(source.read_text());translated=O.parse_srt(output.read_text(encoding='utf-8'))
        self.assertEqual([x[:2] for x in original],[x[:2] for x in translated]);self.assertEqual(len(translated),10)
        report=json.loads(Path(str(output)+'.quality.json').read_text(encoding='utf-8'))
        self.assertEqual(report['request_reuse'],{'hits':5,'calls':5});self.assertEqual(report['needs_review'],0)
    def test_renderer_keeps_existing_mixed_line_endings(self):
        source='HEADER\r\nhello\nTAIL\r\n'
        template=SubtitleTemplate(source,[(8,13)])
        self.assertEqual(template.render(['hello']),source)
        self.assertEqual(template.render(['hello\nworld']),'HEADER\r\nhello\r\nworld\nTAIL\r\n')
