from pathlib import Path
import sys
import unittest
import tempfile
import json
from unittest.mock import Mock,patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import subtitle_editor as E
import subtitle_quality as Q
import ollama_script as O


class EditorialTests(unittest.TestCase):
    def test_romaji_is_distinguished_from_names_and_ordinary_english(self):
        for text in ['Kuchibiru ni dake','Kono te de omae o mamoritai','Wakaranai','Abiru hodo dakiattari kuchizuke shitari']:
            self.assertTrue(Q.romanized_japanese(text),text)
        for text in ['Save!','Journey','Deep Dragon','Majic?','Your father is here.','I found ore to sell.','Aitsu told you to come.']:
            self.assertFalse(Q.romanized_japanese(text),text)

    def test_romaji_conversion_preserves_english_words_and_grammar_particles(self):
        self.assertEqual(Q.japanese_input('Omae to fly'),'おまえ と fly')
        self.assertEqual(Q.japanese_input('Kuchibiru ni dake'),'くちびる に だけ')
        self.assertEqual(Q.japanese_input('Omae wa watashi o miru'),'おまえ は わたし を みる')
        self.assertEqual(Q.japanese_input('ZXQFMT0QXZ omae ZXQFMT1QXZ'),'ZXQFMT0QXZ おまえ ZXQFMT1QXZ')
        self.assertEqual(Q.japanese_input('Kaito wa watashi o miru',protected=['Kaito']),'Kaito は わたし を みる')

    def test_source_ocr_and_duplicate_caption_are_explicitly_noted(self):
        self.assertEqual(E.normalized_source('1, the black sorcerer.')[0],'I, the black sorcerer.')
        value,notes=E.normalized_source('the terror Of BLOOJY AUGUST\n"The Terror of Bloody August."')
        self.assertEqual(value,'The Terror of Bloody August.')
        self.assertIn('source_duplicate_caption',notes)
        self.assertEqual(E.normalized_source('Use 1, the first number.')[0],'Use 1, the first number.')

    def test_postedit_does_not_repeat_neighbour_dialogue(self):
        call=Mock(return_value='Não entendo.')
        E.postedit(call,'model','Wakaranai','Wakaranai','An earlier sentence','A following sentence',{},2)
        prompt=call.call_args.args[1][0]['content']
        self.assertNotIn('An earlier sentence',prompt);self.assertNotIn('A following sentence',prompt)
        self.assertNotIn('Portuguese draft to correct',prompt)
        self.assertTrue(prompt.endswith('わからない'))

    def test_editor_rejects_subject_changes_and_preserves_approved_aliases(self):
        self.assertIn('possessive_shift',E.validate('Your father paid me.','Meu pai me pagou.',{},{}))
        self.assertNotIn('context_entity_leak',E.validate('The sword of Baltandenrs.','A Espada de Baltanders.',
            {'Baltandenrs':'Baltanders'},{'Baltanders':'Baltanders'}))

    def test_render_does_not_destroy_outer_tags_or_add_visual_wrap_meaning(self):
        rendered=E.render('<i>Hello\nthere.</i>','Olá.\nComo vai?',lambda _:None)
        self.assertEqual(rendered,'<i>Olá. Como vai?</i>')

    def test_main_translation_api_detects_romaji_per_cue(self):
        with patch.object(O,'ACTIVE_SOURCE_LANGUAGE','en'),patch.object(O,'_ollama_call',return_value='Não entendo.') as call:
            self.assertEqual(O._context_call('model','Wakaranai','previous','following',{}),'Não entendo.')
        prompt=call.call_args.args[1][0]['content']
        self.assertIn('Japanese (ja)',prompt)
        self.assertTrue(prompt.endswith('わからない'))
        self.assertNotIn('previous',prompt)

    def test_confirmed_memory_matches_whole_cue_only(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            root=Path(folder)
            (root/'series_memory.json').write_text('{"Your heart":"O seu coração..."}', encoding='utf-8')
            series=Q.SeriesTerms(root/'ep.srt',[],root/'cache','en')
            self.assertEqual(series.memory_for('Your\nheart'),'O seu coração...')
            self.assertIsNone(series.memory_for('Listen to your heart.'))
            self.assertEqual(series.relevant('Listen to your heart.'),{})

    def test_name_lists_do_not_turn_into_verbs(self):
        self.assertEqual(Q.terms_only('Row! Row, Row!',{'Row':'Row'}),'Row! Row, Row!')
        self.assertEqual(Q.terms_only('Kaito! Yuna!',{'Kaito':'Kaito','Yuna':'Yuna'}),'Kaito! Yuna!')
        self.assertIsNone(Q.terms_only('Row the boat!',{'Row':'Row'}))
        self.assertIsNone(Q.terms_only('Save!',{}))

    def test_confirmed_memory_respects_html_and_ass_layout(self):
        self.assertEqual(Q.render_memory('<i>Hello</i>','Olá.'),'<i>Olá.</i>')
        result=Q.render_memory('Hello','Uma frase suficientemente longa para precisar de duas linhas na legenda.',ass=True)
        self.assertIn(r'\N',result);self.assertNotIn('\n',result)

    def test_memory_edit_updates_one_cue_without_retranslating_dialogue(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            root=Path(folder);source=root/'ep.srt'
            source.write_text('1\n00:00:01,000 --> 00:00:03,000\nHello there.\n\n2\n00:00:04,000 --> 00:00:06,000\nYour heart\n', encoding='utf-8')
            memory=root/'series_memory.json';memory.write_text('{"Your heart":"Seu coração."}', encoding='utf-8')
            with patch.object(O,'SOURCE_LANGUAGE','en'),patch.object(O,'_ollama_call',return_value='Olá.'):
                first=O.translate_paths([source],root/'out')[0]
            memory.write_text('{"Your heart":"O seu coração..."}', encoding='utf-8')
            with patch.object(O,'SOURCE_LANGUAGE','en'),patch.object(O,'_ollama_call',side_effect=AssertionError('dialogue cache reset')):
                second=O.translate_paths([source],root/'out')[0]
            self.assertIn('Seu coração.',first.read_text(encoding='utf-8'))
            self.assertIn('O seu coração...',second.read_text(encoding='utf-8'))

    def test_finalizer_applies_confirmed_decision_without_changing_timing(self):
        from tools.finalize_season_review import finalize
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            root=Path(folder);work=root/'work';out=root/'out';work.mkdir();out.mkdir()
            row={'episode':1,'position':0,'index':'7','time':'00:00:01,000 --> 00:00:04,000',
                 'source':'Kaito!','translation':'Errado!','source_path':str(root/'source.srt'),'target_path':str(root/'episode.PTBR.srt'),'flags':[]}
            (work/'inventory.json').write_text(json.dumps([row]), encoding='utf-8')
            (work/'glossary_confirmed.json').write_text('{"Kaito":"Kaito"}', encoding='utf-8')
            (work/'editorial_profile.json').write_text('{"overrides":{"1:1":"Kaito!"},"recurring_translations":{},"target_aliases":{}}', encoding='utf-8')
            (work/'editorial_audit.json').write_text(json.dumps([{**row,'method':'retained_for_review','remaining_flags':['terminology']}]), encoding='utf-8')
            path=out/'episode.PTBR.srt';path.write_text('7\n00:00:01,000 --> 00:00:04,000\nErrado!\n', encoding='utf-8')
            finalize(work,out)
            self.assertEqual(O.parse_srt(path.read_text(encoding='utf-8')),[('7',row['time'],'Kaito!')])
            self.assertEqual(json.loads((work/'pending_editorial.json').read_text(encoding='utf-8')),[])


if __name__=='__main__':unittest.main()
