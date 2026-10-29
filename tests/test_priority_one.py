"""Original preservation, review history, explicit sources and shared projects."""
import hashlib,json,sys,tempfile,time,unittest,zipfile,io
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import QCoreApplication
from review_workspace import ReviewWorkspace,SubtitleDocument,digest,transaction
from series_registry import SeriesRegistry,apply_project
from source_selection import validate_options,subtitle_sample
import subtitle_quality as Q
from studio_ui.backend import Backend
from studio_ui.pipeline import Pipeline,validate_settings

ROOT=Path(__file__).resolve().parents[1]
SRT='1\n00:00:01,000 --> 00:00:04,000\nPrimeira fala.\n\n2\n00:00:05,000 --> 00:00:08,000\nSegunda fala.\n'
SOURCE='1\n00:00:01,000 --> 00:00:04,000\nFirst line.\n\n2\n00:00:05,000 --> 00:00:08,000\nSecond line.\n'

class FakeRuntime:
    OLLAMA_SCRIPT=ROOT/'ollama_script.py';WHISPER_SCRIPT=ROOT/'whisper_script.py';EXTRACT_SCRIPT=ROOT/'extract_subs.py'
    def __init__(self):self.commands=[]
    def runtime_python(self):return sys.executable
    def _ensure_ollama_ready(self,**kw):return True
    def _release_translation_memory(self,**kw):pass
    def _stop_managed_ollama_server(self,**kw):pass
    def kill_all_active_procs(self):pass
    def run_capture(self,cmd,on_line,**kwargs):
        import ollama_script as O
        self.commands.append(cmd)
        if str(cmd[0]).lower().endswith('ffmpeg.exe'):
            import subprocess
            return subprocess.run(cmd,capture_output=True).returncode
        folder=Path(cmd[cmd.index('--outdir')+1]);folder.mkdir(parents=True,exist_ok=True)
        inputs=cmd[2:cmd.index('--outdir')]
        for path in inputs:
            source=Path(path);records=O.parse_srt(source.read_text(encoding='utf-8')) if source.suffix=='.srt' else [('1','00:00:00,000 --> 00:00:01,000','sample')]
            target=folder/(source.stem+'.result.srt');target.write_text(O.build_srt([(r[0],r[1],'Nova tradução '+str(i+1)) for i,r in enumerate(records)]),encoding='utf-8')
            on_line('[RESULT] '+json.dumps({'kind':'transcription' if 'whisper' in str(cmd[1]) else 'translation','input':str(source.resolve()),'output':str(target.resolve())}))
        return 0

