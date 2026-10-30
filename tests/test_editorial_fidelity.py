"""Regression coverage for isolated English leaks, questions and ASS reference."""
import unittest
from types import SimpleNamespace
import ollama_script as O
import subtitle_quality as Q
from fansub_tools import render_ass, REFERENCE_PRESET, validate_preset, suggest

class EditorialFidelityTests(unittest.TestCase):
    def test_isolated_english_in_portuguese_and_legitimate_names(self):
        self.assertTrue(O._has_english_residual('It cries "cuckoo".','Ele faz "cuckoo".'))
        self.assertFalse(O._has_english_residual('It cries "cuckoo".','Ele faz "cuco".'))
        self.assertFalse(O._has_english_residual('Cuckoo arrived.','Cuckoo chegou.'))
        self.assertFalse(O._has_english_residual('A Peeping Tom, Majic.','Um tarado, Majic.'))
        self.assertFalse(O._has_english_residual('A Peeping Tom.','Um voyeur.'))

    def test_lost_question_is_not_silently_accepted(self):
        self.assertIn('question_lost',Q.quality_flags('Are you alright?','Você está bem.',2,{}))
        self.assertNotIn('question_lost',Q.quality_flags('Are you alright?','Você está bem?',2,{}))
        self.assertNotIn('question_lost',Q.quality_flags('Go!','Vá!',2,{}))
        self.assertIn('Keep it a question',O._retry_feedback('Why?',['question_lost'],{},'Por isso.',1))

    def test_reference_separates_music_titles_and_dialogue(self):
        doc=SimpleNamespace(ext='.srt',values=['Fala.','Canção.','Título.'],bounds=[(1,2),(2,3),(3,4)],annotations={1:{'kind':'music'},2:{'kind':'sign'}})
        raw=render_ass(doc,REFERENCE_PRESET)
        self.assertIn('PlayResX: 640\nPlayResY: 480',raw)
        styles={line.split(',')[0].split(': ')[1]:line.split(',') for line in raw.splitlines() if line.startswith('Style:')}
        self.assertEqual(styles['Dialogue'][2],'26')
        self.assertEqual(styles['Dialogue'][7:9],['0','0'])
        self.assertEqual(styles['Dialogue'][16:22],['2.25','0.7','2','24','24','20'])
        self.assertEqual(styles['Music'][2],'24')
        self.assertEqual(styles['Music'][8],'-1')
        self.assertEqual(styles['Music'][16:22],['2','0.7','2','26','26','23'])
        self.assertEqual(styles['Sign'][2],'24')

    def test_fractional_strokes_are_allowed_but_not_fractional_resolution(self):
        self.assertEqual(validate_preset({'outline':2.25,'shadow':.7})['outline'],2.25)
        for key,value in [('height',480.5),('shadow',float('nan')),('outline',True),('layout','invalid')]:
            with self.assertRaises(ValueError):validate_preset({key:value})

    def test_no_music_is_inferred_from_opening_time_alone(self):
        doc=SimpleNamespace(ext='.srt',values=['Fala às nove segundos.','♪ Canção ♪'],times=['',''],annotations={})
        rows=suggest(doc)
        self.assertEqual(rows[0]['suggestedKind'],'dialogue')
        self.assertEqual(rows[1]['suggestedKind'],'music')

if __name__=='__main__':unittest.main()
