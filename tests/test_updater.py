"""Real Windows signatures and isolated install/rollback/security regressions."""
import base64,io,json,os,tempfile,threading,time,unittest,uuid,zipfile
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from PySide6.QtCore import QCoreApplication
import update_core as U
from release_crypto import generate_key,sign,verify,protect
from release_info import REPOSITORY,RUNTIME_ID
from test_priority_one import ROOT,FakeRuntime
from studio_ui.backend import Backend

PUBLIC,PRIVATE=generate_key();PIN=base64.b64encode(PUBLIC).decode()
REQUIRED=['studio_launcher.py','release_info.py','update_core.py','release_crypto.py','studio_update_worker.py','studio_ui/backend.py','studio_ui/qml/Main.qml']

def bundle(version='1.0.1',extra=None):
    files={p:b'# payload\n' for p in REQUIRED};files['release_info.py']=('VERSION = '+repr(version)+'\n').encode();files.update(extra or {})
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as archive:
        for path,data in files.items():archive.writestr(path,data)
    data=buffer.getvalue();payload=dict(schema=1,version=version,repository=REPOSITORY,runtime=RUNTIME_ID,zip_size=len(data),zip_sha256=U.sha(data),files=[dict(path=p,size=len(b),sha256=U.sha(b)) for p,b in files.items()])
    return files,data,dict(manifest=payload,signature=base64.b64encode(sign(PRIVATE,U.canonical(payload))).decode())

