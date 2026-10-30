import sys,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fansub_tools import reference_copy
from speech_context import read_context
from studio_ui.pipeline import Pipeline,validate_settings
from test_priority_one import FakeRuntime,ROOT

SRT='1\n00:00:01,250 --> 00:00:04,500\nUma fala de exemplo.\n'

class AutomaticStyleTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'tests');self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.source=self.root/'episode.srt';self.source.write_text(SRT,encoding='utf-8')
    def test_default_stays_unchanged_and_invalid_values_are_rejected(self):
        self.assertEqual(validate_settings({})['subtitle_style'],'original')
        self.assertEqual(validate_settings({'subtitle_style':'bad'})['subtitle_style'],'original')
    def test_copy_preserves_source_and_is_idempotent(self):
        before=self.source.read_bytes();output=Path(reference_copy(self.source))
        self.assertEqual(output.name,'episode.visual.ass');self.assertEqual(self.source.read_bytes(),before)
        text=output.read_text(encoding='utf-8-sig');self.assertIn('Trebuchet MS,26',text);self.assertIn('0:00:01.25,0:00:04.50',text)
        self.assertEqual(read_context(output)['visual_style'],'reference-v2')
        self.assertEqual(reference_copy(output),str(output));self.assertEqual(len(list(self.root.glob('*.visual.ass'))),1)
        self.assertEqual(reference_copy(self.source),str(output));self.assertEqual(len(list(self.root.glob('*.visual.ass'))),1)
    def test_existing_file_is_never_overwritten(self):
        existing=self.root/'episode.visual.ass';existing.write_bytes(b'KEEP')
        created=reference_copy(self.source)
        self.assertNotEqual(created,str(existing));self.assertEqual(existing.read_bytes(),b'KEEP')
        self.assertEqual(reference_copy(self.source),created)
    def test_content_bound_classification_is_preserved(self):
        from speech_context import write_context
        import json
        from pipeline_io import atomic_write_text
        write_context(self.source,self.source,{},source_kind='subtitle')
        side=Path(str(self.source)+'.source.json');data=json.loads(side.read_text(encoding='utf-8'))
        data['subtitle_annotations']={'0':{'kind':'music','simultaneous':False}}
        atomic_write_text(side,json.dumps(data))
        output=Path(reference_copy(self.source)).read_text(encoding='utf-8-sig')
        self.assertIn('0:00:01.25,0:00:04.50,Music',output)
    def test_ass_keeps_events_positions_drawings_and_scales_dialogue(self):
        source=self.root/'source.ass'
        original='[Script Info]\nPlayResX: 1280\nPlayResY: 720\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\nDialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,Fala\nDialogue: 0,0:00:01.00,0:00:03.00,Signs,,0,0,0,,{\\pos(200,100)}Placa\nDialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,{\\p1}m 0 0 l 10 10\n'
        source.write_text(original,encoding='utf-8');output=Path(reference_copy(source)).read_text(encoding='utf-8-sig')
        self.assertIn(r'\fs39.000\b0\bord3.375',output);self.assertIn(r'{\pos(200,100)}Placa',output)
        self.assertIn(r'{\p1}m 0 0 l 10 10',output);self.assertEqual(output.count('Dialogue: '),3)
        self.assertEqual(source.read_text(encoding='utf-8'),original)
    def test_cancel_does_not_write_output(self):
        cancel=threading.Event();cancel.set()
        with self.assertRaises(RuntimeError):reference_copy(self.source,cancel)
        self.assertFalse(list(self.root.glob('*.ass')))
    def test_translation_automatically_adds_styled_copy(self):
        runtime=FakeRuntime();pipeline=Pipeline(runtime,self.root)
        settings=validate_settings({'subtitle_style':'reference','ollama_out_dir':str(self.root/'translated')})
        outputs=pipeline._episode(dict(id='one',name=self.source.name,path=str(self.source)),settings,'translate')
        self.assertEqual(len(outputs),1);self.assertTrue(outputs[0].endswith('.visual.ass'));self.assertFalse(list((self.root/'translated').glob('*.srt')))
    def test_mux_receives_the_styled_subtitle(self):
        video=self.root/'episode.mkv';video.touch();runtime=FakeRuntime();captured=[]
        def mux(source,subtitle,outdir,**kwargs):
            captured.append(subtitle);target=Path(outdir)/'out.mkv';target.parent.mkdir(parents=True,exist_ok=True);target.touch();return str(target)
        runtime.mux_softsub=mux;pipeline=Pipeline(runtime,self.root)
        settings=validate_settings({'subtitle_style':'reference','embed_enabled':True})
        pipeline._episode(dict(id='one',name=video.name,path=str(video)),settings,'auto')
        self.assertTrue(captured[0].endswith('.visual.ass'))
    def test_folder_button_preserves_originals_and_does_not_duplicate_on_retry(self):
        from PySide6.QtCore import QCoreApplication
        from studio_ui.backend import Backend
        import time
        app=QCoreApplication.instance() or QCoreApplication([]);backend=Backend(self.root,FakeRuntime(),monitor_enabled=False)
        self.addCleanup(backend.timer.stop);self.addCleanup(backend.review.fansub.timer.stop)
        other=self.root/'second.srt';other.write_text(SRT,encoding='utf-8')
        for attempt in range(2):
            with patch('studio_ui.backend.QFileDialog.getExistingDirectory',return_value=str(self.root)):
                backend.styleSubtitleFolder()
            deadline=time.monotonic()+10
            while backend.busy and time.monotonic()<deadline:app.processEvents();time.sleep(.005)
            app.processEvents();self.assertFalse(backend.busy)
        self.assertEqual(len(list(self.root.glob('*.visual.ass'))),2)
        self.assertEqual(self.source.read_text(encoding='utf-8'),SRT);self.assertEqual(other.read_text(encoding='utf-8'),SRT)

if __name__=='__main__':unittest.main()
