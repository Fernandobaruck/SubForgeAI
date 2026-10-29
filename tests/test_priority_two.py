"""Season consistency tests: formatting, style, timing and stale-preview protection."""
import json,tempfile,unittest,time
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import QCoreApplication
from season_tools import *
from review_workspace import ReviewWorkspace,_parse_only
from series_registry import SeriesRegistry,apply_project
from studio_ui.backend import Backend
from studio_ui.pipeline import Pipeline,validate_settings
from test_priority_one import FakeRuntime,SRT,SOURCE,ROOT


class SeasonTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'tests');self.addCleanup(self.temp.cleanup);self.base=Path(self.temp.name);self.app=self.base/'app';self.app.mkdir();self.inputs=self.base/'inputs';self.inputs.mkdir();self.path=self.inputs/'01.PTBR.srt';self.path.write_text(SRT,encoding='utf-8');self.workspace=ReviewWorkspace(self.app)
    def test_reflow_keeps_every_word_and_limits_two_lines(self):
        text='Uma frase longa que precisa de uma quebra para tornar a leitura mais agradável.'
        output=reflow(text);self.assertEqual(output.split(),text.split());self.assertEqual(len(output.splitlines()),2);self.assertLessEqual(max(map(len,output.splitlines())),42)
        self.assertEqual(reflow('x'*100),'x'*100)
        doc=self.workspace.open(self.path);doc.values[0]='a\nb\nc';self.assertIn('too_many_lines',doc.flags()[0]);doc.reported[0]=['too_many_lines'];doc.values[0]='a\nb';self.assertNotIn('too_many_lines',doc.flags()[0])
    def test_reflow_preserves_styling_speakers_music_drawing(self):
        for text in ('{\\i1}'+('texto '*20),'<i>'+('texto '*20)+'</i>','- primeira fala\n- segunda fala','♪ '+('texto '*20),r'{\p1}m 0 0 l 20 20',r'Primeiro\NSegundo'):
            self.assertEqual(reflow(text),text)
    def test_ass_plain_reflow_uses_ass_break(self):
        self.assertIn(r'\N',reflow('Uma frase longa que precisa de uma quebra para tornar a leitura mais agradável.',ass=True))
    def test_replace_boundaries_literal_and_protects_markup(self):
        self.assertEqual(replace_visible('<font face="Lua">Lua</font> e Luar','Lua','Sol'),'<font face="Lua">Sol</font> e Luar')
        self.assertEqual(replace_visible(r'{\fnLua}Lua\NLua','Lua','$1'),r'{\fnLua}$1\N$1')
        self.assertEqual(replace_visible('lua Lua Luar','Lua','Sol',False),'Sol Sol Luar')
        with self.assertRaises(ValueError):replace_visible('a','a','{x}')
    def test_style_validation_and_separation(self):
        registry=SeriesRegistry(self.app);a=registry.create('Anime A');b=registry.create('Anime B')
        registry.set_style(a,{'register':'formal','line_width':35});self.assertEqual(registry.style(a)['line_width'],35);self.assertEqual(registry.style(b),STYLE_DEFAULTS)
        with self.assertRaises(ValueError):registry.set_style(a,{'max_cps':100})
        with self.assertRaises(ValueError):registry.set_style(a,{'notes':'invent'})
        self.assertIn('formal',style_prompt(registry.style(a)))
        self.assertEqual(validate_style({'line_width':38.0})['line_width'],38)
        with self.assertRaises(ValueError):validate_style({'line_width':True})
    def test_style_changes_translation_fingerprint_and_prompt(self):
        import subtitle_quality as Q,ollama_script as O
        registry=SeriesRegistry(self.app);project=registry.create('Anime');registry.set_style(project,{'register':'formal'});copy=self.app/'source.srt';copy.write_text(SOURCE,encoding='utf-8');apply_project(copy,self.path,self.app,project)
        with patch.object(Q,'__file__',str(self.app/'subtitle_quality.py')):
            first=Q.SeriesTerms(copy,['First line.'],self.app/'cache','en');registry.set_style(project,{'register':'casual'});second=Q.SeriesTerms(copy,['First line.'],self.app/'cache','en')
        self.assertNotEqual(first.fingerprint(),second.fingerprint())
        captured=[]
        with patch.object(O,'ACTIVE_PROJECT_STYLE',first.style),patch.object(O,'ACTIVE_SERIES_HINTS',{}),patch.object(O,'ACTIVE_SOURCE_LANGUAGE','en'),patch.object(O,'_ollama_call',side_effect=lambda m,msg:(captured.append(msg[0]['content']) or 'Uma fala.')):
            O._context_call('translategemma:12b','This is a simple line.','','',{})
        self.assertIn('Prefer formal wording',captured[0]);self.assertIn('Never add translator notes',captured[0])
    def test_sync_roundtrip_history_source_and_autosave(self):
        source=self.inputs/'source.srt';source.write_text(SOURCE,encoding='utf-8');doc=self.workspace.open(self.path);doc.attach_source(source)
        doc.set_raw(synced_raw(doc,1.5,1.01));self.assertEqual(doc.bounds[0],(2.51,5.54));self.assertTrue(doc.dirty);self.workspace.autosave(doc)
        recovered=self.workspace.open(self.path);self.assertEqual(recovered.bounds,doc.bounds);self.assertTrue(all(recovered.verified))
        target=self.workspace.save(recovered);opened=self.workspace.open(target);self.assertEqual(opened.bounds,doc.bounds);self.assertTrue(all(opened.verified))
        self.workspace.restore(opened,self.workspace.versions(opened)[0]['id']);self.assertEqual(opened.bounds,[(1.,4.),(5.,8.)]);self.assertEqual(self.path.read_text(encoding='utf-8'),SRT)
    def test_sync_negative_invalid_nan_rejected(self):
        doc=self.workspace.open(self.path)
        for offset,scale in ((-5,1),(0,float('nan')),(float('inf'),1),(0,0),(0,3)):
            with self.assertRaises(ValueError):synced_raw(doc,offset,scale)
        self.assertEqual(synced_raw(doc,0,1),doc.render())
        short=self.inputs/'short.srt';short.write_text('1\n00:00:00,001 --> 00:00:00,002\nFala.\n',encoding='utf-8')
        with self.assertRaises(ValueError):synced_raw(self.workspace.open(short),.0002,.5)
    def test_sync_vtt_notes_and_settings_preserved(self):
        path=self.inputs/'a.vtt';path.write_text('WEBVTT\n\nNOTE 00:00:01.000 --> 00:00:03.000\nnot a cue\n\nid\n00:01.000 --> 00:04.000 align:start\nUma fala.\n',encoding='utf-8');doc=self.workspace.open(path)
        raw=synced_raw(doc,2,1);self.assertIn('NOTE 00:00:01.000 --> 00:00:03.000',raw);self.assertIn('align:start',raw);self.assertIn('00:00:03.000 --> 00:00:06.000',raw);doc.set_raw(raw);self.assertEqual(doc.values,['Uma fala.'])
    def test_sync_ass_unusual_text_column_and_comma(self):
        path=self.inputs/'a.ass';raw='[Script Info]\nTitle: Test\n[Events]\nFormat: Layer, Text, Start, End, Style\nDialogue: 0,Olá, mundo!,0:00:01.00,0:00:04.00,Default\n';path.write_text(raw,encoding='utf-8');doc=self.workspace.open(path);changed=synced_raw(doc,2,1)
        self.assertIn('Olá, mundo!',changed);self.assertIn('0:00:03.00,0:00:06.00,Default',changed);doc.set_raw(changed);self.assertEqual(doc.bounds,[(3.,6.)]);self.assertEqual(doc.values,['Olá, mundo!'])
    def test_discover_skips_internal_sources_and_has_limit(self):
        excluded=self.inputs/'history';excluded.mkdir();(excluded/'source.srt').write_text(SRT)
        self.assertEqual(discover([self.inputs]),[self.path.resolve()])
        with self.assertRaises(ValueError):discover([self.inputs],limit=0)
    def test_backup_keeps_style_and_synced_versions(self):
        registry=SeriesRegistry(self.app);project=registry.create('Anime');registry.set_style(project,{'register':'formal'});doc=self.workspace.open(self.path);doc.set_raw(synced_raw(doc,1,1));target=self.workspace.save(doc);backup=self.workspace.backup();registry.set_style(project,{'register':'casual'});self.workspace.restore_backup(backup)
        self.assertEqual(registry.style(project)['register'],'formal');self.assertEqual(self.workspace.open(target).bounds[0],(2.,5.))