class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'tests');self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)/'app';self.root.mkdir();self.installed=patch.object(U,'VERSION','1.0.0');self.installed.start();self.addCleanup(self.installed.stop);self.controller_version=patch('studio_ui.update_controller.VERSION','1.0.0');self.controller_version.start();self.addCleanup(self.controller_version.stop);self.pin=patch.object(U,'PUBLIC_KEY_B64',PIN);self.pin.start();self.addCleanup(self.pin.stop)
    def prepared(self):
        files,package,envelope=bundle();job=self.root/'.updates/jobs'/uuid.uuid4().hex;job.mkdir(parents=True);(job/'package.zip').write_bytes(package);U.extract_verified(self.root,job,envelope['manifest'],job/'package.zip');U.save_json(job/'manifest.json',envelope)
        for path in files:target=U.safe_target(self.root,path);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(b'original '+path.encode())
        for path in ('config.json','outputs/pt-br/keep.srt','cache/hub/model.bin','ollama_models_v2/blobs/weights','series_projects/terms.json'):
            target=self.root/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(b'USER DATA')
        return job,files
    def test_cng_signature_and_dpapi_roundtrip(self):
        signature=sign(PRIVATE,b'payload');self.assertTrue(verify(PUBLIC,b'payload',signature));self.assertFalse(verify(PUBLIC,b'changed',signature));self.assertFalse(verify(PUBLIC,b'payload',b'bad'));self.assertEqual(protect(protect(PRIVATE),True),PRIVATE)
    def test_signed_manifest_modification_is_rejected(self):
        _,_,envelope=bundle();self.assertEqual(U.validate_envelope(envelope)['version'],'1.0.1');envelope['manifest']['version']='1.0.2'
        with self.assertRaises(ValueError):U.validate_envelope(envelope)
    def test_protected_paths_and_windows_aliases_rejected_even_when_signed(self):
        for path in ('config.json','runtime/python/python.exe','cache/model.bin','../outside.py','studio_ui/../../config.json','studio_ui/CON.py','studio_ui/file.py:evil','studio_ui/file.py.','studio_ui\\evil.py'):
            _,_,envelope=bundle(extra={path:b'evil'})
            with self.assertRaises(ValueError,msg=path):U.validate_envelope(envelope)
    def test_zip_changes_and_extra_files_rejected(self):
        _,package,envelope=bundle();job=self.root/'.updates/jobs'/uuid.uuid4().hex;job.mkdir(parents=True);path=job/'package.zip';path.write_bytes(package+b'extra')
        with self.assertRaises(ValueError):U.extract_verified(self.root,job,envelope['manifest'],path)
        path.write_bytes(package)
        with zipfile.ZipFile(path,'a') as archive:archive.writestr('../outside.py','bad')
        payload=dict(envelope['manifest'],zip_sha256=U.file_sha(path),zip_size=path.stat().st_size)
        with self.assertRaises(ValueError):U.extract_verified(self.root,job,payload,path)
    def test_apply_and_manual_rollback_preserve_all_user_data(self):
        job,files=self.prepared();before={p:p.read_bytes() for p in self.root.rglob('*') if p.is_file() and '.updates' not in p.parts};U.apply(self.root,job,lambda:True)
        for path,data in files.items():self.assertEqual((self.root/path).read_bytes(),data)
        self.assertEqual((self.root/'config.json').read_bytes(),b'USER DATA');self.assertEqual((self.root/'cache/hub/model.bin').read_bytes(),b'USER DATA');U.rollback(self.root,job)
        for path,data in before.items():self.assertEqual(path.read_bytes(),data)
    def test_health_failure_rolls_back(self):
        job,_=self.prepared();before=(self.root/'studio_launcher.py').read_bytes()
        with self.assertRaises(ValueError):U.apply(self.root,job,lambda:False)
        self.assertEqual((self.root/'studio_launcher.py').read_bytes(),before);self.assertEqual(json.loads((job/'journal.json').read_text())['status'],'rolled_back')
    def test_locked_unchanged_file_does_not_prevent_rollback_of_other_files(self):
        job,_=self.prepared();original=U.write_bytes;locked=self.root/'release_info.py';before=(self.root/'studio_launcher.py').read_bytes()
        def write(path,data):
            if Path(path)==locked:raise PermissionError('locked')
            return original(path,data)
        with patch.object(U,'write_bytes',side_effect=write):
            with self.assertRaises(PermissionError):U.apply(self.root,job)
        self.assertEqual((self.root/'studio_launcher.py').read_bytes(),before);self.assertEqual(json.loads((job/'journal.json').read_text())['status'],'rolled_back')
    def test_interrupted_install_is_recovered_on_next_start(self):
        job,_=self.prepared();before=(self.root/'studio_launcher.py').read_bytes();U.apply(self.root,job);journal=json.loads((job/'journal.json').read_text());journal['status']='applying';U.save_json(job/'journal.json',journal);self.assertEqual(U.recover(self.root),[str(job)]);self.assertEqual((self.root/'studio_launcher.py').read_bytes(),before)
    def test_restore_refuses_overwriting_external_code_changes(self):
        job,_=self.prepared();U.apply(self.root,job);(self.root/'studio_launcher.py').write_bytes(b'manual change')
        with self.assertRaises(ValueError):U.rollback(self.root,job)
        self.assertEqual((self.root/'studio_launcher.py').read_bytes(),b'manual change')
    def test_modified_staged_file_fails_before_any_install_write(self):
        job,_=self.prepared();before=(self.root/'studio_launcher.py').read_bytes();(job/'stage/studio_launcher.py').write_bytes(b'tampered')
        with self.assertRaises(ValueError):U.apply(self.root,job)
        self.assertEqual((self.root/'studio_launcher.py').read_bytes(),before)
    def test_existing_directory_cannot_be_replaced_by_package(self):
        job,_=self.prepared();path=self.root/'release_info.py';path.unlink();path.mkdir();sentinel=path/'keep.txt';sentinel.write_bytes(b'KEEP');before=(self.root/'studio_launcher.py').read_bytes()
        with self.assertRaises(ValueError):U.apply(self.root,job)
        self.assertEqual(sentinel.read_bytes(),b'KEEP');self.assertEqual((self.root/'studio_launcher.py').read_bytes(),before)
    def test_shared_gui_lease_blocks_exclusive_installer(self):
        with U.app_lease(self.root):
            with self.assertRaises(ValueError):
                with U.app_lease(self.root,True):pass
        with U.app_lease(self.root,True):pass
    def test_live_installer_prevents_recovery(self):
        cache=U.internal_root(self.root);U.save_json(cache/'install.lock',{'pid':os.getpid()})
        with U.app_lease(self.root,True):
            with self.assertRaises(ValueError):U.recover(self.root)
    def test_stale_pid_marker_does_not_block_recovery_after_restart(self):
        cache=U.internal_root(self.root);U.save_json(cache/'install.lock',{'pid':os.getpid()});self.assertEqual(U.recover(self.root),[]);self.assertFalse((cache/'install.lock').exists())
    def test_check_urls_refuses_cleartext_and_untrusted_hosts(self):
        for url in ('http://github.com/x','https://example.com/package.zip','https://github.com@evil.example/file','file:///C:/test'):
            with self.assertRaises(ValueError):U.check_url(url)
    def test_missing_release_and_rate_limit_have_distinct_results(self):
        with patch.object(U,'fetch',side_effect=HTTPError('https://api.github.com',404,'Not found',None,None)):self.assertIsNone(U.latest_release())
        with patch.object(U,'fetch',side_effect=HTTPError('https://api.github.com',403,'rate limit',None,None)):
            with self.assertRaisesRegex(ValueError,'GitHub'):U.latest_release()
    def test_download_extract_valid_package_and_reject_downgrade(self):
        _,package,envelope=bundle();release=dict(envelope=envelope,zip_url='https://github.com/'+REPOSITORY+'/releases/download/v1.0.1/SubForgeAI-update-1.0.1.zip')
        def fetch(url,limit,cancel=None,destination=None,progress=None):Path(destination).write_bytes(package)
        with patch.object(U,'fetch',side_effect=fetch):job=U.prepare(self.root,release)
        self.assertTrue((job/'stage/release_info.py').is_file());release['envelope']=bundle('1.0.0')[2]
        with self.assertRaises(ValueError):U.prepare(self.root,release)
    def test_invalid_internal_version_cannot_install(self):
        _,package,envelope=bundle(extra={'release_info.py':b'VERSION="1.0.2"\n'});job=self.root/'.updates/jobs'/uuid.uuid4().hex;job.mkdir(parents=True);(job/'package.zip').write_bytes(package)
        with self.assertRaises(ValueError):U.extract_verified(self.root,job,envelope['manifest'],job/'package.zip')

