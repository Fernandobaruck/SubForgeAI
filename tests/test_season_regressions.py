from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ollama_script as O
import subtitle_quality as Q
from glossary_support import Glossary


class SeasonRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent);self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);g=self.root/'global.json';g.write_text('{}', encoding='utf-8')
        for name,value in [('GLOSSARY',Glossary(g)),('SOURCE_LANGUAGE','en'),('ACTIVE_SOURCE_LANGUAGE','en'),('REVIEW_MODE','disabled')]:
            mocked=patch.object(O,name,value);mocked.start();self.addCleanup(mocked.stop)

    def source(self,text,name='episode.srt'):
        p=self.root/name;p.write_text('1\n00:00:01,000 --> 00:00:05,000\n'+text+'\n', encoding='utf-8');return p

    def seed(self,source,values):
        series=Q.SeriesTerms(source,[],self.root/'out/_cache_traducao','en')
        O._save_json(series.path,values)
        return series

    def test_common_words_are_never_required_by_automatic_cache(self):
        for word,translation in [('Save','Salve'),('Give','Dê'),('Journey','Jornada'),('Other','Outro'),('One','Um')]:
            source=self.source(word+'!',word+'.srt')
            self.seed(source,{word:word})
            with patch.object(O,'_ollama_call',return_value=translation+'!') as call:
                output=O.translate_paths([source],self.root/'out')[0]
            self.assertIn(translation,output.read_text(encoding='utf-8'))
            self.assertNotIn('Required series terminology',call.call_args.args[1][0]['content'])

    def test_phrase_beats_its_components(self):
        source=self.source('The Deep Dragon is here.')
        self.seed(source,{'Deep':'Deep','Dragon':'Dragon','Deep Dragon':'Dragão Abissal'})
        with patch.object(O,'_ollama_call',return_value='O Dragão Abissal está aqui.') as call:
            O.translate_paths([source],self.root/'out')
        prompt=call.call_args.args[1][0]['content']
        self.assertIn('"Deep Dragon": "Dragão Abissal"',prompt)
        self.assertNotIn('"Dragon":',prompt);self.assertNotIn('"Deep":',prompt)

    def test_explicit_terms_have_priority_and_articles_can_contract(self):
        chosen=Q.longest_matches({'The Moon Archive':'O Arquivo Lunar','Moon Archive':'Arquivo Lunar','Archive':'Archive'},'The Moon Archive')
        self.assertEqual(chosen,{'The Moon Archive':'O Arquivo Lunar'})
        self.assertNotIn('terminology',Q.quality_flags('The Moon Archive','Venho do Arquivo Lunar.',4,chosen))
        self.assertIn('terminology',Q.quality_flags('The Moon Archive','Venho da biblioteca.',4,chosen))

    def test_unconfirmed_variation_is_reported_without_blocking_file(self):
        source=self.source('The Deep Dragon is here.')
        self.seed(source,{'Deep Dragon':'Dragão Abissal'})
        with patch.object(O,'_ollama_call',return_value='O Dragão Profundo está aqui.'):
            result=O.translate_paths([source],self.root/'out')[0]
        report=json.loads(result.with_suffix('.srt.quality.json').read_text(encoding='utf-8'))
        self.assertIn('suggested_terminology',report['findings'][0]['flags'])

    def test_new_episode_vocabulary_does_not_reset_checkpoint(self):
        source=self.source('Hello there.')
        with patch.object(O,'_ollama_call',return_value='Olá.'):
            O.translate_paths([source],self.root/'out')
        series=Q.SeriesTerms(source,[],self.root/'out/_cache_traducao','en')
        O._save_json(series.path,{'New Name':'New Name','Other':'Other','Journey':'Journey'})
        with patch.object(O,'_ollama_call',side_effect=AssertionError('valid checkpoint was lost')):
            O.translate_paths([source],self.root/'out')

    def test_old_context_checkpoint_is_migrated_without_new_request(self):
        source=self.source('<i>Hello there.</i>');out=self.root/'out';cache={};progress={}
        base=O._cache_context(source,'translategemma:12b',['<i>Hello there.</i>'],'.srt')
        old=base+':'+('a'*40)+':0';cache[old]='<i>Olá.</i>'
        with patch.object(O,'_ollama_call',side_effect=AssertionError('old checkpoint was not migrated')):
            O.translate_srt(source,out/'result.srt','translategemma:12b',cache,progress)
        self.assertIn('<i>Olá.</i>',(out/'result.srt').read_text(encoding='utf-8'))
        self.assertIn(old,cache)
        self.assertTrue(any(':season-safe:' in key for key in cache))

    def test_semantic_invention_blocks_publication_after_bounded_retries(self):
        source=self.source('Next episode.')
        with patch.object(O,'_ollama_call',return_value='No próximo episódio ele vai lutar contra todos os inimigos da cidade.') as call:
            with self.assertRaises(O.TranslationBatchError):O.translate_paths([source],self.root/'out')
        self.assertEqual(call.call_count,O.MAX_RETRIES)
        self.assertFalse(list((self.root/'out').glob('*.srt')))
        report=json.loads(next((self.root/'out').glob('*.review_required.json')).read_text(encoding='utf-8'))
        self.assertIn('excessive_expansion',report['reason'])


if __name__=='__main__':unittest.main()
