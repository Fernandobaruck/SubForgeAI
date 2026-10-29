import hashlib
import json
import tempfile
import threading
import time
import unittest
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from types import SimpleNamespace
from unittest.mock import patch,MagicMock
from PySide6.QtCore import QCoreApplication
from series_registry import SeriesRegistry
from studio_ui import online_glossary as G
from studio_ui.backend import Backend
from test_priority_one import FakeRuntime, ROOT


def fixture(rows=None):
    value=dict(schema=1,id='sample-anime',revision='1',source_language='en',target_language='pt-BR',terms=rows or [dict(source='Tower',target='Torre')])
    raw=json.dumps(value).encode()
    entry=dict(id=value['id'],title='Anime de teste',description='Dados sintéticos',revision='1',source_language='en',target_language='pt-BR',sha256=hashlib.sha256(raw).hexdigest())
    return raw,entry,dict(schema=1,collections=[entry])


class OnlineGlossaryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'tests');self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.registry=SeriesRegistry(self.root);self.project=self.registry.create('Anime sintético')
    def test_collection_integrity_identity_and_languages(self):
        raw,entry,index=fixture();self.assertEqual(G.catalog(index),[entry]);self.assertEqual(G.collection(raw,entry)[0]['target'],'Torre')
        with self.assertRaises(ValueError):G.collection(raw+b' ',entry)
        with self.assertRaises(ValueError):G.collection(raw,dict(entry,revision='2'))
        with self.assertRaises(ValueError):G.catalog(dict(index,collections=[dict(entry,target_language='en')]))
    def test_catalog_rejects_paths_duplicates_and_malformed_entries(self):
        _,entry,index=fixture()
        for bad in ('../escape','x/y','HTTPS://evil','', 'a'*81):
            with self.assertRaises(ValueError):G.catalog(dict(index,collections=[dict(entry,id=bad)]))
        for rows in ([entry,entry],['bad'],[dict(entry,sha256='bad')]):
            with self.assertRaises(ValueError):G.catalog(dict(index,collections=rows))
    def test_terms_reject_empty_oversized_control_and_case_duplicates(self):
        for value in ([],[{}],[dict(source='x',target='')],[dict(source='a\nb',target='b')],[dict(source='a'*501,target='b')],[dict(source='x',target='a'),dict(source='X',target='b')]):
            with self.assertRaises(ValueError):G.terms(value)
    def test_remote_confirmed_flag_is_never_accepted(self):
        self.assertEqual(G.terms([dict(source='x',target='y',confirmed=True,path='private')]),[dict(source='x',target='y')])
    def test_preview_distinguishes_new_duplicate_and_conflict(self):
        rows=G.preview([dict(source='Tower',target='Local',confirmed=True)], [dict(source='Tower',target='Torre'),dict(source='New',target='Novo')])
        self.assertEqual(rows[0]['status'],'conflict');self.assertFalse(rows[0]['eligible']);self.assertTrue(rows[1]['eligible'])
    def test_import_keeps_confirmed_and_unconfirmed_local_conflicts(self):
        self.registry.set_term(self.project,'Tower','Local',True);self.registry.set_term(self.project,'Draft','Rascunho',False)
        old=self.registry.terms(self.project);incoming=[dict(source='Tower',target='Remoto'),dict(source='Draft',target='Outro'),dict(source='New',target='Novo')]
        count=G.apply(self.registry,self.project,incoming,[0,1,2],G.fingerprint(old),dict(collection='sample'))
        current=self.registry.terms(self.project);self.assertEqual(count,1);self.assertEqual(current[:2],old);self.assertFalse(current[2]['confirmed']);self.assertEqual(current[2]['origin']['collection'],'sample')
        self.assertEqual(self.registry.confirmed(self.project),{'Tower':'Local'});self.assertTrue(list((self.registry.base/self.project/'history').glob('*.json')))
    def test_external_edit_rejects_stale_import(self):
        expected=G.fingerprint(self.registry.terms(self.project));self.registry.set_term(self.project,'x','y',True)
        with self.assertRaisesRegex(ValueError,'mudou'):G.apply(self.registry,self.project,[dict(source='new',target='novo')],[0],expected,{})
        self.assertEqual(self.registry.confirmed(self.project),{'x':'y'})
    def test_empty_selection_and_duplicates_do_not_write(self):
        self.registry.set_term(self.project,'Tower','Torre',True);old=self.registry.terms(self.project)
        with self.assertRaises(ValueError):G.apply(self.registry,self.project,[dict(source='Tower',target='Torre')],[0],G.fingerprint(old),{})
        self.assertEqual(self.registry.terms(self.project),old)
    def test_cache_is_used_offline_and_corruption_is_rejected(self):
        raw,entry,index=fixture();store=G.Store(self.root);cancel=threading.Event()
        with patch.object(G,'fetch',return_value=json.dumps(index).encode()):rows,stamp,offline=store.refresh(cancel)
        self.assertFalse(offline)
        with patch.object(G,'fetch',return_value=raw):self.assertEqual(store.load(entry,cancel)[0][0]['target'],'Torre')
        with patch.object(G,'fetch',side_effect=OSError('offline')):
            self.assertTrue(store.refresh(cancel)[2]);self.assertTrue(store.load(entry,cancel)[1])
            (store.base/(entry['id']+'-'+entry['sha256']+'.json')).write_bytes(b'broken')
            with self.assertRaises(ValueError):store.load(entry,cancel)
    def test_cancellation_does_not_fall_back_to_cache(self):
        cancel=threading.Event();cancel.set();store=G.Store(self.root)
        with patch.object(G,'fetch',side_effect=OSError('stopped')):
            with self.assertRaisesRegex(ValueError,'interrompida'):store.refresh(cancel)
    def test_fetch_rejects_oversized_responses_and_cancelled_reads(self):
        response=SimpleNamespace(read=lambda size:b'x'*size)
        with patch.object(G,'build_opener') as opener:
            opener.return_value.open.return_value.__enter__.return_value=response
            with self.assertRaisesRegex(ValueError,'limite'):G.fetch('index.json')
            cancel=threading.Event();cancel.set()
            with self.assertRaisesRegex(ValueError,'interrompida'):G.fetch('index.json',cancel)
    def test_redirect_rejects_other_hosts_and_paths(self):
        for url in ('https://example.com/x','http://raw.githubusercontent.com/x','https://raw.githubusercontent.com/other/repo/main/index.json'):
            with self.assertRaises(ValueError):G.Redirect().redirect_request(None,None,302,'',{},url)
    def test_invalid_cache_does_not_break_startup(self):
        store=G.Store(self.root);store.base.mkdir(parents=True);(store.base/'index.json').write_text('{"catalog":{"schema":1,"collections":[null]}}')
        self.assertEqual(store.cached_catalog(),([],''))
    def test_cache_preserves_utf8_bom_and_line_endings_for_integrity_checks(self):
        raw,entry,_=fixture();raw=b'\xef\xbb\xbf'+raw.replace(b',',b',\r\n');entry['sha256']=hashlib.sha256(raw).hexdigest()
        store=G.Store(self.root);cancel=threading.Event()
        with patch.object(G,'fetch',return_value=raw):self.assertFalse(store.load(entry,cancel)[1])
        with patch.object(G,'fetch',side_effect=OSError('offline')):self.assertTrue(store.load(entry,cancel)[1])