class UpdateControllerTests(unittest.TestCase):
    setUp=UpdateTests.setUp
    def backend(self):
        self.qt=QCoreApplication.instance() or QCoreApplication([]);backend=Backend(self.root,FakeRuntime(),monitor_enabled=False);self.addCleanup(backend.timer.stop);self.addCleanup(backend.review.fansub.timer.stop);return backend
    def wait(self,review):
        deadline=time.monotonic()+10
        while review.busy and time.monotonic()<deadline:self.qt.processEvents();time.sleep(.005)
        self.qt.processEvents();self.assertFalse(review.busy)
    def test_empty_repo_and_new_release_ui_states(self):
        backend=self.backend();updater=backend.updater
        with patch('studio_ui.update_controller.latest_release',return_value=None):updater.check();self.wait(backend.review)
        self.assertIn('Ainda não há',updater.status);self.assertFalse(updater.canDownload)
        release=dict(version='1.0.1',notes='release notes',page=updater.releasePage)
        with patch('studio_ui.update_controller.latest_release',return_value=release):updater.check();self.wait(backend.review)
        self.assertTrue(updater.canDownload);self.assertEqual(updater.notes,'release notes')
    def test_install_requires_idle_and_launches_helper_before_requesting_close(self):
        backend=self.backend();updater=backend.updater;updater._prepared=self.root/'.updates/jobs'/uuid.uuid4().hex
        with patch.object(updater,'_launch') as launch,patch.object(backend,'requestClose') as close:
            backend._busy=True;updater.install();launch.assert_not_called();backend._busy=False;updater.install();launch.assert_called_once();close.assert_called_once()
