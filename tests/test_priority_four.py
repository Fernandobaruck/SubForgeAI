"""Resource dispatch, offline inventories, bounded cleanup and one-shot actions."""
import hashlib,json,os,tempfile,time,unittest,threading
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import QCoreApplication
from maintenance_tools import resources,resource_env,scan_models,verify_model,cleanup_preview,delete_preview
from studio_ui.backend import Backend
from studio_ui.pipeline import validate_settings
from test_priority_one import FakeRuntime,ROOT,SRT


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'tests');self.addCleanup(self.temp.cleanup);self.base=Path(self.temp.name);self.app=self.base/'app';self.app.mkdir()
    def blob_model(self):
        store=self.app/'ollama_models_v2';blobs=store/'blobs';blobs.mkdir(parents=True);data=b'model fixture';sha=hashlib.sha256(data).hexdigest();blob=blobs/('sha256-'+sha);blob.write_bytes(data);manifest=store/'manifests/registry.ollama.ai/library/fixture/12b';manifest.parent.mkdir(parents=True);descriptor=dict(digest='sha256:'+sha,size=len(data),mediaType='application/vnd.ollama.image.model');manifest.write_text(json.dumps({'config':descriptor,'layers':[descriptor]}));return blob,manifest
    def test_resource_validation_and_no_global_environment_changes(self):
        before=dict(os.environ);limits=resources({'resource_cpu_threads':1,'resource_gpu_layers':0,'resource_background':True});env=resource_env(limits);self.assertEqual(env['OMP_NUM_THREADS'],'1');self.assertEqual(env['SUBFORGEAI_GPU_LAYERS'],'0');self.assertEqual(os.environ,before)
        self.assertEqual(resources({'resource_cpu_threads':999})['resource_cpu_threads'],0);self.assertEqual(resources({'resource_gpu_layers':float('nan')})['resource_gpu_layers'],-1)
    def test_ollama_requests_include_limits_without_changing_context_or_precision(self):
        import ollama_script as O
        payloads=[]
        with patch('studio_ui.gpu_policy.ensure_ollama_gpu'),patch.dict(os.environ,{'SUBFORGEAI_CPU_THREADS':'1','SUBFORGEAI_GPU_LAYERS':'0'}),patch.object(O,'_ollama_stream',side_effect=lambda url,body:payloads.append(body) or 'Olá.'):
            self.assertEqual(O._ollama_call('translategemma:12b',[{'role':'user','content':'hello'}]),'Olá.')
        options=payloads[0]['options'];self.assertEqual(options['num_thread'],1);self.assertEqual(options['num_gpu'],999);self.assertEqual(options['num_ctx'],4096);self.assertEqual(payloads[0]['model'],'translategemma:12b')
    def test_ocr_cpu_inference_is_blocked_before_engine_creation(self):
        from pgs_ocr import Reader
        from studio_ui.gpu_policy import GPURequiredError
        with patch('rapidocr.RapidOCR') as engine:
            with self.assertRaises(GPURequiredError): Reader()
            engine.assert_not_called()
    def test_inventory_and_checksum_detect_same_size_corruption(self):
        blob,_=self.blob_model();row=scan_models(self.app)[0];self.assertTrue(row['offline']);result=verify_model(row);self.assertGreater(result['verified'],0);blob.write_bytes(b'X'+blob.read_bytes()[1:])
        with self.assertRaises(ValueError):verify_model(row)
    def test_inventory_missing_or_incomplete_is_not_offline(self):
        blob,_=self.blob_model();blob.unlink();self.assertFalse(scan_models(self.app)[0]['offline'])
        hub=self.app/'cache/hub/models--Fixture--whisper/snapshots'/('a'*40);hub.mkdir(parents=True);(hub/'model.bin').write_bytes(b'model');self.assertFalse(next(r for r in scan_models(self.app) if r['type']=='Hugging Face')['offline'])
        for name in ('config.json','tokenizer.json'):(hub/name).write_text('{}')
        self.assertTrue(next(r for r in scan_models(self.app) if r['type']=='Hugging Face')['offline'])
    def test_malformed_manifest_is_reported_without_breaking_inventory(self):
        _,manifest=self.blob_model();manifest.write_text('[]');rows=scan_models(self.app);self.assertEqual(rows[0]['status'],'invalid');self.assertFalse(rows[0]['offline'])
    def test_background_priority_changes_only_owned_server(self):
        from studio_ui.runtime import Runtime
        from types import SimpleNamespace
        runtime=Runtime(SimpleNamespace(),self.app)
        with patch('psutil.Process') as process:
            runtime.configure_resources({'resource_background':True});process.assert_not_called()
            runtime._server=SimpleNamespace(pid=12345,poll=lambda:None);runtime.configure_resources({'resource_background':True})
            if os.name=='nt':process.assert_called_once_with(12345)
    def test_model_verification_cancellable_and_no_hash_is_explicit(self):
        self.blob_model();row=scan_models(self.app)[0];cancel=threading.Event();cancel.set()
        with self.assertRaises(ValueError):verify_model(row,cancel)
        row['files'][0]['sha256']='';self.assertEqual(verify_model(row)['unhashed'],1)
    def files_for_cleanup(self):
        owned=self.app/'outputs/studio/previews/old/preview.mp4';owned.parent.mkdir(parents=True);owned.write_bytes(b'temporary')
        protected=[]
        for relative in ('outputs/pt-br/episode.srt','outputs/studio/history/state.json','outputs/pt-br/_cache_traducao/progress.json','cache/hub/model.bin','ollama_models_v2/blobs/model','backups/studio/backup.zip','outputs/studio/samples/test.srt'):
            path=self.app/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'keep');protected.append(path)
        return owned,protected
    def test_cleanup_preview_and_delete_preserve_models_results_history_and_checkpoints(self):
        owned,keep=self.files_for_cleanup();entries=cleanup_preview(self.app,0);self.assertEqual([e['path'] for e in entries],[str(owned)]);result=delete_preview(self.app,entries);self.assertEqual(result['removed'],1);self.assertFalse(owned.exists());self.assertTrue(all(p.read_bytes()==b'keep' for p in keep))
    def test_cleanup_age_and_active_file_exclusion(self):
        owned,_=self.files_for_cleanup();self.assertEqual(cleanup_preview(self.app,7),[]);os.utime(owned,(1,1));self.assertEqual(cleanup_preview(self.app,0,[owned]),[]);self.assertEqual(len(cleanup_preview(self.app,7)),1)
        os.utime(owned,(time.time()+86400,time.time()+86400));self.assertEqual(len(cleanup_preview(self.app,0)),1)
    def test_cleanup_rejects_changed_files_and_outside_paths(self):
        owned,_=self.files_for_cleanup();entries=cleanup_preview(self.app,0);owned.write_bytes(b'changed');self.assertEqual(delete_preview(self.app,entries)['removed'],0)
        outside=self.base/'outside.mp4';outside.write_bytes(b'keep');entry=dict(entries[0],path=str(outside));self.assertEqual(delete_preview(self.app,[entry])['removed'],0);self.assertEqual(outside.read_bytes(),b'keep')
    def test_cleanup_revalidates_new_protected_file(self):
        owned,_=self.files_for_cleanup();entries=cleanup_preview(self.app,0);self.assertEqual(delete_preview(self.app,entries,[owned])['removed'],0);self.assertTrue(owned.exists())
    def test_named_old_session_logs_only(self):
        folder=self.app/'logs/studio';folder.mkdir(parents=True)
        for name in ('20260101_010101_abcdef.log','launcher.log','ollama_server.log','qt.log'):(folder/name).write_bytes(b'log')
        self.assertEqual([Path(e['path']).name for e in cleanup_preview(self.app,0)],['20260101_010101_abcdef.log'])


