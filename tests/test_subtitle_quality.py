from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import subtitle_quality as Q
import ollama_script as O
from glossary_support import Glossary


class QualityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent);self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        path = self.root/'glossary.json';path.write_text('{}', encoding='utf-8')
        for name,value in [('GLOSSARY',Glossary(path)),('ACTIVE_SOURCE_LANGUAGE','en'),('SOURCE_LANGUAGE','en')]:
            mocked=patch.object(O,name,value);mocked.start();self.addCleanup(mocked.stop)

    def test_visual_breaks_do_not_split_semantics(self):
        safe,tokens,prefix,suffix=Q.prepare('<i>Since you first\nbegan teaching her magic.</i>')
        self.assertEqual(safe,'Since you first began teaching her magic.')
        self.assertEqual(Q.restore('Desde que você começou a ensinar magia a ela.',tokens,prefix,suffix),
                         '<i>Desde que você começou a ensinar magia a ela.</i>')

    def test_speaker_boundaries_and_inline_tags_are_strict(self):
        source='- Wait!\n- The <i>ship</i> is here!'
        safe,tokens,prefix,suffix=Q.prepare(source)
        self.assertIn('ZXQFMT0QXZ',safe)
        self.assertEqual(Q.restore(safe,tokens,prefix,suffix),source)
        for bad in [safe.replace('ZXQFMT0QXZ',''),safe+'ZXQFMT0QXZ',safe.replace('ZXQFMT0QXZ','ZXQFMT99QXZ')]:
            with self.assertRaises(ValueError): Q.restore(bad,tokens,prefix,suffix)

    def test_reflow_preserves_all_words_and_format(self):
        text='<i>Este é um exemplo de frase comprida que precisa ser dividida sem perder nenhuma palavra.</i>'
        wrapped=Q.reflow(text)
        self.assertEqual(Q.plain(wrapped),Q.plain(text))
        self.assertEqual(wrapped.count('\n'),1)
        self.assertIn('<i>',wrapped);self.assertIn('</i>',wrapped)
        self.assertIn(r'\N',Q.reflow(text,ass=True))

    def test_inline_alignment_keeps_full_sentence_translation(self):
        target='Os Cavaleiros Estelares estão chegando.'
        result=Q.align_inline('The <i>Star Knights</i> are coming.',target,lambda _: 'Cavaleiros Estelares')
        self.assertEqual(result,'Os <i>Cavaleiros Estelares</i> estão chegando.')
        self.assertEqual(Q.plain(result),target)
        with self.assertRaises(ValueError):
            Q.align_inline('The <i>ship</i> and the ship.', 'O navio e o navio.',lambda _: 'navio')

    def test_inline_alignment_preserves_ass_emphasis(self):
        result=Q.align_inline(r'The {\i1}Star Knights{\i0} are coming.',
                              'Os Cavaleiros Estelares estão chegando.',lambda _:'Cavaleiros Estelares')
        self.assertEqual(result,r'Os {\i1}Cavaleiros Estelares{\i0} estão chegando.')

    def test_names_generalize_and_ordinary_words_are_not_entities(self):
        names=Q.detect_names(['Yuna, wait for Riven!', 'Riven is searching for Yuna.', 'Aster!',
                              "It's difficult.","That's it.",'Bad...','Naive! Naive!','Nakedness?'])
        self.assertTrue({'Yuna','Riven','Aster'}<=names.keys())
        self.assertFalse({"It's","That's",'Bad','Naive','Nakedness'} & names.keys())
        self.assertTrue(Q.contains('A Torre dos\nDentes está aqui.', 'Torre dos Dentes'))

    def test_series_are_isolated_and_explicit_glossary_wins(self):
        a=self.root/'a';b=self.root/'b';a.mkdir();b.mkdir()
        (a/'series_glossary.json').write_text('{"Yuna":"Yunna"}', encoding='utf-8')
        first=Q.SeriesTerms(a/'ep1.srt',['Yuna!'],self.root/'cache','en')
        other=Q.SeriesTerms(b/'ep1.srt',['Yuna!'],self.root/'cache','en')
        self.assertEqual(first.values['Yuna'],'Yunna')
        self.assertEqual(other.values['Yuna'],'Yuna')
        self.assertNotEqual(first.path,other.path)

    def test_terminology_and_hallucination_flags(self):
        self.assertIn('terminology',Q.quality_flags('Yuna!','Flor!',2,{'Yuna':'Yuna'}))
        self.assertIn('unsupported_show_reference',Q.quality_flags('Big Brother?','Programa Big Brother?',2,{}))
        self.assertIn('unsupported_company_reference',Q.quality_flags('Master?','A empresa Master?',2,{}))
        self.assertNotIn('unsupported_company_reference',Q.quality_flags('The company is here.','A empresa está aqui.',2,{}))
        self.assertIn('gender_alternatives',Q.quality_flags('Thanks','Obrigado(a)',2,{}))
        self.assertIn('possessive_shift',Q.quality_flags('Your friend is here.','Meu amigo está aqui.',3,{}))
        self.assertIn('context_entity_leak',Q.context_flags('Aster!','Aster, proteja Yuna!',{'Aster':'Aster','Yuna':'Yuna'}))
        self.assertIn('excessive_expansion',Q.quality_flags('Next episode.','No próximo episódio ele vai lutar contra todos os inimigos da cidade.',3,{}))
        self.assertNotIn('unsupported_company_reference',Q.quality_flags('会社に行く','Vou à empresa.',3,{},'ja'))

    def test_readability_uses_actual_duration_and_never_truncates(self):
        self.assertAlmostEqual(Q.duration('00:01:02,000 --> 00:01:04,500'),2.5)
        self.assertAlmostEqual(Q.duration('00:02.000 --> 00:03.000 align:start'),1)
        self.assertIn('reading_speed',Q.quality_flags('', 'a'*43,1,{}))
        self.assertEqual(Q.reflow('a'*100),'a'*100)

    def test_context_changes_prompt_without_translating_neighbors(self):
        with patch.object(O,'_ollama_call',return_value='O que o Mestre pretende fazer?') as call:
            O._context_call('translategemma:12b','What is Master planning to do?',
                            'He is my teacher.','We must ask him.',{},budget=60)
        prompt=call.call_args.args[1][0]['content']
        self.assertIn('He is my teacher.',prompt)
        self.assertTrue(prompt.endswith('\n\n\nWhat is Master planning to do?'))
        self.assertIn('never translate or quote this background',prompt)

    def test_short_reactions_do_not_receive_neighbor_dialogue(self):
        with patch.object(O,'_ollama_call',return_value='Ah, bom.') as call:
            O._context_call('translategemma:12b','Oh, well.','A big dinner.','My teacher is here.',{})
        prompt=call.call_args.args[1][0]['content']
        self.assertNotIn('A big dinner.',prompt)
        self.assertNotIn('My teacher is here.',prompt)

    def test_mixed_script_english_is_not_misclassified_as_japanese(self):
        with patch.object(O,'SOURCE_LANGUAGE','auto'):
            self.assertEqual(O._detect_source_language(('You must be careful because they are looking for us. '*8)+'ありがとう'),'en')

    def test_full_pipeline_resume_and_quality_report(self):
        source=self.root/'ep.srt';source.write_text('1\n00:00:01,000 --> 00:00:04,000\n<i>Hello\nthere.</i>\n', encoding='utf-8')
        with patch.object(O,'_ollama_call',return_value='Olá.') as call:
            first=O.translate_paths([source],self.root/'out')[0]
        self.assertEqual(call.call_count,1)
        self.assertIn('<i>Olá.</i>',first.read_text(encoding='utf-8'))
        self.assertTrue(first.with_suffix('.srt.quality.json').is_file())
        with patch.object(O,'_ollama_call',side_effect=AssertionError('must resume')):
            second=O.translate_paths([source],self.root/'out')[0]
        self.assertEqual(first.read_text(encoding='utf-8'),second.read_text(encoding='utf-8'))

    def test_bad_output_does_not_publish_or_cache_current_item(self):
        source=self.root/'ep.srt';source.write_text('1\n00:00:01,000 --> 00:00:04,000\nYuna is here.\n', encoding='utf-8')
        (self.root/'series_glossary.json').write_text('{"Yuna":"Yuna"}', encoding='utf-8')
        with patch.object(O,'_ollama_call',return_value='Flor!'):
            with self.assertRaises(O.TranslationBatchError):O.translate_paths([source],self.root/'out')
        self.assertFalse(list((self.root/'out').glob('*.srt')))
        cache=O._load_json(self.root/'out/_cache_traducao/cache.json')
        self.assertFalse(cache)

    def test_vtt_notes_and_ass_nonstandard_columns_survive(self):
        vtt=self.root/'ep.vtt';vtt.write_text('WEBVTT\n\nNOTE metadata\nkeep\n\nid\n00:01.000 --> 00:04.000 align:start\nHello\nthere.\n', encoding='utf-8')
        ass=self.root/'ep.ass';ass.write_text('[Script Info]\nTitle: Test\n[Events]\nFormat: Layer, End, Start, Text\nDialogue: 0,0:00:04.00,0:00:01.00,{\\i1}Hello\\Nthere.{\\i0}\n', encoding='utf-8')
        with patch.object(O,'_ollama_call',return_value='Olá.'):
            outputs=O.translate_paths([vtt,ass],self.root/'out')
        self.assertIn('NOTE metadata\nkeep',outputs[0].read_text(encoding='utf-8'))
        self.assertIn('align:start',outputs[0].read_text(encoding='utf-8'))
        self.assertIn('Dialogue: 0,0:00:04.00,0:00:01.00,{\\i1}Olá.{\\i0}',outputs[1].read_text(encoding='utf-8'))


if __name__=='__main__':unittest.main()
