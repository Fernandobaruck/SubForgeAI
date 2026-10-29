"""Job orchestration/configuration regressions for the Qt presentation."""
from pathlib import Path
import json
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from studio_ui.pipeline import Pipeline, validate_settings


class Runtime:
    WHISPER_SCRIPT = Path('whisper_script.py')
    OLLAMA_SCRIPT = Path('ollama_script.py')
    EXTRACT_SCRIPT = Path('extract_subs.py')
    def __init__(self, folder):
        self.folder = folder
        self.commands = []
        self.fail = None
        self.confirm = True
        self.kills = 0
        self.stops = 0
    def runtime_python(self): return sys.executable
    def _release_translation_memory(self, **kw): pass
    def _ensure_ollama_ready(self, **kw): return not kw['cancel_event'].is_set()
    def kill_all_active_procs(self): self.kills += 1
    def _stop_managed_ollama_server(self, **kw): self.stops += 1
    def run_capture(self, cmd, on_line, **kw):
        self.commands.append(cmd)
        if self.fail and self.fail in Path(cmd[2]).name: return 1
        kind = 'transcription' if 'whisper_script.py' in cmd[1] else 'translation'
        output = self.folder / (Path(cmd[2]).stem + ('.PTBR' if kind == 'translation' else '.EN') + '.srt')
        output.write_text('1\n00:00:00,000 --> 00:00:01,000\nOlá\n', encoding='utf-8')
        on_line('100% (1/1)')
        if self.confirm:
            on_line('[RESULT] '+json.dumps(dict(kind=kind,input=cmd[2],output=str(output))))
        return 0


class StudioPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT/'tests')
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.runtime = Runtime(self.folder)
        self.pipeline = Pipeline(self.runtime, self.folder)

    def item(self, name):
        path = self.folder / name; path.touch()
        return dict(id=name, name=name, path=str(path), state='Aguardando')

    def run_job(self, items, mode='auto', settings=None):
        self.assertTrue(self.pipeline.start(items, settings or {}, mode))
        self.pipeline.thread.join(5)
        self.assertFalse(self.pipeline.busy)
        events = []
        while not self.pipeline.events.empty(): events.append(self.pipeline.events.get())
        return events

    def test_extract_sup_to_srt_requests_ocr_and_returns_output(self):
        events = self.run_job([self.item('episode.sup')], mode='extract', settings={'extract_to':'srt'})
        self.assertEqual(len(self.runtime.commands),1)
        self.assertIn('--ocr',self.runtime.commands[0])
        completed=[event for event in events if event[0]=='item' and event[2].get('state')=='Concluído']
        self.assertTrue(completed)

    def test_auto_confirms_matching_output_before_translation(self):
        events = self.run_job([self.item('episode.mkv')])
        commands = self.runtime.commands
        self.assertEqual(len(commands), 2)
        self.assertTrue(commands[1][2].endswith('episode.EN.srt'))
        self.assertIn('--no-stems', commands[0])
        self.assertEqual(events[-2][2]['state'], 'Concluído')

    def test_subtitle_auto_skips_transcription(self):
        self.run_job([self.item('episode.srt')])
        self.assertEqual(len(self.runtime.commands), 1)
        self.assertEqual(self.runtime.commands[0][1], 'ollama_script.py')

    def test_missing_result_marker_cannot_translate_stale_output(self):
        self.runtime.confirm = False
        events = self.run_job([self.item('episode.mkv')])
        self.assertEqual(len(self.runtime.commands), 1)
        self.assertTrue(any(e[0]=='item' and e[2].get('state')=='Erro' for e in events))

    def test_one_episode_failure_does_not_skip_remaining(self):
        self.runtime.fail = 'bad'
        events = self.run_job([self.item('bad.srt'), self.item('good.srt')])
        terminal = [(e[1],e[2]['state']) for e in events if e[0]=='item' and e[2].get('state') in ('Erro','Concluído')]
        self.assertEqual(terminal, [('bad.srt','Erro'),('good.srt','Concluído')])

    def test_resume_remembers_original_operation(self):
        item = self.item('episode.mkv'); item['operation'] = 'transcribe'
        self.run_job([item], 'resume')
        self.assertEqual(len(self.runtime.commands), 1)

    def test_season_transcription_uses_one_worker_and_exact_outputs(self):
        original = self.runtime.run_capture
        def batch(cmd, on_line, **kw):
            if cmd[1] != 'whisper_script.py': return original(cmd, on_line, **kw)
            self.runtime.commands.append(cmd)
            for source in cmd[2:cmd.index('--outdir')]:
                output = self.folder/(Path(source).stem+'.EN.srt'); output.touch()
                on_line('[RESULT] '+json.dumps(dict(kind='transcription',input=source,output=str(output))))
            return 0
        self.runtime.run_capture = batch
        events = self.run_job([self.item('one.mkv'),self.item('two.mkv')])
        self.assertEqual(sum(c[1]=='whisper_script.py' for c in self.runtime.commands),1)
        translated_inputs = [Path(c[2]).name for c in self.runtime.commands if c[1]=='ollama_script.py']
        self.assertEqual(translated_inputs,['one.EN.srt','two.EN.srt'])
        self.assertEqual(sum(e[0]=='item' and e[2].get('state')=='Concluído' for e in events),2)

    def test_translate_video_requires_extraction_first(self):
        events = self.run_job([self.item('episode.mkv')], 'translate')
        self.assertFalse(self.runtime.commands)
        self.assertTrue(any(e[0]=='item' and e[2].get('state')=='Erro' for e in events))

    def test_cancel_keeps_queue_locked_until_worker_exits(self):
        entered, release = threading.Event(), threading.Event()
        def blocked(*a, **kw): entered.set(); release.wait(5); return 130
        self.runtime.run_capture = blocked
        self.pipeline.start([self.item('episode.srt')], {}, 'translate')
        self.assertTrue(entered.wait(2))
        self.pipeline.cancel()
        self.assertFalse(self.pipeline.start([], {}, 'auto'))
        release.set(); self.pipeline.thread.join(5)
        self.assertFalse(self.pipeline.busy)
        self.assertEqual(self.runtime.stops, 1)

    def test_settings_restrict_models_without_erasing_unknown_keys(self):
        config = validate_settings(dict(ollama_model='old', whisper_model='small',
                                        extract_stream='nope', custom='preserved'))
        self.assertEqual(config['ollama_model'], 'translategemma:12b')
        self.assertEqual(config['whisper_model'], 'large-v3-turbo')
        self.assertEqual(config['extract_stream'], 'all')
        self.assertEqual(config['custom'], 'preserved')


class StudioBackendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtCore import QCoreApplication
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        from studio_ui.backend import Backend
        self.temp = tempfile.TemporaryDirectory(dir=ROOT/'tests')
        self.folder = Path(self.temp.name)
        self.runtime = Runtime(self.folder)
        (self.folder/'config.json').write_text(json.dumps(dict(runtime_python='portable.exe', custom=42)))
        self.backend = Backend(self.folder, self.runtime, monitor_enabled=False)

    def tearDown(self):
        self.backend.shutdown()
        self.app.processEvents()
        self.temp.cleanup()

    def test_settings_merge_preserves_unknown_configuration(self):
        self.backend.updateSetting('whisper_model', 'large-v3')
        config = json.loads((self.folder/'config.json').read_text())
        self.assertEqual(config['runtime_python'], 'portable.exe')
        self.assertEqual(config['custom'], 42)
        self.assertEqual(config['whisper_model'], 'large-v3')

    def test_invalid_stream_does_not_silently_select_all_tracks(self):
        self.backend.updateSetting('extract_stream', '2,3')
        self.backend.updateSetting('extract_stream', 'invalid')
        self.assertEqual(self.backend.settings['extract_stream'], '2,3')

    def test_video_selection_does_not_launch_external_player(self):
        from unittest.mock import patch
        path = self.folder/'ep.mkv'; path.touch()
        with patch('studio_ui.backend.QDesktopServices.openUrl') as open_url:
            self.backend.inspectResult(str(path))
            open_url.assert_not_called()
        self.assertEqual(self.backend.previewPath, str(path))

    def test_queue_deduplicates_paths_and_accepts_file_urls(self):
        from PySide6.QtCore import QUrl
        path = self.folder/'ep.srt'; path.touch()
        self.backend.addFiles([str(path),QUrl.fromLocalFile(str(path)).toString()])
        self.assertEqual(len(self.backend.items), 1)

    def test_busy_prevents_configuration_changes(self):
        self.backend._busy = True
        self.backend.updateSetting('whisper_model','large-v3')
        self.backend.addFiles(['missing.srt'])
        self.assertEqual(self.backend.settings['whisper_model'], 'large-v3-turbo')
        self.assertEqual(self.backend.items, [])
        self.backend._busy = False

    def test_full_season_can_be_added_without_clearing_completed(self):
        paths=[]
        for number in range(1,27):
            path=self.folder/f'episode{number:02}.srt';path.touch();paths.append(str(path))
        self.backend.addFiles(paths[:2])
        for item in self.backend._items:item['state']='Concluído'
        self.backend.addFiles(paths[2:])
        self.assertEqual(len(self.backend.items),26)
        self.assertEqual(self.backend.completed,2)
        self.assertEqual(self.backend.pendingCount,24)
        persisted=json.loads(self.backend._queue_path.read_text(encoding='utf-8'))
        self.assertEqual(len(persisted),26)

    def test_completed_input_can_be_queued_again_without_erasing_history(self):
        path=self.folder/'ep.srt';path.touch();self.backend.addFiles([str(path)])
        original=self.backend._items[0];original.update(state='Concluído',results=['previous.srt'])
        self.backend.addFiles([str(path),str(path)])
        self.assertEqual(len(self.backend.items),2)
        self.assertEqual(original['results'],['previous.srt'])
        self.assertNotEqual(original['id'],self.backend.items[1]['id'])
        self.assertEqual(self.backend.pendingCount,1)

    def test_progress_update_does_not_reset_queue_model(self):
        from PySide6.QtTest import QSignalSpy
        path=self.folder/'ep.srt';path.touch();self.backend.addFiles([str(path)])
        reset=QSignalSpy(self.backend.queueModel.modelReset)
        change=QSignalSpy(self.backend.queueModel.dataChanged)
        self.backend._items[0]['progress']=.5;self.backend.changed.emit()
        self.assertEqual(reset.count(),0)
        self.assertEqual(change.count(),1)
        self.assertEqual(self.backend.queueModel.rowCount(),1)

    def test_new_files_during_execution_continue_after_current_batch(self):
        import time
        entered,release=threading.Event(),threading.Event()
        original=self.runtime.run_capture
        def run(cmd,on_line,**kwargs):
            if Path(cmd[2]).name=='first.srt':entered.set();release.wait(5)
            return original(cmd,on_line,**kwargs)
        self.runtime.run_capture=run
        for name in ('first.srt','second.srt'):(self.folder/name).touch()
        self.backend.addFiles([str(self.folder/'first.srt')]);self.backend.start('translate')
        try:
            self.assertTrue(entered.wait(2))
            self.backend.addFiles([str(self.folder/'second.srt')])
            self.assertEqual(len(self.backend.items),2)
            self.assertEqual(len(self.backend._next_ids),1)
        finally:release.set()
        deadline=time.monotonic()+5
        while self.backend.busy and time.monotonic()<deadline:
            self.backend.drain();self.app.processEvents();time.sleep(.01)
        self.backend.drain()
        self.assertFalse(self.backend.busy)
        self.assertEqual(self.backend.completed,2)
        self.assertEqual([Path(c[2]).name for c in self.runtime.commands],['first.srt','second.srt'])

    def test_cancelled_batch_does_not_auto_start_added_files(self):
        for name in ('first.srt','second.srt'):(self.folder/name).touch()
        self.backend.addFiles([str(self.folder/'first.srt')])
        first=self.backend._items[0]
        self.backend._busy=True;self.backend._active_ids={first['id']}
        first['state']='Executando'
        self.backend.addFiles([str(self.folder/'second.srt')])
        self.backend.pipeline.events.put(('finished',True,None));self.backend.drain()
        self.assertFalse(self.backend.busy)
        self.assertEqual(self.backend.items[1]['state'],'Aguardando')
        self.assertFalse(self.runtime.commands)

    def test_pending_addition_can_be_removed_while_active_item_is_protected(self):
        for name in ('first.srt','second.srt'):(self.folder/name).touch()
        self.backend.addFiles([str(self.folder/'first.srt')])
        first=self.backend.items[0]['id']
        self.backend._busy=True;self.backend._active_ids={first}
        self.backend.addFiles([str(self.folder/'second.srt')])
        second=self.backend.items[1]['id']
        self.backend.removeItem(first);self.assertEqual(len(self.backend.items),2)
        self.backend.removeItem(second);self.assertEqual(len(self.backend.items),1)
        self.assertFalse(self.backend._next_ids)
        self.backend._busy=False

    def test_preview_cannot_modify_subtitle(self):
        path = self.folder/'ep.srt'; path.write_text('1\n00:00:00,000 --> 00:00:01,000\nOlá\n',encoding='utf-8')
        before = path.read_bytes()
        self.backend.inspectResult(str(path))
        self.assertIn('Olá', self.backend.preview)
        self.assertEqual(path.read_bytes(), before)


