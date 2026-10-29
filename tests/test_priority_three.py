"""Fansub integrity, export, organization, history and empirical estimates."""
import json,time,tempfile,unittest
from pathlib import Path
from PySide6.QtCore import QCoreApplication
from fansub_tools import annotations,suggest,render_ass,organize,episode_number,estimate,performance_key,validate_preset,PRESET_DEFAULTS
from review_workspace import ReviewWorkspace,digest
from studio_ui.backend import Backend
from studio_ui.queue_model import EpisodeListModel
from test_priority_one import ROOT,SRT,FakeRuntime


class FansubTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'tests');self.addCleanup(self.temp.cleanup);self.base=Path(self.temp.name);self.app=self.base/'app';self.app.mkdir();self.path=self.base/'Episode 01.srt';self.path.write_text(SRT,encoding='utf-8');self.workspace=ReviewWorkspace(self.app)
    def test_suggestions_are_non_destructive(self):
        doc=self.workspace.open(self.path);doc.values[0]='♪ Canção ♪';before=doc.render();rows=suggest(doc);self.assertEqual(rows[0]['suggestedKind'],'music');self.assertEqual(rows[0]['kind'],'dialogue');self.assertEqual(doc.annotations,{});self.assertEqual(before,doc.render())
    def test_ass_suggestions_keep_nonstandard_columns_and_drawings(self):
        path=self.base/'a.ass';raw='[Events]\nFormat: Layer, Text, Start, End, Style\nDialogue: 0,{\\pos(100,100)}Placa,0:00:01.00,0:00:04.00,Signs\nDialogue: 0,Canção,0:00:05.00,0:00:08.00,Karaoke\n';path.write_text(raw,encoding='utf-8');doc=self.workspace.open(path);rows=suggest(doc);self.assertEqual([r['suggestedKind'] for r in rows],['sign','music']);self.assertEqual(render_ass(doc,{}).replace('\r\n','\n'),raw)
    def test_only_confirmed_pairs_suppress_overlap_and_preserve_timing(self):
        self.path.write_text(SRT.replace('00:00:05,000','00:00:03,000'),encoding='utf-8');doc=self.workspace.open(self.path);before=list(doc.bounds);doc.annotations[0]={'kind':'dialogue','simultaneous':True};self.assertIn('overlap',doc.flags()[0]);doc.annotations[1]={'kind':'dialogue','simultaneous':True};self.assertNotIn('overlap',doc.flags()[0]);self.assertEqual(doc.bounds,before)
    def test_annotations_autosave_history_backup_and_restore(self):
        doc=self.workspace.open(self.path);doc.annotations[0]={'kind':'music','simultaneous':False};self.assertTrue(doc.dirty);self.workspace.autosave(doc);recovered=self.workspace.open(self.path);self.assertEqual(recovered.annotations,doc.annotations);target=self.workspace.save(recovered);self.assertFalse(recovered.dirty)
        opened=self.workspace.open(target);self.assertEqual(opened.annotations,doc.annotations);backup=self.workspace.backup();self.workspace.restore_backup(backup);self.assertEqual(self.workspace.open(target).annotations,doc.annotations)
        version=self.workspace.versions(opened)[0];self.workspace.restore(opened,version['id']);self.assertEqual(opened.annotations,{});self.assertEqual(self.path.read_text(encoding='utf-8'),SRT)
    def test_invalid_annotation_rejected(self):
        for value in ({'-1':{'kind':'music','simultaneous':True}},{'0':{'kind':'unknown','simultaneous':True}},{'0':{'kind':'music','simultaneous':'false'}}):
            with self.assertRaises(ValueError):annotations(value,2)
    def test_external_changes_drop_stale_classification(self):
        doc=self.workspace.open(self.path);doc.annotations[0]={'kind':'dialogue','simultaneous':True};target=self.workspace.save(doc);target.write_text(target.read_text(encoding='utf-8').replace('Primeira','Externa'),encoding='utf-8');opened=self.workspace.open(target);self.assertEqual(opened.annotations,{})
    def test_ass_conversion_styles_formatting_separate_events(self):
        doc=self.workspace.open(self.path);doc.values[0]='<i>Uma fala</i>\nOutra linha.';doc.annotations[0]={'kind':'music','simultaneous':False};doc.annotations[1]={'kind':'sign','simultaneous':True};raw=render_ass(doc,{'size':52,'color':'#112233'});self.assertIn(r'{\i1}Uma fala{\i0}\NOutra linha.',raw);self.assertIn('&H00332211&',raw);self.assertIn('0:00:01.00,0:00:04.00,Music',raw);self.assertIn('0:00:05.00,0:00:08.00,Sign',raw);self.assertEqual(raw.count('Dialogue: '),2)
    def test_export_rejects_literal_commands_and_unsupported_markup(self):
        doc=self.workspace.open(self.path)
        for text in (r'Literal \N',r'{\pos(0,0)}Texto','<ruby>Nome</ruby>','<i>Sem fim','<i><i>Duplo</i></i>'):
            doc.values[0]=text
            with self.assertRaises(ValueError):render_ass(doc,{})
    def test_export_rejects_centisecond_collapse(self):
        self.path.write_text('1\n00:00:01,001 --> 00:00:01,002\nFala.\n',encoding='utf-8')
        with self.assertRaises(ValueError):render_ass(self.workspace.open(self.path),{})
    def test_preset_validation(self):
        self.assertEqual(validate_preset({'alignment':8.0})['alignment'],8)
        for value in ({'font':'Arial\nInjected'},{'size':0},{'color':'red'},{'margin':float('nan')}):
            with self.assertRaises(ValueError):validate_preset(value)
    def test_episode_numbering_and_specials(self):
        cases={'Anime_S02E03.mkv':(2,3,'episode'),'[Fansub] Anime - 12 [1080p][HEVC].mkv':(None,12,'episode'),'Orphen Revenge 01 [480p][BD][10bit_x265_HEVC][AAC].mkv':(None,1,'episode'),'Anime Episode 04.srt':(None,4,'episode'),'Anime NCOP 01.mkv':(None,None,'special'),'Anime - 01-02.mkv':(None,None,'range'),'Anime 1080p.mkv':(None,None,'unknown')}
        for name,want in cases.items():self.assertEqual(episode_number(name),want,name)
    def test_organizer_missing_duplicate_candidates_and_seasons(self):
        result=organize(['Anime S01E03.mkv','Anime S01E01.mkv','Other S01E01.mkv','Anime S02E02.mkv','Anime S01E01.srt']);self.assertEqual(result['missing'],[{'season':1,'episode':2},{'season':2,'episode':1}]);self.assertEqual(sum(r['duplicate'] for r in result['rows']),2)
        result=organize(['Anime 01.mkv','Anime 02.mkv'],4);self.assertEqual([r['episode'] for r in result['missing']],[3,4])
        with self.assertRaises(ValueError):organize([],501)
    def test_queue_model_reorder_has_no_duplicates(self):
        model=EpisodeListModel();model.sync([{'id':'a'},{'id':'b'},{'id':'c'}]);model.sync([{'id':'c'},{'id':'a'},{'id':'b'}]);self.assertEqual([r['id'] for r in model.rows],['c','a','b']);self.assertEqual(model.rowCount(),3)
    def test_estimate_requires_compatible_history_and_ignores_failed(self):
        settings={'whisper_model':'large-v3','whisper_device':'cuda','whisper_demucs_mode':'enabled','ollama_model':'translategemma:12b'};item=dict(path='01.mkv',operation='auto',state='Aguardando',options={});key=performance_key('auto',{},settings)
        report=dict(input='old.mkv',state='Concluído',performance_key=key,effective_seconds=120,output_bytes=1000)
        self.assertEqual(estimate([item],[report],settings)['unknown'],1);result=estimate([item],[report,dict(report,effective_seconds=180)],settings);self.assertEqual(result['seconds'],150);self.assertEqual(result['outputBytes'],1000)
        self.assertIsNone(estimate([item],[report,dict(report,state='Erro')],settings)['seconds']);self.assertIsNone(estimate([item],[report,report],dict(settings,whisper_device='cpu'))['seconds'])


