"""Targeted concise repairs and progress must work across subtitles, not one anime."""
import contextlib,io,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import ollama_script as O
import subtitle_quality as Q
from glossary_support import Glossary

class TranslationRepairTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent);self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        empty=self.root/'glossary.json';empty.write_text('{}')
        for key,value in [('GLOSSARY',Glossary(empty)),('SOURCE_LANGUAGE','en'),('ACTIVE_SOURCE_LANGUAGE','en'),('ACTIVE_SERIES_HINTS',{}),('ACTIVE_PROJECT_STYLE',{}),('REVIEW_MODE','disabled')]:
            mocked=patch.object(O,key,value);mocked.start();self.addCleanup(mocked.stop)

    def test_expansion_retry_contains_rejected_output_and_actionable_instruction(self):
        value=O._retry_feedback("He's so gullible.",['excessive_expansion'],{},'Ele é tão ingênuo, acredita em qualquer coisa.',1)
        self.assertIn('Do not explain',value);self.assertIn('Rejected translation',value)
        self.assertNotIn('spellings: {}',value)
        self.assertNotEqual(value,O._retry_feedback("He's so gullible.",['excessive_expansion'],{},'Ele é tão ingênuo, acredita em qualquer coisa.',2))

    def test_valid_short_repair_completes_without_relaxing_validator(self):
        source=self.root/'episode.srt';source.write_text("1\n00:00:01,000 --> 00:00:03,000\nHe's so gullible.\n",encoding='utf-8')
        rejected='Ele é tão ingênuo, acredita em qualquer coisa.'
        self.assertIn('excessive_expansion',Q.quality_flags("He's so gullible.",rejected,2,{},'en'))
        with patch.object(O,'_ollama_call',side_effect=[rejected,'Ele é tão ingênuo.']) as call:
            result=O.translate_paths([source],self.root/'out')[0]
        self.assertEqual(call.call_count,2)
        self.assertIn(rejected,call.call_args.args[1][0]['content'])
        self.assertIn('Ele é tão ingênuo.',result.read_text(encoding='utf-8'))
        self.assertFalse(Path(str(result)+'.review_required.json').exists())

    def test_isolated_english_is_repaired_before_checkpoint(self):
        source=self.root/'episode.srt'
        source.write_text('1\n00:00:01,000 --> 00:00:04,000\nIt cries "cuckoo".\n',encoding='utf-8')
        with patch.object(O,'_ollama_call',side_effect=['Ele faz "cuckoo".','Ele faz "cuco".']) as call:
            result=O.translate_paths([source],self.root/'out')[0]
        self.assertEqual(call.call_count,2)
        self.assertNotIn('cuckoo',result.read_text(encoding='utf-8'))
        self.assertIn('cuco',result.read_text(encoding='utf-8'))
        self.assertIn('Translate the remaining ordinary English words',call.call_args.args[1][0]['content'])

    def test_colloquial_spying_accusation_does_not_require_private_glossary(self):
        with patch.object(O,'_ollama_call',return_value='Um tarado!') as call:
            O._context_call('model','A Peeping Tom!','','',{})
        prompt=call.call_args.args[1][0]['content']
        self.assertIn('use tarado',prompt)
        self.assertIn('explicit glossary overrides',prompt)

    def test_repair_drops_unrelated_spelling_reference_but_keeps_required_term(self):
        with patch.object(O,'ACTIVE_SERIES_HINTS',{'Unrelated Name':'Outro Nome'}),patch.object(O,'_ollama_call',return_value='Kaito chegou.') as call:
            O._context_call('model','Kaito arrived.','Unrelated earlier line','Unrelated following line',{'Kaito':'Kaito'},feedback='excessive_expansion')
        prompt=call.call_args.args[1][0]['content']
        self.assertNotIn('Unrelated Name',prompt);self.assertNotIn('Unrelated earlier line',prompt)
        self.assertIn('"Kaito": "Kaito"',prompt)

    def test_invented_name_is_not_echoed_back_in_entity_repair(self):
        feedback=O._retry_feedback('Are you back from school?',['context_entity_leak'],{},'Você voltou, Yuna?',1)
        with patch.object(O,'ACTIVE_SERIES_HINTS',{'Yuna':'Yuna'}),patch.object(O,'_ollama_call',return_value='Você voltou da escola?') as call:
            O._context_call('model','Are you back from school?','Yuna arrived.','Yuna speaks.',{},feedback)
        prompt=call.call_args.args[1][0]['content']
        self.assertNotIn('Yuna',prompt)
        self.assertIn('original source only',prompt)

    def test_common_address_is_not_confused_with_glossary_entity(self):
        self.assertEqual(Q.context_flags("I'm sorry! Are you alright, Miss?",'Desculpa! Você está bem, mocinha?',{'Missy':'mocinha'}),[])
        self.assertIn('context_entity_leak',Q.context_flags('I miss you.','Sinto sua falta, mocinha.',{'Missy':'mocinha'}))
        self.assertIn('context_entity_leak',Q.context_flags('Miss, wait.','Mocinha, espere por Yuna.',{'Missy':'mocinha','Yuna':'Yuna'}))
        self.assertIn('context_entity_leak',Q.context_flags('Wait.','Yuna, espere.',{'Yuna':'Yuna'}))

    def test_preview_title_is_a_caption_and_never_invents_a_destination(self):
        for name in ('Aster','Yuna','Vai'):
            self.assertEqual(Q.preview_heading('next '+name.lower(),{name:name}),'A seguir, '+name+'.')
            self.assertIn('preview_caption_invention',Q.quality_flags('next '+name,name+' segue para o próximo local.',2,{name:name},'en'))
            self.assertNotIn('preview_caption_invention',Q.quality_flags('next '+name,'A seguir, '+name+'.',2,{name:name},'en'))
        self.assertIsNone(Q.preview_heading('Next, Aster!',{'Aster':'Aster'}))
        self.assertIsNone(Q.preview_heading('next place',{}))

    def test_resume_does_not_print_percentages_from_beginning(self):
        source=self.root/'episode.srt'
        source.write_text(''.join(str(i+1)+'\n00:00:01,000 --> 00:00:03,000\nHello there.\n\n' for i in range(12)),encoding='utf-8')
        out=self.root/'out';cache={};progress={}
        with patch.object(O,'_ollama_call',return_value='Olá.'):
            O.translate_srt(source,out/'first.srt','translategemma:12b',cache,progress)
        # Keep a non-contiguous checkpoint, like an interrupted/corrected season.
        entries=[key for key in cache if key.rsplit(':',1)[-1].isdigit()]
        for key in entries:
            if int(key.rsplit(':',1)[-1])>=7:del cache[key]
        console=io.StringIO()
        with contextlib.redirect_stdout(console),patch.object(O,'_ollama_call',return_value='Olá.'):
            O.translate_srt(source,out/'resumed.srt','translategemma:12b',cache,progress)
        self.assertIn('(7/12)',console.getvalue());self.assertNotIn('(5/12)',console.getvalue())

if __name__=='__main__':unittest.main()
