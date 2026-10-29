"""Qt updater: explicit checking/download, separate installer and one-click rollback."""
import json,os,sys,shutil,subprocess
from pathlib import Path
from PySide6.QtCore import QObject,Property,Signal,Slot,QTimer
from release_info import VERSION,REPOSITORY
from update_core import latest_release,prepare,version_tuple,validate_envelope,job_path

class UpdateController(QObject):
    changed=Signal();_progress=Signal(float)
    def __init__(self,owner):
        super().__init__(owner);self.owner=owner;self._release=None;self._prepared=None;self._status='Verifique se há uma nova versão.';self._percent=0.;self._working=False
        self._progress.connect(self._set_progress);owner.preferencesChanged.connect(self.changed.emit);owner.review.changed.connect(self._review_changed)
        for path in sorted((owner.root/'.updates/jobs').glob('*/manifest.json'),key=lambda p:p.stat().st_mtime,reverse=True):
            try:
                data=validate_envelope(json.loads(path.read_text('utf-8')))
                if not (path.parent/'journal.json').exists() and version_tuple(data['version'])>version_tuple(VERSION):self._prepared=path.parent;self._release={'version':data['version'],'notes':'','page':self.releasePage};self._status='Pacote preparado disponível; os arquivos serão revalidados na instalação.';break
            except (OSError,ValueError):continue
        result=owner.root/'.updates/last_result.json'
        if result.is_file():
            try:
                data=json.loads(result.read_text('utf-8'))
                if not data.get('ok'):self._status='A última atualização falhou e foi recuperada. Consulte .updates/last_result.json.'
            except (OSError,ValueError):pass
        if owner._settings.get('update_check_startup') and '--smoke-test' not in sys.argv:QTimer.singleShot(2000,self.check)
    @Property(str,constant=True)
    def installed(self):return VERSION
    @Property(str,constant=True)
    def repository(self):return 'https://github.com/'+REPOSITORY
    @Property(str,constant=True)
    def releasePage(self):return self.repository+'/releases'
    @Property(str,notify=changed)
    def latest(self):return self._release['version'] if self._release else '—'
    @Property(str,notify=changed)
    def notes(self):return self._release.get('notes','') if self._release else ''
    @Property(str,notify=changed)
    def status(self):return self.owner._ui(self._status)
    @Property(float,notify=changed)
    def progress(self):return self._percent
    @Property(bool,notify=changed)
    def canDownload(self):return bool(self._release and not self._prepared and version_tuple(self.latest)>version_tuple(VERSION))
    @Property(bool,notify=changed)
    def ready(self):return self._prepared is not None
    @Property(bool,notify=changed)
    def canRollback(self):return self._backup() is not None
    def _backup(self):
        candidates=[]
        for path in (self.owner.root/'.updates/jobs').glob('*/journal.json'):
            try:
                data=json.loads(path.read_text('utf-8'))
                if data.get('status')=='committed':candidates.append((data.get('created',0),path.parent))
            except (ValueError,OSError):continue
        return max(candidates,key=lambda x:x[0])[1] if candidates else None
    @Slot(float)
    def _set_progress(self,value):self._percent=value;self.changed.emit()
    def _review_changed(self):
        if self._working and not self.owner.review.busy and self.owner.review._cancel.is_set():self._working=False;self._status='Atualização cancelada.';self.changed.emit()
    def _submit(self,status,work,callback):
        if self.owner.busy:return
        self._status=status;self._working=True;self.changed.emit()
        def guarded():
            try:return True,work()
            except Exception as exc:return False,str(exc)
        def done(result):
            self._working=False
            if result[0]:callback(result[1])
            else:self._status=result[1];self.owner._notify(result[1])
            self.changed.emit()
        self.owner.review._submit(status,guarded,done,True)
    @Slot()
    def check(self):
        def done(release):
            if release is None:self._status='Ainda não há uma release publicada neste repositório.';return
            if self._prepared and self._release and self._release['version']!=release['version']:self._prepared=None
            self._release=release
            self._status='Nova versão disponível.' if version_tuple(release['version'])>version_tuple(VERSION) else 'Você está na versão mais recente.'
        self._submit('Consultando atualizações',lambda:latest_release(self.owner.review._cancel),done)
    @Slot()
    def download(self):
        if not self.canDownload:return
        release=self._release;self._percent=0
        def done(job):self._prepared=job;self._percent=1;self._status='Download validado. Pronto para instalar.'
        self._submit('Baixando e validando atualização',lambda:prepare(self.owner.root,release,self.owner.review._cancel,lambda count,total:self._progress.emit(count/total)),done)
    def _launch(self,job,restore=False):
        root=self.owner.root;job=job_path(root,job);helper=job/'helper';helper.mkdir(exist_ok=True);source=Path(__file__).resolve().parents[1]
        for name in ('studio_update_worker.py','update_core.py','release_crypto.py','release_info.py'):shutil.copy2(source/name,helper/name)
        pids=[os.getpid()]
        try:
            import psutil
            parent=psutil.Process().parent()
            if parent and parent.name().casefold()=='subforgeai studio.exe':pids.append(parent.pid)
        except ImportError:pass
        except (OSError,psutil.Error):pass
        command=[str(root/'runtime/python/pythonw.exe'),'-B','-X','utf8',str(helper/'studio_update_worker.py'),'--root',str(root),'--job',str(job),'--wait-pids',','.join(map(str,pids))]
        if restore:command.append('--rollback')
        with (job/'installer.log').open('ab') as log:subprocess.Popen(command,cwd=helper,stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    @Slot()
    def install(self):
        if self.owner.busy or not self._prepared:return
        if self.owner.review.dirty and not self.owner.review.save():return
        try:self._launch(self._prepared);self.owner.requestClose()
        except Exception as exc:self.owner._notify(str(exc))
    @Slot()
    def restore(self):
        if self.owner.busy:return
        job=self._backup()
        if not job:return
        if self.owner.review.dirty and not self.owner.review.save():return
        try:self._launch(job,True);self.owner.requestClose()
        except Exception as exc:self.owner._notify(str(exc))
    @Slot()
    def openRelease(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl(self._release.get('page',self.releasePage) if self._release else self.releasePage))