class FansubControllerTests(unittest.TestCase):
    setUp=FansubTests.setUp
    def controller(self):
        self.qt=QCoreApplication.instance() or QCoreApplication([]);backend=Backend(self.app,FakeRuntime(),monitor_enabled=False);self.addCleanup(backend.timer.stop);self.addCleanup(backend.review.fansub.timer.stop);return backend
    def wait(self,review):
        deadline=time.monotonic()+10
        while review.busy and time.monotonic()<deadline:self.qt.processEvents();time.sleep(.005)
        self.qt.processEvents();self.assertFalse(review.busy)
    def test_profiles_are_isolated_and_backed_up(self):
        backend=self.controller();review=backend.review;fansub=review.fansub;fansub.setPreset({'size':52});fansub.saveProfile('Global');project=review.registry.create('A');review.refreshProjects();review.setProject(project);self.assertEqual(fansub.profiles,[]);fansub.setPreset({'size':60});fansub.saveProfile('Anime');backup=review.workspace.backup();fansub.removeProfile('Anime');self.assertEqual(fansub.profiles,[]);review.workspace.restore_backup(backup);self.assertEqual(fansub.profiles[0]['settings']['size'],60);review.setProject('');fansub.loadProfile('Global');self.assertEqual(fansub.preset['size'],52)
    def test_export_creates_unique_copies_with_audit_and_preserves_original(self):
        backend=self.controller();review=backend.review;fansub=review.fansub;review.openDocument(str(self.path));self.wait(review);fansub.classify('music',False);fansub.exportAss();self.wait(review);fansub.exportAss();self.wait(review);outputs=list((self.app/'outputs/studio/exports').glob('*.ass'));self.assertEqual(len(outputs),2);self.assertTrue(all(Path(str(p)+'.export.json').is_file() for p in outputs));self.assertEqual(self.path.read_text(encoding='utf-8'),SRT)
    def test_classification_selected_and_navigation(self):
        backend=self.controller();review=backend.review;review.openDocument(str(self.path));self.wait(review);review.toggle(1,True);review.fansub.classify('sign',True);self.assertEqual(review.document.annotations,{1:{'kind':'sign','simultaneous':True}});review.navigate(1);self.assertEqual(review.currentIndex,1);review.navigate(100);self.assertEqual(review.currentIndex,1);review.navigate(-1);review.approveNext();self.assertEqual(review.currentIndex,1);self.assertIn(0,review.document.approved)
    def test_line_wrapping_does_not_rewrite_confirmed_songs_or_signs(self):
        backend=self.controller();review=backend.review;review.openDocument(str(self.path));self.wait(review);review.editCurrent('Esta é uma frase bem longa que precisa de quebra para caber na legenda exibida.');review.fansub.classify('music',False);review.season.previewWrap();self.assertEqual(review.season.preview,[])
    def test_queue_sort_keeps_finished_and_item_settings(self):
        backend=self.controller();backend._items=[dict(id='03',path='Anime 03.mkv',state='Aguardando',options={'source_mode':'whisper'}),dict(id='done',path='done.mkv',state='Concluído'),dict(id='01',path='Anime 01.mkv',state='Aguardando')];backend.changed.emit();backend.review.fansub.sortQueue();self.assertEqual([i['id'] for i in backend._items],['01','done','03']);self.assertEqual(backend._items[2]['options'],{'source_mode':'whisper'});self.assertEqual(backend.queueModel.rowCount(),3)