class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'tests');self.addCleanup(self.temp.cleanup);self.base=Path(self.temp.name);self.app=self.base/'app';self.app.mkdir();self.inputs=self.base/'inputs';self.inputs.mkdir();self.source=self.inputs/'episode.srt';self.source.write_text(SRT,encoding='utf-8');self.workspace=ReviewWorkspace(self.app)
    def test_save_copy_history_restore_and_original_hash(self):
        original=self.source.read_bytes();doc=self.workspace.open(self.source);doc.values[0]='Correção.';doc.approved.add(0);target=self.workspace.save(doc)
        self.assertTrue(target.is_relative_to(self.app));self.assertEqual(self.source.read_bytes(),original)
        versions=self.workspace.versions(doc);self.assertEqual(len(versions),2)
        self.workspace.restore(doc,versions[0]['id']);self.assertEqual(doc.values[0],'Primeira fala.');self.assertFalse(doc.approved)
        self.assertEqual(self.source.read_bytes(),original)
    def test_autosave_after_first_save_recovers_later_edits(self):
        doc=self.workspace.open(self.source);doc.values[0]='Salvo.';self.workspace.save(doc);doc.values[1]='Ainda não salvo.';self.workspace.autosave(doc)
        recovered=self.workspace.open(self.source);self.assertEqual(recovered.values[0],'Salvo.');self.assertEqual(recovered.values[1],'Ainda não salvo.');self.assertTrue(recovered.dirty)
    def test_external_edits_are_never_overwritten(self):
        doc=self.workspace.open(self.source);self.source.write_text(SRT.replace('Primeira','Externa'),encoding='utf-8');doc.values[0]='Meu texto.'
        with self.assertRaises(ValueError):self.workspace.save(doc)
        self.assertIn('Externa',self.source.read_text(encoding='utf-8'))
    def test_independent_copy_recovers_work_after_external_edit(self):
        doc=self.workspace.open(self.source);doc.values[0]='Meu rascunho.';self.source.write_text(SRT.replace('Primeira','Externa'),encoding='utf-8')
        target=self.workspace.fork(doc);self.assertIn('Meu rascunho.',target.read_text(encoding='utf-8'));self.assertIn('Externa',self.source.read_text(encoding='utf-8'))
        recovered=self.workspace.open(target);self.assertTrue(recovered.independent);recovered.values[1]='Mais uma edição.';self.workspace.save(recovered)

    def test_two_review_sessions_cannot_lose_each_others_save(self):
        first=self.workspace.open(self.source);second=self.workspace.open(self.source);first.values[0]='Uma edição.';target=self.workspace.save(first);saved=target.read_bytes();second.values[0]='Outra edição.'
        with self.assertRaises(ValueError):self.workspace.save(second)
        self.assertEqual(target.read_bytes(),saved)
    def test_source_matching_uses_times_not_row_numbers(self):
        source=self.inputs/'original.srt';source.write_text(SOURCE.replace('00:00:05,000','00:00:06,000'),encoding='utf-8');doc=self.workspace.open(self.source);doc.attach_source(source)
        self.assertTrue(doc.verified[0]);self.assertFalse(doc.verified[1]);self.assertIn('source_unmatched',doc.flags()[1])
    def test_technical_checks_find_invalid_empty_and_overlap(self):
        self.source.write_text('1\n00:00:02,000 --> 00:00:01,000\n\n2\n00:00:00,000 --> 00:00:04,000\nTexto\n\n3\n00:00:03,000 --> 00:00:05,000\nTexto\n',encoding='utf-8');doc=self.workspace.open(self.source);flags=doc.flags()
        self.assertIn('invalid_time',flags[0]);self.assertIn('empty',flags[0]);self.assertIn('overlap',flags[1]);self.assertIn('overlap',flags[2]);self.assertIn('out_of_order',flags[1])
    def test_ass_nonfinal_text_field_and_vtt_metadata_survive(self):
        ass=self.inputs/'custom.ass';raw='[Script Info]\nTitle: Test\n[Events]\nFormat: Layer, Text, Start, End, Style\nDialogue: 0,Hello, there,0:00:01.00,0:00:04.00,Default\n';ass.write_text(raw,encoding='utf-8');doc=self.workspace.open(ass)
        self.assertEqual(doc.bounds,[(1.,4.)]);doc.values[0]='Olá, mundo';target=self.workspace.save(doc);self.assertIn('Dialogue: 0,Olá, mundo,0:00:01.00,0:00:04.00,Default',target.read_text(encoding='utf-8'))
        vtt=self.inputs/'web.vtt';vtt.write_text('WEBVTT\n\nNOTE keep\nDo not touch\n\nid-1\n00:01.000 --> 00:04.000 align:start\nHello\n',encoding='utf-8');doc=self.workspace.open(vtt);doc.values[0]='Olá';target=self.workspace.save(doc)
        self.assertIn('NOTE keep\nDo not touch',target.read_text(encoding='utf-8'));self.assertIn('align:start',target.read_text(encoding='utf-8'))
    def test_backup_roundtrip_and_pre_restore_copy(self):
        (self.app/'config.json').write_text('{"custom":42}',encoding='utf-8');doc=self.workspace.open(self.source);doc.values[0]='Aprovado.';self.workspace.save(doc);backup=self.workspace.backup();(self.app/'config.json').write_text('{"custom":99}',encoding='utf-8')
        safety=self.workspace.restore_backup(backup);self.assertTrue(safety.is_file());self.assertEqual(json.loads((self.app/'config.json').read_text())['custom'],42);self.assertEqual(self.source.read_text(encoding='utf-8'),SRT)
    def test_hostile_backup_paths_and_executable_entries_are_rejected(self):
        for entry in ('../evil.json','C:/evil.json','series_projects/../../evil.json','runtime/evil.py','series_projects/evil.exe','series_projects/link.json'):
            backup=self.base/'bad.zip'
            with zipfile.ZipFile(backup,'w') as z:
                info=zipfile.ZipInfo(entry)
                if entry.endswith('link.json'):info.external_attr=(0o120777<<16)
                z.writestr(info,'{}')
            with self.assertRaises(ValueError):self.workspace.restore_backup(backup)
        self.assertFalse((self.app/'config.json').exists())
    def test_transaction_rolls_back_partial_save(self):
        from review_workspace import atomic_bytes
        a=self.app/'a.json';b=self.app/'b.json';a.write_bytes(b'old a');b.write_bytes(b'old b');count=[0]
        def fail_second(path,data):
            count[0]+=1
            if count[0]==2:raise OSError('simulated full disk')
            atomic_bytes(path,data)
        with patch('review_workspace.atomic_bytes',side_effect=fail_second):
            with self.assertRaises(OSError):transaction(self.app,{a:b'new a',b:b'new b'})
        self.assertEqual(a.read_bytes(),b'old a');self.assertEqual(b.read_bytes(),b'old b')
    def test_subtitle_samples_preserve_format_and_original(self):
        source=self.inputs/'long.srt';source.write_text(SRT.replace('00:00:05,000','00:02:05,000').replace('00:00:08,000','00:02:08,000'),encoding='utf-8');before=source.read_bytes();target=subtitle_sample(source,self.app/'sample',0,60)
        import ollama_script as O
        self.assertEqual(len(O.parse_srt(target.read_text(encoding='utf-8'))),1);self.assertEqual(source.read_bytes(),before)
    def test_ass_and_vtt_sample_do_not_include_other_dialogues(self):
        for ext,raw in [('.ass','[Events]\nFormat: Layer, Start, End, Text\nDialogue: 0,0:00:01.00,0:00:02.00,first\nDialogue: 0,0:02:01.00,0:02:02.00,second\n'),('.vtt','WEBVTT\n\nNOTE preserve\nhello\n\n00:01.000 --> 00:02.000\nfirst\n\n02:01.000 --> 02:02.000\nsecond\n')]:
            source=self.inputs/('sample'+ext);source.write_text(raw,encoding='utf-8');target=subtitle_sample(source,self.app/'samples',0,60);text=target.read_text(encoding='utf-8');self.assertIn('first',text);self.assertNotIn('second',text)
            if ext=='.vtt':self.assertIn('NOTE preserve',text)
    def test_source_reference_is_preserved_in_backup_and_history(self):
        source=self.inputs/'english.srt';source.write_text(SOURCE,encoding='utf-8');doc=self.workspace.open(self.source);doc.attach_source(source);doc.values[0]='Corrigida.';target=self.workspace.save(doc);backup=self.workspace.backup()
        source.unlink();recovered=self.workspace.open(target);self.assertTrue(all(recovered.verified));self.assertEqual(recovered.original_texts[0],'First line.')
        self.workspace.restore_backup(backup);self.assertTrue(all(self.workspace.open(target).verified))
    def test_raw_transcription_gets_immutable_source_reference(self):
        Path(str(self.source)+'.transcription.json').write_text(json.dumps({'audio_stream':2,'review_findings':[{'block':1,'start':1,'end':4,'flags':['low_word_confidence']}]}),encoding='utf-8')
        doc=self.workspace.open(self.source);self.assertTrue(all(doc.verified));doc.values[0]='Texto editado.'
        self.assertEqual(doc.original_texts[0],'Primeira fala.');self.assertIn('low_word_confidence',doc.flags()[0]);self.assertEqual(doc.audio_stream,2)

    def test_invalid_source_does_not_destroy_previous_reference(self):
        source=self.inputs/'english.srt';source.write_text(SOURCE,encoding='utf-8');doc=self.workspace.open(self.source);doc.attach_source(source);data=doc.source_bytes
        bad=self.inputs/'wrong.bin';bad.write_bytes(b'wrong')
        with self.assertRaises(ValueError):doc.attach_source(bad)
        self.assertEqual(doc.source_bytes,data);self.assertEqual(doc.source_path,str(source))
    def test_blocked_translation_becomes_editable_partial_draft(self):
        source=self.inputs/'english.srt';source.write_text(SOURCE,encoding='utf-8');report=self.inputs/'failed.srt.review_required.json'
        report.write_text(json.dumps({'source':str(source),'source_sha256':digest(source.read_bytes()),'block':2,'input':'Second line.','rejected_candidate':'Candidato para revisar.','partial_translations':[{'index':0,'time':'00:00:01,000 --> 00:00:04,000','source':'First line.','translation':'Primeira traduzida.'}]}),encoding='utf-8')
        before=source.read_bytes();doc=self.workspace.open(report);self.assertEqual(doc.values,['Primeira traduzida.','Candidato para revisar.']);self.assertIn('model_rejected',doc.flags()[1]);self.assertTrue(all(doc.verified))
        target=self.workspace.save(doc);recovered=self.workspace.open(target);self.assertEqual(recovered.values,doc.values);self.assertIn('model_rejected',recovered.flags()[1]);self.assertEqual(source.read_bytes(),before)
    def test_blocked_translation_rejects_changed_source_hash(self):
        report=self.inputs/'failed.srt.review_required.json';report.write_text(json.dumps({'source':str(self.source),'source_sha256':'invalid'}),encoding='utf-8')
        with self.assertRaises(ValueError):self.workspace.open(report)

    def test_long_filename_uses_short_owned_copy(self):
        source=self.inputs/('a'*200+'.srt');source.write_text(SRT,encoding='utf-8');doc=self.workspace.open(source);self.assertLess(len(doc.target.name),220);self.workspace.save(doc)