class CompletionTests(unittest.TestCase):
    setUp=MaintenanceTests.setUp
    def backend(self):
        self.qt=QCoreApplication.instance() or QCoreApplication([]);backend=Backend(self.app,FakeRuntime(),monitor_enabled=False);self.addCleanup(backend.timer.stop);self.addCleanup(backend.review.fansub.timer.stop);self.addCleanup(backend.maintenance.timer.stop);return backend
    def completed(self,backend):backend._items=[dict(id='one',path='episode.mkv',state='Concluído',results=[])]
    def test_sleep_requires_explicit_arm_for_each_run(self):
        backend=self.backend();m=backend.maintenance;backend._settings['completion_action']='sleep';self.completed(backend)
        with patch.object(m,'_notify_system'):
            m.begin_run();m.finish_run();self.assertEqual(m.countdown,0);m.armSleep();m.begin_run();m.finish_run();self.assertGreater(m.countdown,0);self.assertFalse(m.sleepArmed);m.cancelCompletion();m.begin_run();m.finish_run();self.assertEqual(m.countdown,0)
    def test_errors_cancellation_and_pending_items_block_sleep(self):
        backend=self.backend();m=backend.maintenance;backend._settings['completion_action']='sleep'
        for state,cancelled in [('Erro',False),('Aguardando',False),('Concluído',True)]:
            backend._items=[dict(id='x',state=state,path='episode.mkv')];m.armSleep();m.begin_run();m.finish_run(cancelled);self.assertEqual(m.countdown,0)
    def test_countdown_cancel_prevents_native_sleep(self):
        backend=self.backend();m=backend.maintenance;m._deadline=time.monotonic()-1
        with patch('studio_ui.maintenance_controller.suspend_windows') as sleep:
            m.cancelCompletion();m._tick();sleep.assert_not_called()
    def test_countdown_calls_native_sleep_once_only_when_idle(self):
        backend=self.backend();m=backend.maintenance
        with patch('studio_ui.maintenance_controller.suspend_windows') as sleep:
            m._deadline=time.monotonic()-1;m._tick();m._tick();sleep.assert_called_once()
    def test_new_work_and_dirty_review_cancel_countdown(self):
        backend=self.backend();m=backend.maintenance;m._deadline=time.monotonic()+60;backend._busy=True;backend.changed.emit();self.assertEqual(m.countdown,0);backend._busy=False
        source=self.base/'source.srt';source.write_text(SRT,encoding='utf-8');backend.review.document=backend.review.workspace.open(source);m._deadline=time.monotonic()+60;backend.review.document.values[0]='Edit';backend.review.changed.emit();self.assertEqual(m.countdown,0)
    def test_notification_and_open_folder_happen_once_at_final_completion(self):
        backend=self.backend();m=backend.maintenance;self.completed(backend);backend._settings['completion_action']='notify'
        with patch.object(m,'_notify_system') as notify:
            m.begin_run();m.finish_run();m.finish_run();notify.assert_called_once()
        backend._settings['completion_action']='open'
        with patch.object(backend,'openOutputs') as opened:
            m.begin_run();m.finish_run();opened.assert_called_once()
    def test_backend_waits_for_added_batches_before_action(self):
        backend=self.backend();m=backend.maintenance;backend._settings['completion_action']='notify';m.begin_run();backend._items=[dict(id='first',path='a.srt',state='Concluído'),dict(id='next',path='b.srt',state='Aguardando')];backend._next_ids={'next'}
        with patch.object(backend.pipeline,'start',return_value=True),patch.object(m,'_notify_system') as notify:
            backend.pipeline.events.put(('finished',False,None));backend.drain();notify.assert_not_called();self.assertTrue(backend._busy)
            backend._items[1]['state']='Concluído';backend.pipeline.events.put(('finished',False,None));backend.drain();notify.assert_called_once()
