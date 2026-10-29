"""Optional reference styling must preserve originals, timestamps and existing ASS."""
import sys,unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fansub_tools import PRESET_DEFAULTS,REFERENCE_PRESET,validate_preset,render_ass


class ReferenceStyleTests(unittest.TestCase):
    def document(self,text='Texto de exemplo.'):
        return SimpleNamespace(ext='.srt',values=[text],bounds=[(1.25,4.5)],annotations={})
    def test_old_presets_keep_regular_weight(self):
        self.assertFalse(validate_preset({'font':'Arial','size':48})['bold'])
        self.assertFalse(PRESET_DEFAULTS['bold'])
        self.assertIn(',0,0,0,0,100,100,',render_ass(self.document(),{}))
    def test_reference_style_is_explicit_and_keeps_timing_and_text(self):
        doc=self.document('Primeira linha.\nSegunda linha.');before=(list(doc.values),list(doc.bounds),dict(doc.annotations))
        raw=render_ass(doc,REFERENCE_PRESET)
        self.assertIn('Style: Dialogue,Trebuchet MS,66,',raw)
        style=next(line for line in raw.splitlines() if line.startswith('Style: Dialogue,')).split(',')
        self.assertEqual(style[7],'-1');self.assertEqual(style[16:19],['5','0','2'])
        self.assertIn('0:00:01.25,0:00:04.50,Dialogue',raw);self.assertIn(r'Primeira linha.\NSegunda linha.',raw)
        self.assertEqual((doc.values,doc.bounds,doc.annotations),before)
    def test_inline_bold_returns_to_the_selected_base_weight(self):
        doc=self.document('<b>Parte</b> restante.')
        self.assertIn(r'{\b1}Parte{\b1} restante.',render_ass(doc,REFERENCE_PRESET))
        self.assertIn(r'{\b1}Parte{\b0} restante.',render_ass(doc,{}))
    def test_existing_ass_is_preserved_even_with_reference_selected(self):
        original='[Script Info]\nTitle: Existing\n[Events]\nDialogue: drawing and positioning preserved\n'
        doc=SimpleNamespace(ext='.ass',render=lambda:original)
        self.assertEqual(render_ass(doc,REFERENCE_PRESET),original)
    def test_bold_does_not_accept_strings_or_numbers(self):
        for value in (0,1,'true',None):
            with self.assertRaises(ValueError):validate_preset({'bold':value})


if __name__=='__main__':unittest.main()
