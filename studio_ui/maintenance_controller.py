"""Maintenance UI and opt-in, one-run completion actions."""
from __future__ import annotations
import time,os
from pathlib import Path
from PySide6.QtCore import QObject,Property,Signal,Slot,QTimer
from PySide6.QtWidgets import QApplication,QSystemTrayIcon
from PySide6.QtGui import QIcon
from maintenance_tools import scan_models,verify_model,cleanup_preview,delete_preview

def suspend_windows():
    if os.name!='nt':raise OSError('Suspensão disponível somente no Windows.')
    import ctypes
    api=ctypes.WinDLL('powrprof',use_last_error=True).SetSuspendState;api.argtypes=[ctypes.c_ubyte]*3;api.restype=ctypes.c_ubyte
    if not api(False,False,False):raise OSError('O Windows não permitiu suspender o computador.')


class MaintenanceController(QObject):
    changed=Signal()
    def __init__(self,owner):
        super().__init__(owner);self.owner=owner;self._models=[];self._cleanup=[];self._selected=set();self._result='';self._armed=False;self._action='none';self._deadline=0;self._run=False;self._tray=None;self._panel_open=False
        self.timer=QTimer(self);self.timer.setInterval(1000);self.timer.timeout.connect(self._tick)
        owner.changed.connect(self._activity);owner.preferencesChanged.connect(self.changed.emit)
        owner.review.changed.connect(self._activity)
    def text(self,value):return self.owner.translate(value)
    @Property(bool,notify=changed)
    def panelOpen(self):return self._panel_open
    @Slot(bool)
    def setPanelOpen(self,value):self._panel_open=bool(value);self.changed.emit()
    @Property(int,constant=True)
    def maxCpuThreads(self):return min(256,os.cpu_count() or 1)
    @Property('QVariantList',notify=changed)
    def models(self):
        labels={'ready':'Arquivos necessários presentes','incomplete':'Incompleto','invalid':'Manifesto inválido','present':'Arquivo presente'}
        return [dict(row,index=i,statusLabel=self.text(labels[row['status']])) for i,row in enumerate(self._models)]
    @Property('QVariantList',notify=changed)
    def cleanup(self):
        labels={'previews':'Prévias regeneráveis','logs':'Logs antigos','python':'Cache Python'}
        return [dict(row,checked=row['id'] in self._selected,categoryLabel=self.text(labels[row['category']])) for row in self._cleanup]
    @Property(str,notify=changed)
    def result(self):return self.owner._ui(self._result)
    @Property(int,notify=changed)
    def selectedCount(self):return len(self._selected)
    @Property(float,notify=changed)
    def selectedBytes(self):return float(sum(r['bytes'] for r in self._cleanup if r['id'] in self._selected))
    @Property(bool,notify=changed)
    def sleepArmed(self):return self._armed
    @Property(int,notify=changed)
    def countdown(self):return max(0,int(self._deadline-time.monotonic()+.999)) if self._deadline else 0
    def _protected(self):
        review=self.owner.review;paths=[self.owner._log_path]
        if review.document:paths.extend([review.document.path,review.document.source_path,review.document.origin_path,review.document.video_path,review.document.target])
        paths.extend([review.fansub._image,review.fansub._video]);return paths
    @Slot()
    def refreshModels(self):
        if self.owner.busy:return
        def work():
            store=getattr(self.owner.runtime,'OLLAMA_MODELS_DIR',None)
            return scan_models(self.owner.root,store)
        def done(rows):self._models=rows;self.changed.emit()
        self.owner.review._submit('Lendo modelos locais',work,done)
    @Slot(int)
    def verifyModel(self,index):
        if self.owner.busy or not 0<=index<len(self._models):return
        row=self._models[index]
        def done(result):
            self._result=self.text('{verified} arquivos verificados por SHA-256; {unhashed} sem hash publicado.').format(**result);self.changed.emit();self.owner._notify(self._result)
        self.owner.review._submit('Verificando arquivos do modelo',lambda:verify_model(row,self.owner.review._cancel),done,True)
    @Slot(int)
    def openModel(self,index):
        if 0<=index<len(self._models):self.owner.openPath(self._models[index]['path'])
    @Slot(int)
    def scanCleanup(self,days):
        if self.owner.busy:return
        protected=self._protected()
        def done(rows):self._cleanup=rows;self._selected=set();self._result='';self.changed.emit()
        self.owner.review._submit('Preparando prévia de limpeza',lambda:cleanup_preview(self.owner.root,days,protected),done)
    @Slot(str,bool)
    def selectCleanup(self,identifier,checked):
        if self.owner.busy:return
        if not any(r['id']==identifier for r in self._cleanup):return
        if checked:self._selected.add(identifier)
        else:self._selected.discard(identifier)
        self.changed.emit()
    @Slot(bool)
    def selectAll(self,checked):
        if not self.owner.busy:self._selected={r['id'] for r in self._cleanup} if checked else set();self.changed.emit()
    @Slot()
    def deleteSelected(self):
        # Called only by the explicit confirmation in the UI, using this stored preview.
        if self.owner.busy or not self._selected:return
        entries=[dict(r) for r in self._cleanup if r['id'] in self._selected];protected=self._protected()
        def done(result):
            self._result=self.text('{count} arquivos temporários excluídos.').format(count=result['removed'])
            if result['errors']:self._result+='\n'+'\n'.join(result['errors'])
            self._cleanup=[];self._selected=set();self.changed.emit();self.owner._notify(self._result)
        self.owner.review._submit('Excluindo temporários selecionados',lambda:delete_preview(self.owner.root,entries,protected),done)
    @Slot()
    def armSleep(self):
        if self.owner.busy:return
        self.cancelCompletion();self._armed=True;self.changed.emit();self.owner._notify('Suspensão armada somente para a próxima fila iniciada.')
    @Slot()
    def cancelCompletion(self):
        self._deadline=0;self._armed=False;self._action='none';self.timer.stop();self.changed.emit()
    def begin_run(self):
        armed=self._armed;self.cancelCompletion();self._action=self.owner._settings.get('completion_action','none');self._run=True
        if self._action=='sleep' and not armed:self._action='none';self.owner._notify('A suspensão não foi armada para esta fila.')
    def finish_run(self,cancelled=False):
        if not self._run:return
        self._run=False;action=self._action;self._action='none'
        if cancelled or self.owner._closing:return
        success=bool(self.owner._items) and all(i.get('state')=='Concluído' for i in self.owner._items)
        if action=='notify':self._notify_system('Fila concluída' if success else 'Fila concluída — há episódios com erro');return
        if not success:
            if action in ('sleep','open'):self.owner._notify('A ação final foi cancelada porque há itens pendentes ou com erro.')
            return
        if action=='open':
            results=[p for i in self.owner._items for p in i.get('results',[]) if Path(p).is_file()]
            if results:self.owner.openPath(str(Path(results[-1]).parent))
            else:self.owner.openOutputs()
        elif action=='sleep':
            if self.owner.review.dirty:return
            self._deadline=time.monotonic()+60;self.timer.start();self.changed.emit();self._notify_system('A fila terminou. Suspensão em 60 segundos; você pode cancelar no Studio.')
    def _notify_system(self,message):
        self.owner._notify(message)
        app=QApplication.instance()
        if not isinstance(app,QApplication):return
        app.beep()
        if QSystemTrayIcon.isSystemTrayAvailable():
            if self._tray is None:
                self._tray=QSystemTrayIcon(QIcon(str(self.owner.root/'assets/brand/subforge-studio.ico')),self);self._tray.show()
            self._tray.showMessage('SubForgeAI Studio',self.text(message),QSystemTrayIcon.Information,10000)
    def _activity(self):
        if self._deadline and (self.owner.busy or self.owner.review.dirty):self.cancelCompletion()
    def _tick(self):
        if not self._deadline:return
        if self.owner.busy or self.owner._closing or self.owner.review.dirty:self.cancelCompletion();return
        if self.countdown:self.changed.emit();return
        self._deadline=0;self.timer.stop();self.changed.emit()
        app=QApplication.instance()
        if isinstance(app,QApplication) and app.activeModalWidget() is not None:self.owner._notify('Suspensão cancelada: há uma janela de diálogo aberta.');return
        try:suspend_windows()
        except OSError as exc:self.owner._notify(str(exc))
    def shutdown(self):
        self.cancelCompletion()
        if self._tray:self._tray.hide()