class OnlineControllerTests(unittest.TestCase):
    setUp=OnlineGlossaryTests.setUp
    def backend(self):
        self.qt=QCoreApplication.instance() or QCoreApplication([])
        with patch.object(G,'fetch',side_effect=AssertionError('Automatic network request')) as fetch:
            backend=Backend(self.root,FakeRuntime(),monitor_enabled=False);fetch.assert_not_called()
        self.addCleanup(backend.timer.stop);self.addCleanup(backend.review.fansub.timer.stop);backend.review.setProject(self.project)
        return backend,backend.review.online
    def wait(self,backend):
        deadline=time.monotonic()+10
        while backend.review.busy and time.monotonic()<deadline:self.qt.processEvents();time.sleep(.005)
        self.qt.processEvents();self.assertFalse(backend.review.busy)
    def test_preview_and_selection_reset_when_project_changes(self):
        backend,online=self.backend();raw,entry,index=fixture();online._catalog=[entry]
        with patch.object(online.store,'load',return_value=(G.terms(json.loads(raw)['terms']),False)):
            online.load(entry['id']);self.wait(backend)
        online.selectNew();self.assertEqual(online.selectedCount,1)
        other=backend.review.registry.create('Outro anime');backend.review.refreshProjects();backend.review.setProject(other)
        self.assertEqual(online.selectedCount,0);self.assertEqual(online.rows,[])
    def test_import_integration_stays_unconfirmed_until_manual_review(self):
        backend,online=self.backend();raw,entry,_=fixture();online._catalog=[entry]
        with patch.object(online.store,'load',return_value=(G.terms(json.loads(raw)['terms']),False)):
            online.load(entry['id']);self.wait(backend)
        online.selectNew();online.importSelected();self.assertFalse(backend.review.terms[0]['confirmed']);self.assertEqual(backend.review.registry.confirmed(self.project),{})
        backend.review.saveTerm('Tower','Torre',True);self.assertEqual(backend.review.registry.confirmed(self.project),{'Tower':'Torre'})
    def test_share_contains_only_explicitly_selected_confirmed_terms(self):
        backend,online=self.backend();backend.review.saveTerm('Keep','Manter',True);backend.review.saveTerm('Draft','Rascunho',False)
        self.assertEqual(online.contribution,'');online.selectShare('Keep',True);online.selectShare('Draft',True)
        proposal=json.loads(online.contribution);self.assertEqual(proposal['terms'],[dict(source='Keep',target='Manter')]);self.assertNotIn(str(self.root),online.contribution)
        with patch('studio_ui.online_glossary_controller.QDesktopServices.openUrl',return_value=True) as open_url:
            online.contribute();self.assertEqual(open_url.call_count,1);self.assertIn('/issues/new?',open_url.call_args[0][0].toString())
    def test_ai_never_changes_local_glossary_and_requires_complete_response(self):
        backend,online=self.backend();backend.runtime.processes=SimpleNamespace(OLLAMA_BASE_URL='http://127.0.0.1:11434')
        response=MagicMock(status=200);response.__iter__.return_value=iter([b'{"message":{"content":"Torre"}}',b'{"done":true}'])
        with patch('studio_ui.gpu_policy.ensure_ollama_gpu'), patch('studio_ui.glossary_ai.http.client.HTTPConnection') as connection:
            connection.return_value.getresponse.return_value=response;online.suggest('Tower','en');self.wait(backend)
        self.assertEqual(online.aiSuggestion,'Torre');self.assertEqual(backend.review.terms,[])
        online.saveSuggestion('Tower','Torre');self.assertFalse(backend.review.terms[0]['confirmed'])
        backend.review.saveTerm('Tower','Confirmado',True);online.saveSuggestion('Tower','Sobrescrever')
        self.assertEqual(backend.review.registry.confirmed(self.project),{'Tower':'Confirmado'})
    def test_ai_refuses_non_local_endpoint(self):
        backend,online=self.backend();backend.runtime.processes=SimpleNamespace(OLLAMA_BASE_URL='https://example.com')
        with patch('studio_ui.gpu_policy.ensure_ollama_gpu'), patch('studio_ui.glossary_ai.http.client.HTTPConnection') as connection:online.suggest('Tower','en');self.wait(backend);connection.assert_not_called()
        self.assertEqual(online.aiSuggestion,'')
    def test_incomplete_ai_response_is_not_presented_as_a_suggestion(self):
        backend,online=self.backend();backend.runtime.processes=SimpleNamespace(OLLAMA_BASE_URL='http://127.0.0.1:11434')
        response=MagicMock(status=200);response.__iter__.return_value=iter([b'{"message":{"content":"partial"}}'])
        with patch('studio_ui.gpu_policy.ensure_ollama_gpu'), patch('studio_ui.glossary_ai.http.client.HTTPConnection') as connection:
            connection.return_value.getresponse.return_value=response;online.suggest('Tower','en');self.wait(backend)
        self.assertEqual(online.aiSuggestion,'');self.assertEqual(backend.review.terms,[])
    def test_history_excludes_style_and_subtitle_memory(self):
        backend,online=self.backend();backend.review.saveTerm('One','Um',True);backend.review.saveTerm('Two','Dois',True)
        backend.review.registry.remember(self.project,'PRIVATE SENTENCE','PRIVATE TRANSLATION')
        online.localHistory();self.assertIn('One → Um',online.historyText);self.assertNotIn('PRIVATE',online.historyText)
    def test_cancel_interrupts_cold_model_loading_without_waiting_for_read_timeout(self):
        from studio_ui.glossary_ai import suggest
        import http.client
        cancel=threading.Event();shutdown=threading.Event()
        with patch('studio_ui.gpu_policy.ensure_ollama_gpu'), patch('studio_ui.glossary_ai.http.client.HTTPConnection') as cls:
            connection=cls.return_value;connection.sock.shutdown.side_effect=lambda how:shutdown.set()
            def loading():
                if not shutdown.wait(3):raise AssertionError('Cancellation did not interrupt socket')
                raise http.client.RemoteDisconnected('cancelled')
            connection.getresponse.side_effect=loading
            timer=threading.Timer(.15,cancel.set);timer.start();started=time.monotonic()
            try:
                with self.assertRaisesRegex(ValueError,'interrompida'):suggest('http://127.0.0.1:11434','Tower','en',cancel)
            finally:timer.join()
            self.assertLess(time.monotonic()-started,1.5);connection.sock.settimeout.assert_called_once_with(180)
    def test_ai_reuses_confirmed_local_term_without_querying_the_model(self):
        backend,online=self.backend();backend.review.saveTerm('Tower','Tradução aprovada',True)
        with patch.object(backend.runtime,'_ensure_ollama_ready') as prepare:
            online.suggest('tower','en');prepare.assert_not_called()
        self.assertEqual(online.aiSuggestion,'Tradução aprovada')
    def test_external_change_cannot_share_data_different_from_the_preview(self):
        backend,online=self.backend();backend.review.saveTerm('Term','Approved',True);online.selectShare('Term',True)
        self.assertIn('Approved',online.contribution)
        backend.review.registry.set_term(self.project,'Term','EXTERNAL CHANGE',True)
        self.assertEqual(online.contribution,'')
        with patch('studio_ui.online_glossary_controller.QDesktopServices.openUrl') as browser:
            online.contribute();browser.assert_not_called()


if __name__=='__main__':unittest.main()