class StudioRuntimeTests(unittest.TestCase):
    def setUp(self):
        from studio_ui.runtime import Runtime as PortableRuntime
        self.temp = tempfile.TemporaryDirectory(dir=ROOT/'tests')
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.killed = []
        self.legacy = SimpleNamespace(OLLAMA_BASE_URL='http://127.0.0.1:11434',
            OLLAMA_MODELS_DIR=self.folder/'models', _find_ollama_cli=lambda:'ollama.exe',
            _pick_managed_ollama_host=lambda:'127.0.0.1:11435',
            _subprocess_hide_window_kwargs=lambda:{}, _kill_process_tree=self.killed.append)
        self.runtime = PortableRuntime(self.legacy,self.folder)

    def test_owned_server_always_uses_portable_home_and_models(self):
        from unittest.mock import Mock,patch
        import os
        process=Mock();process.poll.return_value=None;process.pid=12345
        with patch.dict(os.environ), patch('studio_ui.runtime.subprocess.Popen',return_value=process) as popen, patch.object(self.runtime,'_tags',side_effect=[[],['translategemma:12b']]):
            self.assertTrue(self.runtime._ensure_ollama_ready(required_model='translategemma:12b'))
            env=popen.call_args.kwargs['env']
            self.assertEqual(env['USERPROFILE'],str(self.folder/'.ollama_home'))
            self.assertEqual(env['OLLAMA_MODELS'],str(self.folder/'models'))
            self.runtime._stop_managed_ollama_server()
        self.assertEqual(self.killed,[12345])

    def test_reused_server_is_never_terminated(self):
        from unittest.mock import patch
        import os
        with patch.dict(os.environ),patch.object(self.runtime,'_tags',return_value=['translategemma:12b']),patch('studio_ui.runtime.subprocess.Popen') as popen:
            self.assertTrue(self.runtime._ensure_ollama_ready(required_model='translategemma:12b'))
            self.runtime._stop_managed_ollama_server()
            popen.assert_not_called()
        self.assertEqual(self.killed,[])

    def test_exited_server_fails_without_waiting_for_timeout(self):
        from unittest.mock import Mock,patch
        import os,time
        process=Mock();process.poll.return_value=7;process.returncode=7
        started=time.monotonic()
        with patch.dict(os.environ),patch.object(self.runtime,'_tags',return_value=[]),patch('studio_ui.runtime.subprocess.Popen',return_value=process):
            self.assertFalse(self.runtime._ensure_ollama_ready(required_model='translategemma:12b'))
        self.assertLess(time.monotonic()-started,1)


if __name__ == '__main__': unittest.main()
