"""Qt adapter. All worker events are consumed on the Qt main thread."""
from __future__ import annotations

import json
import queue
import threading
import time
import uuid
from pathlib import Path

from PySide6.QtCore import QObject, Property, QTimer, Signal, Slot, QUrl, Qt, QTranslator, QLibraryInfo, QCoreApplication
from PySide6.QtGui import QDesktopServices, QPalette, QColor
from PySide6.QtWidgets import QApplication, QFileDialog

from pipeline_io import atomic_write_text
from .pipeline import Pipeline, DEFAULTS, MEDIA, SUBTITLES, path_key, resolve_dir, validate_settings
from .queue_model import EpisodeListModel
from .review_controller import ReviewController
from .presentation import UI_DEFAULTS, LANGUAGES, THEMES, COLORS, Translations, normalize_preferences


class Backend(QObject):
    changed = Signal()
    preferencesChanged = Signal()
    message = Signal(str)
    closeReady = Signal()
    _hardwareReady = Signal(dict)
    _resultsReady = Signal(list)

    def __init__(self, root, runtime, monitor_enabled=True):
        super().__init__(QCoreApplication.instance())
        self.root, self.runtime = Path(root), runtime
        self.pipeline = Pipeline(runtime, root)
        self._translations = Translations()
        self._settings = self._load_settings()
        self._qt_translator = QTranslator(self)
        self._apply_ui_preferences()
        self._items = []
        self._results = []
        self._busy = False
        self._status = 'Pronto para começar'
        self._console = ''
        self._preview = ''
        self._preview_is_placeholder = False
        self._preview_title = 'Selecione uma legenda'
        self._preview_path = ''
        self._hardware = 'Detectando hardware…'
        self._metrics = {}
        self._closing = False
        self._scanning = False
        self._operation = 'auto'
        self._active_ids = set()
        self._next_ids = set()
        self._active_settings = dict(self._settings)
        self._queue_model = EpisodeListModel(self)
        self._queue_path = self.root / 'outputs/studio/queue.json'
        self._log_path = self.root / 'logs/studio' / (time.strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:6] + '.log')
        self._review = ReviewController(self)
        from .maintenance_controller import MaintenanceController
        self._maintenance=MaintenanceController(self)
        from .update_controller import UpdateController
        self._updater=UpdateController(self)
        self._restore_queue()
        self.changed.connect(self._sync_queue_model)
        self._sync_queue_model()
        self._hardwareReady.connect(self._set_hardware)
        self._resultsReady.connect(self._set_results)
        self.timer = QTimer(self)
        self.timer.setInterval(150)
        self.timer.timeout.connect(self.drain)
        self.timer.start()
        self.monitor = None
        if monitor_enabled:
            from monitor import SystemMonitor
            self.monitor = SystemMonitor(lambda values: self.pipeline.events.put(('metrics', values, None)), interval=2)
            self.monitor.start()
            threading.Thread(target=self._detect_hardware, daemon=True).start()
        self.refreshResults()

    def _load_settings(self):
        try:
            data = json.loads((self.root / 'config.json').read_text(encoding='utf-8-sig'))
            values = validate_settings(data if isinstance(data, dict) else {})
            return {**values, **normalize_preferences(values)}
        except (OSError, ValueError):
            return {**validate_settings({}), **UI_DEFAULTS}

    def _restore_queue(self):
        try:
            saved = json.loads(self._queue_path.read_text(encoding='utf-8'))
            for item in saved:
                if not isinstance(item, dict) or not Path(item.get('path', '')).is_file():
                    continue
                item.setdefault('results', [])
                if item.get('state') == 'Executando':
                    item.update(state='Interrompido', stage='Disponível para retomar', progress=0)
                self._items.append(item)
        except (OSError, ValueError, TypeError):
            pass

    def _save_queue(self):
        try:
            self._queue_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(self._queue_path, json.dumps(self._items, ensure_ascii=False, indent=2))
            return True
        except OSError as exc:
            self._notify(f'Não foi possível salvar a fila: {exc}')
            return False

    @Property('QVariantList', notify=changed)
    def items(self): return [dict(item, removable=item['id'] not in self._active_ids,
                                stateLabel=self._ui(item.get('state','')),stageLabel=self._ui(item.get('stage','')),
                                errorLabel=self._ui(item.get('error',''))) for item in self._items]

    @Property(QObject, constant=True)
    def review(self): return self._review
    @Property(QObject,constant=True)
    def maintenance(self):return self._maintenance
    @Property(QObject,constant=True)
    def updater(self):return self._updater

    @Property(QObject, constant=True)
    def queueModel(self): return self._queue_model

    def _sync_queue_model(self): self._queue_model.sync(self.items)

    @Property(int, notify=changed)
    def pendingCount(self): return sum(i.get('state') == 'Aguardando' for i in self._items)

    @Property('QVariantList', notify=changed)
    def results(self): return self._results

    @Property('QVariantMap', notify=changed)
    def settings(self): return self._settings

    @Property('QVariantMap', notify=changed)
    def metrics(self): return self._metrics

    @Property(bool, notify=changed)
    def busy(self): return self._busy or bool(getattr(self,'_review',None) and self._review.busy)

    @Property(str, notify=changed)
    def status(self): return self._review.job if self._review.busy else self._ui(self._status)

    @Property(str, notify=changed)
    def console(self): return self._console

    @Property(str, notify=changed)
    def hardware(self): return self._ui(self._hardware)

    @Property(str, notify=changed)
    def preview(self): return self._ui(self._preview) if self._preview_is_placeholder else self._preview

    @Property(str, notify=changed)
    def previewTitle(self): return self._ui(self._preview_title)

    @Property(str, notify=changed)
    def previewPath(self): return self._preview_path

    @Property(str, notify=changed)
    def previewFolder(self): return str(Path(self._preview_path).parent) if self._preview_path else ''

    @Property(int, notify=changed)
    def completed(self): return sum(i.get('state') == 'Concluído' for i in self._items)

    @Property(int, notify=changed)
    def failed(self): return sum(i.get('state') == 'Erro' for i in self._items)

    @Property(str, notify=changed)
    def logPath(self): return str(self._log_path)

    def _ui(self, text):
        return self._translations.message(self.uiLanguage,text)

    def _notify(self, text):
        self.message.emit(self._ui(text))

    @Property(str, notify=preferencesChanged)
    def uiLanguage(self): return self._settings['ui_language']

    @Property(str, notify=preferencesChanged)
    def uiTheme(self): return self._settings['ui_theme']

    @Property('QVariantMap', notify=preferencesChanged)
    def themePalette(self): return COLORS[self.uiTheme]

    @Slot(str, result=str)
    def translate(self, source):
        return self._translations.text(self.uiLanguage,source)

    @Slot(str, 'QVariantMap', result=str)
    def formatText(self, source, values):
        return self._translations.text(self.uiLanguage,source,values)

    def _apply_ui_preferences(self):
        app=QApplication.instance()
        if not isinstance(app,QApplication):return
        app.removeTranslator(self._qt_translator)
        locale={'pt-BR':'pt_BR','en':'en','es':'es'}[self.uiLanguage]
        if self._qt_translator.load('qtbase_'+locale,QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
            app.installTranslator(self._qt_translator)
        app.styleHints().setColorScheme(Qt.ColorScheme.Dark if self.uiTheme=='dark' else Qt.ColorScheme.Light)
        colors=COLORS[self.uiTheme];palette=QPalette()
        for role,key in ((QPalette.Window,'bg'),(QPalette.WindowText,'text'),(QPalette.Base,'card'),
                         (QPalette.AlternateBase,'elevated'),(QPalette.Text,'text'),(QPalette.Button,'elevated'),
                         (QPalette.ButtonText,'text'),(QPalette.Highlight,'accent'),(QPalette.HighlightedText,'accentText'),
                         (QPalette.ToolTipBase,'card'),(QPalette.ToolTipText,'text'),(QPalette.PlaceholderText,'muted')):
            palette.setColor(role,QColor(colors[key]))
        for role in (QPalette.WindowText,QPalette.Text,QPalette.ButtonText):
            palette.setColor(QPalette.Disabled,role,QColor(colors['disabledText']))
        app.setPalette(palette)

    @Slot(str, 'QVariant')
    def updateSetting(self, key, value):
        if (self.busy and key not in UI_DEFAULTS) or key not in {*DEFAULTS,*UI_DEFAULTS}:
            return
        if key == 'whisper_language' and not isinstance(value, str):
            return
        if key=='ui_language' and value not in LANGUAGES:
            self._notify('Idioma de interface não suportado.'); return
        if key=='ui_theme' and value not in THEMES:
            self._notify('Tema não suportado.'); return
        updated = validate_settings({**self._settings, key: value})
        updated.update(normalize_preferences(updated))
        if key in ('extract_stream','whisper_audio_stream') and str(value) != updated[key]:
            self._notify('Informe auto ou um índice para áudio; all ou índices separados por vírgula para legendas.')
            self.changed.emit()
            return
        try:
            # Merge the latest disk contents so unknown/legacy keys survive.
            try:
                current = json.loads((self.root / 'config.json').read_text(encoding='utf-8-sig'))
            except FileNotFoundError:
                current = {}
            if not isinstance(current, dict): current = {}
            current[key] = updated[key]
            if key == 'subs_out_dir': current['ocr_out_dir'] = updated[key]
            if key == 'whisper_demucs_mode': current['whisper_use_demucs'] = updated[key] == 'enabled'
            atomic_write_text(self.root / 'config.json', json.dumps(current, ensure_ascii=False, indent=2))
        except (OSError, ValueError) as exc:
            self._notify(f'Não foi possível salvar a configuração: {exc}')
            return
        self._settings = updated
        if key in UI_DEFAULTS:
            self._apply_ui_preferences()
            self.preferencesChanged.emit()
        self.changed.emit()

    @Slot()
    def chooseFiles(self):
        paths, _ = QFileDialog.getOpenFileNames(None, self.translate('Adicionar episódios ou legendas'), str(self.root),
            self.translate('Vídeos, áudios e legendas') + ' (*.mkv *.mp4 *.avi *.mov *.webm *.m4v *.mpg *.mpeg *.ts *.m2ts *.mp3 *.wav *.flac *.m4a *.aac *.ogg *.srt *.ass *.vtt *.ssa *.sub *.sup *.idx *.mks);;' + self.translate('Todos os arquivos') + ' (*)', options=QFileDialog.Option.DontUseNativeDialog)
        self.addFiles(paths)

    @Slot('QVariantList')
    def addFiles(self, paths):
        if self._maintenance.countdown:self._maintenance.cancelCompletion()
        known = {path_key(i['path']) for i in self._items if i.get('state') != 'Concluído' and not (i.get('options') or {}).get('sample_seconds')}
        rejected = 0
        duplicates = 0
        added = 0
        for value in paths:
            url = QUrl(str(value))
            path = Path(url.toLocalFile() if url.isLocalFile() else str(value)).resolve()
            if not path.is_file() or path.suffix.lower() not in MEDIA | SUBTITLES:
                rejected += 1
                continue
            if path_key(path) in known:
                duplicates += 1
                continue
            known.add(path_key(path))
            self._items.append(dict(id=uuid.uuid4().hex, path=str(path), name=path.name,
                type='Legenda' if path.suffix.lower() in SUBTITLES else 'Vídeo / áudio',
                state='Aguardando', stage='Na fila', progress=0, error='', results=[], operation=self._operation))
            added += 1
            if self._busy and not self._closing:
                self._next_ids.add(self._items[-1]['id'])
        self._save_queue()
        self.changed.emit()
        if rejected: self._notify(f'{rejected} arquivo(s) indisponíveis ou com formato não suportado.')
        elif duplicates: self._notify(f'{added} adicionado(s); {duplicates} já está(ão) na fila pendente. Concluídos podem ser adicionados novamente.')
        elif added and self._busy: self._notify(f'{added} episódio(s) adicionado(s). Serão processados após o lote atual, com a mesma operação e configurações.')

    @Slot(str)
    def requeueItem(self, identifier):
        item = next((i for i in self._items if i['id'] == identifier), None)
        if item and item.get('state') == 'Concluído':
            import copy
            duplicate=next((other for other in self._items if other.get('state')!='Concluído' and path_key(other['path'])==path_key(item['path']) and other.get('options',{})==item.get('options',{})),None)
            if duplicate:return
            fresh=copy.deepcopy(item);fresh.update(id=uuid.uuid4().hex,state='Aguardando',stage='Na fila',progress=0,error='',results=[])
            self._items.append(fresh)
            if not self._save_queue():self._items.pop();return
            if self._busy and not self._closing:self._next_ids.add(fresh['id'])
            self.changed.emit()

    @Slot(str)
    def removeItem(self, identifier):
        if identifier in self._active_ids: return
        self._next_ids.discard(identifier)
        self._items = [i for i in self._items if i['id'] != identifier]
        self._save_queue()
        self.changed.emit()

    @Slot()
    def clearFinished(self):
        self._items = [i for i in self._items if i.get('state') != 'Concluído']
        self._save_queue()
        self.changed.emit()

    @Slot(str)
    def start(self, operation):
        if self.busy: return
        if operation not in ('auto', 'transcribe', 'translate', 'extract'): return
        pending = [i for i in self._items if i.get('state') != 'Concluído']
        if not pending:
            self._notify('Adicione arquivos à fila antes de iniciar.')
            return
        for item in pending:
            item.update(state='Aguardando', stage='Na fila', error='', progress=0, operation=operation)
        self._save_queue()
        self._operation = operation
        self._active_settings = dict(self._settings)
        self._active_ids = {i['id'] for i in pending}
        self._next_ids.clear()
        self._busy = True
        self._status = 'Preparando a fila…'
        if not self.pipeline.start(pending, dict(self._settings), operation):
            self._busy = False
            self._active_ids.clear()
            self._notify('A tarefa anterior ainda está encerrando. Aguarde um instante.')
        else:self._maintenance.begin_run()
        self.changed.emit()

    @Slot(str)
    def sampleItem(self,identifier):
        if self.busy:return
        original=next((item for item in self._items if item['id']==identifier),None)
        if not original:return
        from source_selection import validate_options
        options=validate_options(original.get('options'));options['sample_seconds']=60
        item=dict(original,id=uuid.uuid4().hex,name=original['name']+' · '+self.translate('Teste de 60 s'),state='Aguardando',stage='Na fila',progress=0,error='',results=[],options=options,operation='auto')
        self._items.append(item);self._save_queue();self._operation='auto';self._active_settings=dict(self._settings);self._active_ids={item['id']};self._next_ids.clear();self._busy=True
        if not self.pipeline.start([item],dict(self._settings),'auto'):
            self._busy=False;self._active_ids.clear()
        else:self._maintenance.begin_run()
        self.changed.emit()

    @Slot()
    def retryFailed(self):
        if self.busy: return
        failed = [i for i in self._items if i.get('state') in ('Erro', 'Interrompido')]
        if not failed:
            self._notify('Não há episódios com erro ou interrompidos.')
            return
        self._busy = True
        self._status = 'Retomando episódios…'
        operations = {i.get('operation','auto') for i in failed}
        self._operation = next(iter(operations)) if len(operations) == 1 else 'auto'
        self._active_settings = dict(self._settings)
        self._active_ids = {i['id'] for i in failed}
        self._next_ids.clear()
        if not self.pipeline.start(failed, dict(self._settings), 'resume'):
            self._busy = False
            self._active_ids.clear()
        else:self._maintenance.begin_run()
        self.changed.emit()

    @Slot()
    def stop(self):
        if self._review.busy:
            self._review.cancel(); return
        if not self._busy: return
        self._status = 'Interrompendo com segurança…'
        self.pipeline.cancel()
        self.changed.emit()

    @Slot()
    def requestClose(self):
        if self._review.dirty and not self._review.busy and not self._review.save():return
        self._maintenance.cancelCompletion()
        self._closing = True
        if self.busy:
            self.stop()
        else:
            self.closeReady.emit()

    @Slot()
    def drain(self):
        changed = False
        while True:
            try: event, key, data = self.pipeline.events.get_nowait()
            except queue.Empty: break
            if event == 'metrics':
                self._metrics = key
            elif event == 'item':
                for item in self._items:
                    if item['id'] == key:
                        item.update(data)
                        if item['state'] == 'Executando': self._status = item['stage'] + ' · ' + item['name']
                        break
            elif event == 'finished':
                # The event is enqueued just before the worker returns. Keep busy
                # until the thread actually exits, including cancellation cleanup.
                if self.pipeline.busy:
                    QTimer.singleShot(50, lambda cancelled=key: self.pipeline.events.put(('finished', cancelled, None)))
                    continue
                self._busy = False
                self._active_ids.clear()
                if key:
                    for item in self._items:
                        if item['state'] == 'Executando':
                            item.update(state='Interrompido', stage='Disponível para retomar')
                self._status = ('Interrompido — você pode retomar' if key else
                                'Fila concluída — há episódios com erro' if self.failed else 'Fila concluída')
                self._save_queue()
                self.refreshResults()
                if self._closing:
                    self._next_ids.clear()
                    self.closeReady.emit()
                elif not key:
                    waiting = [i for i in self._items if i['id'] in self._next_ids and i.get('state') == 'Aguardando']
                    self._next_ids.clear()
                    if waiting:
                        if self.pipeline.start(waiting, self._active_settings, self._operation):
                            self._active_ids = {i['id'] for i in waiting}
                            self._busy = True
                            self._status = 'Processando os episódios adicionados…'
                        else:
                            self._status = 'Há episódios aguardando — clique em Iniciar fila.'
                else:
                    self._next_ids.clear()
                if not self._busy:self._maintenance.finish_run(bool(key))
            changed = True
        lines = []
        for _ in range(160):
            try: lines.append(self.pipeline.logs.get_nowait())
            except queue.Empty: break
        if lines:
            self._console = '\n'.join((self._console.splitlines() + lines)[-1600:])
            try:
                self._log_path.parent.mkdir(parents=True, exist_ok=True)
                with self._log_path.open('a', encoding='utf-8') as f: f.write('\n'.join(lines) + '\n')
            except OSError: pass
            changed = True
        if changed: self.changed.emit()

    def _detect_hardware(self):
        try:
            from profile_manager import detect_hw
            hw = detect_hw()
            self._hardwareReady.emit(dict(text=f'{hw.gpu_name or "CPU"}  ·  {hw.vram_gb:.0f} GB VRAM  ·  {hw.ram_gb:.0f} GB RAM'))
        except Exception:
            self._hardwareReady.emit(dict(text='Hardware disponível no diagnóstico'))

    @Slot(dict)
    def _set_hardware(self, values):
        self._hardware = values['text']
        self.changed.emit()

    @Slot()
    def refreshResults(self):
        if self._scanning: return
        self._scanning = True
        # Scan only outputs and configured destinations, not models/runtime.
        destinations = {self.root / 'outputs'}
        destinations.update(resolve_dir(self.root, self._settings[k]) for k in
                            ('whisper_out_dir', 'ollama_out_dir', 'subs_out_dir', 'embed_output_dir'))
        def scan():
            found = {}
            try:
                for folder in destinations:
                    if not folder.is_dir(): continue
                    for path in folder.rglob('*'):
                        if not path.is_file() or (path.suffix.lower() not in {'.srt', '.ass', '.vtt', '.mkv', '.mp4'} and not path.name.endswith('.review_required.json')): continue
                        internal=self.root/'outputs/studio'
                        if path.is_relative_to(internal) and path.relative_to(internal).parts[0] in ('history','context_inputs','previews','retranslate'):continue
                        if any(part.startswith('_') for part in path.relative_to(folder).parts): continue
                        try:
                            st = path.stat()
                            found[path_key(path)] = dict(path=str(path), name=path.name,
                                folder=str(path.parent), modified=st.st_mtime,
                                size=f'{st.st_size / 1024:.0f} KB', format=path.suffix[1:].upper())
                        except OSError: continue
                self._resultsReady.emit(sorted(found.values(), key=lambda i: i['modified'], reverse=True)[:500])
            except OSError as exc:
                self.pipeline.log(f'[WARN] Falha ao listar resultados: {exc}')
                self._resultsReady.emit(list(found.values()))
        threading.Thread(target=scan, name='studio-results', daemon=True).start()

    @Slot(list)
    def _set_results(self, values):
        self._results = values
        self._scanning = False
        self.changed.emit()

    @Slot(str)
    def inspectResult(self, path):
        candidate = Path(path)
        if not candidate.is_file():
            self._notify('Este arquivo não está disponível.')
            return
        self._preview_path = str(candidate.resolve())
        self._preview_is_placeholder = candidate.suffix.lower() not in {'.srt', '.ass', '.vtt'}
        if candidate.name.endswith('.review_required.json'):
            try:
                report=json.loads(candidate.read_text(encoding='utf-8'));self._preview_title=candidate.name
                self._preview='Tradução bloqueada. Use Revisar para conferir o rascunho e retraduzir trechos.';self.changed.emit();return
            except (OSError,ValueError) as exc:self._notify(str(exc));return
        if candidate.suffix.lower() not in {'.srt', '.ass', '.vtt'}:
            self._preview_title = candidate.name
            self._preview = 'Arquivo de vídeo. Use “Abrir arquivo” para assistir no seu reprodutor.'
            self.changed.emit()
            return
        try:
            with candidate.open('r', encoding='utf-8-sig', errors='replace') as f:
                self._preview = f.read(200_000)
            self._preview_title = candidate.name
            report = Path(str(candidate) + '.quality.json')
            if report.is_file():
                quality = json.loads(report.read_text(encoding='utf-8'))
                self._preview_title += f' · {quality.get("needs_review", 0)} bloco(s) sinalizado(s)'
            else:
                audit_path = Path(str(candidate)+'.transcription.json')
                if audit_path.is_file():
                    audit = json.loads(audit_path.read_text(encoding='utf-8'))
                    self._preview_title += f' · áudio {audit.get("audio_stream", "?")} / {audit.get("language", "?")} · {len(audit.get("review_findings", []))} bloco(s) sinalizado(s)'
                    pending=sum(not item.get('accepted',False) and (item.get('kind')=='alignment' or item.get('reason')=='recognition_disagreement')
                                for item in audit.get('retry_audit',[]))
                    if pending:self._preview_title += f' · {pending} reavaliação(ões) pendente(s)'
            self.changed.emit()
        except (OSError, ValueError) as exc: self._notify(f'Não foi possível abrir a prévia: {exc}')

    @Slot(str)
    def openPath(self, path):
        candidate = Path(path).resolve()
        if candidate.exists(): QDesktopServices.openUrl(QUrl.fromLocalFile(str(candidate)))
        else: self._notify('Este arquivo ou pasta não está disponível.')

    @Slot()
    def openOutputs(self):
        path = self.root / 'outputs'
        path.mkdir(parents=True, exist_ok=True)
        self.openPath(str(path))

    @Slot(str)
    def chooseDirectory(self, key):
        if self._busy or key not in ('whisper_out_dir','ollama_out_dir','subs_out_dir','embed_output_dir'): return
        selected = QFileDialog.getExistingDirectory(None, self.translate('Escolher pasta de saída'), str(resolve_dir(self.root, self._settings[key])), options=QFileDialog.Option.DontUseNativeDialog)
        if selected:
            path = Path(selected).resolve()
            try: value = str(path.relative_to(self.root))
            except ValueError: value = str(path)
            self.updateSetting(key, value)

    def shutdown(self):
        self._maintenance.shutdown()
        self._review.shutdown()
        app=QApplication.instance()
        if app:app.removeTranslator(self._qt_translator)
        self.timer.stop()
        if self.monitor: self.monitor.stop()
        if self.pipeline.busy: self.pipeline.cancel()
        def cleanup():
            self._review.join()
            if self.pipeline.thread: self.pipeline.thread.join()
            self.runtime._stop_managed_ollama_server(log_fn=None)
        threading.Thread(target=cleanup, name='studio-shutdown', daemon=False).start()