class ProjectTests(unittest.TestCase):
    setUp=WorkspaceTests.setUp
    def test_seasons_share_confirmed_terms_without_cross_anime_leak(self):
        registry=SeriesRegistry(self.app);one=registry.create('Anime One');two=registry.create('Anime Two');registry.set_term(one,'Moon Tower','Torre Lunar',True);registry.set_term(one,'Sky Gate','Portal Celeste',False)
        s1=self.inputs/'season1';s2=self.inputs/'season2';s1.mkdir();s2.mkdir();registry.bind_folder(one,s1);registry.bind_folder(one,s2)
        self.assertEqual(registry.resolve(s1/'episode.mkv'),one);self.assertEqual(registry.resolve(s2/'episode.mkv'),one);self.assertEqual(registry.confirmed(two),{})
        self.assertNotIn('Sky Gate',registry.confirmed(one))
        source=s2/'episode.srt';source.write_text(SOURCE,encoding='utf-8')
        with patch.object(Q,'__file__',str(self.app/'subtitle_quality.py')):
            terms=Q.SeriesTerms(source,[],self.app/'cache','en');self.assertEqual(terms.explicit.get('Moon Tower'),'Torre Lunar');self.assertNotIn('Sky Gate',terms.explicit)
    def test_project_context_follows_owned_subtitle_copy(self):
        registry=SeriesRegistry(self.app);project=registry.create('Project');registry.set_term(project,'Nora','Nora',True);owned=self.app/'copied.srt';owned.write_text(SRT,encoding='utf-8');apply_project(owned,self.source,self.app,project)
        with patch.object(Q,'__file__',str(self.app/'subtitle_quality.py')):
            terms=Q.SeriesTerms(owned,[],self.app/'cache','en');self.assertEqual(terms.explicit['Nora'],'Nora')
    def test_untrusted_confirmation_type_never_becomes_approved(self):
        registry=SeriesRegistry(self.app);project=registry.create('Project');path=registry.base/project/'terms.json';path.parent.mkdir();path.write_text('[{"source":"A","target":"B","confirmed":"false"}]',encoding='utf-8')
        with self.assertRaises(ValueError):registry.confirmed(project)

class ControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QCoreApplication.instance() or QCoreApplication([])
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'tests');self.root=Path(self.temp.name);self.runtime=FakeRuntime();self.backend=Backend(self.root,self.runtime,monitor_enabled=False)
    def tearDown(self):self.backend.shutdown();self.backend.review.join();self.app.processEvents();self.temp.cleanup()
    def wait(self):
        deadline=time.monotonic()+5
        while self.backend.review.busy and time.monotonic()<deadline:self.app.processEvents();time.sleep(.005)
        self.app.processEvents();self.assertFalse(self.backend.review.busy)
    def doc(self):
        source=self.root/'original.srt';source.write_text(SOURCE,encoding='utf-8');target=self.root/'translation.srt';target.write_text(SRT,encoding='utf-8');Path(str(target)+'.quality.json').write_text(json.dumps({'source':str(source),'findings':[]}),encoding='utf-8')
        self.backend.review.openDocument(str(target));self.wait();self.assertTrue(self.backend.review.loaded);return source,target
    def test_selected_retranslation_needs_approval_and_changes_only_selection(self):
        source,target=self.doc();before=target.read_bytes();review=self.backend.review;review.toggle(1,True);review.retranslateSelected();self.wait()
        self.assertEqual(review.document.values,['Primeira fala.','Segunda fala.']);self.assertNotIn(0,review.document.proposals);self.assertIn(1,review.document.proposals)
        review.select(1);review.applyProposal();self.assertEqual(review.document.values[0],'Primeira fala.');self.assertTrue(review.dirty);self.assertEqual(target.read_bytes(),before)
    def test_unmatched_source_blocks_retranslation(self):
        self.doc();review=self.backend.review;review.document.verified[1]=False;review.toggle(1,True);review.retranslateSelected();self.assertFalse(review.busy);self.assertEqual(self.runtime.commands,[])
    def test_source_audio_selection_uses_corresponding_language(self):
        path=self.root/'episode.mkv';path.touch();self.backend.addFiles([str(path)]);item=self.backend._items[0]
        streams=[{'index':1,'kind':'audio','codec':'aac','language':'eng','title':''},{'index':2,'kind':'audio','codec':'aac','language':'jpn','title':''}]
        with patch('studio_ui.review_controller.probe',return_value=streams):self.backend.review.inspectInput(item['id']);self.wait()
        self.assertTrue(self.backend.review.saveInputOptions(item['id'],{'source_mode':'whisper','audio_stream':'1'}));self.assertEqual(item['options']['audio_language'],'en')
    def test_save_keeps_input_original_and_emits_owned_result(self):
        source,target=self.doc();before=target.read_bytes();self.backend.review.editCurrent('Corrigida.');self.backend.review.approve();self.assertTrue(self.backend.review.save());self.assertEqual(target.read_bytes(),before)
        self.assertTrue(Path(self.backend.review.outputPath).is_file())
    def test_external_source_pipeline_skips_whisper_and_preserves_files(self):
        source=self.root/'english.srt';source.write_text(SOURCE,encoding='utf-8');video=self.root/'video.mkv';video.write_bytes(b'unchanged');item={'id':'abc','path':str(video),'options':{'source_mode':'external','source_subtitle':str(source)}}
        pipeline=Pipeline(self.runtime,self.root);results=pipeline._episode(item,validate_settings({}),'translate')
        self.assertTrue(results);self.assertEqual(len(self.runtime.commands),1);self.assertIn('ollama_script.py',str(self.runtime.commands[0][1]));self.assertEqual(video.read_bytes(),b'unchanged');self.assertEqual(source.read_text(encoding='utf-8'),SOURCE)
    def test_short_text_test_processes_only_interval(self):
        path=self.root/'long.srt';path.write_text(SOURCE.replace('00:00:05,000','00:02:05,000').replace('00:00:08,000','00:02:08,000'),encoding='utf-8');item={'id':'sample1','path':str(path),'options':{'sample_seconds':60}}
        pipeline=Pipeline(self.runtime,self.root);pipeline._episode(item,validate_settings({}),'auto')
        cmd=self.runtime.commands[0];self.assertIn('outputs',str(cmd));self.assertIn('samples',str(cmd));self.assertNotIn('Second line',Path(cmd[2]).read_text(encoding='utf-8'))
    def test_requeue_keeps_source_project_and_track_options(self):
        source=self.root/'episode.srt';source.write_text(SRT,encoding='utf-8');self.backend.addFiles([str(source)]);item=self.backend._items[0];item.update(state='Concluído',options={'source_mode':'external','source_subtitle':str(source),'audio_stream':'2'})
        self.backend.requeueItem(item['id']);self.assertEqual(len(self.backend._items),2);self.assertEqual(self.backend._items[1]['options'],item['options']);self.assertIsNot(self.backend._items[1]['options'],item['options'])

    def test_invalid_source_options_are_rejected(self):
        for value in ({'source_mode':'bad'},{'subtitle_stream':'all'},{'sample_start':-1},{'sample_seconds':999},{'series_project':'../bad'}):
            with self.assertRaises(ValueError):validate_options(value)