class SeasonControllerTests(unittest.TestCase):
    setUp=SeasonTests.setUp
    def controller(self):
        self.qt=QCoreApplication.instance() or QCoreApplication([]);backend=Backend(self.app,FakeRuntime(),monitor_enabled=False);self.addCleanup(backend.timer.stop);return backend
    def wait(self,review):
        deadline=time.monotonic()+10
        while review.busy and time.monotonic()<deadline:self.qt.processEvents();time.sleep(.005)
        self.qt.processEvents();self.assertFalse(review.busy)
    def test_search_and_selected_propagation_preserve_originals(self):
        second=self.inputs/'02.PTBR.srt';second.write_text(SRT,encoding='utf-8');backend=self.controller();review=backend.review;season=review.season;season.loadFolder(str(self.inputs));self.wait(review)
        season.search('Primeira',False);self.assertEqual(len(season.hits),2);season.previewReplace('Primeira','Nova',True,True);self.assertEqual(len(season.preview),2);self.assertEqual(season.selectedCount,0)
        season.check(1,True);season.apply();self.wait(review);copies=list(self.workspace.reviewed.glob('*.srt'));self.assertEqual(len(copies),1);self.assertIn('Nova fala.',copies[0].read_text(encoding='utf-8'));self.assertEqual(self.path.read_text(encoding='utf-8'),SRT);self.assertEqual(second.read_text(encoding='utf-8'),SRT)
    def test_stale_preview_never_overwrites_external_changes(self):
        backend=self.controller();review=backend.review;season=review.season;season.loadFolder(str(self.inputs));self.wait(review);season.previewReplace('Primeira','Nova',True,True);season.checkAll(True);self.path.write_text(SRT.replace('Primeira','Externa'),encoding='utf-8');season.apply();self.wait(review)
        self.assertEqual(list(self.workspace.reviewed.glob('*.srt')),[]);self.assertIn('Externa',self.path.read_text(encoding='utf-8'))
    def test_sync_preview_must_match_current_draft(self):
        backend=self.controller();review=backend.review;season=review.season;review.openDocument(str(self.path));self.wait(review);season.previewSync(2,1);review.editCurrent('Changed.');season.applySync();self.assertEqual(review.document.bounds[0],(1.,4.))
        season.previewSync(2,1);season.applySync();self.assertEqual(review.document.bounds[0],(3.,6.));self.assertTrue(review.dirty);self.assertTrue(review.save());self.assertEqual(self.path.read_text(encoding='utf-8'),SRT)
    def test_pipeline_episode_summary_includes_error_and_timing(self):
        runtime=FakeRuntime();pipeline=Pipeline(runtime,self.app);item=dict(id='test',name=self.path.name,path=str(self.path),options={'source_mode':'external'})
        with patch.object(pipeline,'_episode',side_effect=ValueError('Failure')):pipeline._work([item],validate_settings({}),'translate')
        reports=list((self.app/'outputs/studio/episode_reports').glob('*.json'));self.assertEqual(len(reports),1);data=json.loads(reports[0].read_text(encoding='utf-8'));self.assertEqual(data['state'],'Erro');self.assertEqual(data['error'],'Failure');self.assertIsInstance(data['elapsed_seconds'],float)
    def test_project_load_finds_translations_without_cross_anime_leak(self):
        backend=self.controller();review=backend.review;season=review.season;registry=review.registry;project=registry.create('Anime A');other=registry.create('Anime B');review.refreshProjects();review.setProject(project)
        translated=self.app/'outputs/pt-br';translated.mkdir(parents=True)
        for name,identifier in [('a',project),('b',other)]:
            source=self.inputs/(name+'.srt');source.write_text(SOURCE,encoding='utf-8');apply_project(source,source,self.app,identifier)
            target=translated/(name+'.PTBR.srt');target.write_text(SRT,encoding='utf-8');Path(str(target)+'.quality.json').write_text(json.dumps({'source':str(source),'findings':[]}),encoding='utf-8')
        season.loadProject();self.wait(review);self.assertEqual(len(season.summaries),1);self.assertEqual(season.summaries[0]['file'],'a.PTBR.srt');season.search('First line.',False);self.assertEqual(len(season.hits),1)
    def test_propagation_preserves_existing_approvals_except_changed_cues(self):
        doc=self.workspace.open(self.path);doc.approved={0,1};target=self.workspace.save(doc)
        backend=self.controller();review=backend.review;season=review.season;season.loadFolder(str(target));self.wait(review);season.previewReplace('Primeira','Nova',True,True);season.checkAll(True);season.apply();self.wait(review)
        opened=self.workspace.open(target);self.assertEqual(opened.approved,{1});self.assertEqual(opened.values[0],'Nova fala.')
