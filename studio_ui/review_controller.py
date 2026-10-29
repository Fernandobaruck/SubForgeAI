"""Qt review workflow; disk/model operations keep originals and run off-thread."""
from __future__ import annotations
import json,threading,uuid
from pathlib import Path
from PySide6.QtCore import QObject,Property,Signal,Slot,QTimer
from PySide6.QtWidgets import QFileDialog,QApplication
from pipeline_io import atomic_write_text
from review_workspace import ReviewWorkspace,SubtitleDocument,json_read,digest
from series_registry import SeriesRegistry
from source_selection import validate_options,probe
from .queue_model import EpisodeListModel

FLAGS={'invalid_time':'Tempo inválido','empty':'Bloco vazio','overlap':'Sobreposição para conferir','out_of_order':'Ordem temporal incorreta',
       'reading_speed':'Leitura rápida','long_line':'Linha longa','source_unmatched':'Origem sem correspondência exata','low_word_confidence':'Reconhecimento incerto',
       'low_decoder_confidence':'Reconhecimento incerto','ocr_disagreement':'Divergência de OCR','low_ocr_confidence':'OCR incerto','ocr_uncertain':'OCR incerto',
       'asr_disagreement':'Reconhecimento incerto','source_fragment':'Origem fragmentada','suggested_terminology':'Termo sugerido','romanized_source':'Japonês romanizado','translator_explanation':'Explicação acrescentada','format_mismatch':'Formatação divergente','speaker_boundary':'Separação de falantes','untranslated_english':'Inglês não traduzido','untranslated_romaji':'Japonês romanizado não traduzido','context_entity_leak':'Informação fora da origem','gender_alternatives':'Alternativa de gênero','possessive_shift':'Possessivo divergente','unsupported_company_reference':'Referência empresarial acrescentada','unsupported_show_reference':'Referência a programa acrescentada',
       'not_translated':'Ainda não traduzido','model_rejected':'Sugestão rejeitada pela validação','too_many_lines':'Muitas linhas','added_politeness':'Cortesia acrescentada','terminology':'Terminologia divergente','excessive_expansion':'Expansão para conferir'}

class ReviewController(QObject):
    changed=Signal();opened=Signal();sourceReady=Signal();_done=Signal(object)
    def __init__(self,owner):
        super().__init__(owner);self.owner=owner;self.root=owner.root;self.workspace=ReviewWorkspace(self.root);self.registry=SeriesRegistry(self.root)
        self.document=None;self._rows=[];self._current=0;self._selected=set();self._model=EpisodeListModel(self)
        self._busy=False;self._cancellable=False;self._job='';self._cancel=threading.Event();self._thread=None;self._project='';self._source_info={};self._projects=[]
        self._done.connect(self._finish);self.changed.connect(self._sync);owner.preferencesChanged.connect(self.changed.emit)
        self._draft_timer=QTimer(self);self._draft_timer.setSingleShot(True);self._draft_timer.setInterval(500);self._draft_timer.timeout.connect(self._autosave)
        from .season_controller import SeasonController
        self._season=SeasonController(self)
        from .fansub_controller import FansubController
        self._fansub=FansubController(self)
        self.refreshProjects()
    def _text(self,text):return self.owner.translate(text)
    def _notify(self,text):self.owner._notify(text)
    @Property(QObject,constant=True)
    def fansub(self):return self._fansub
    @Property(QObject,constant=True)
    def season(self):return self._season
    @Property(bool,notify=changed)
    def busy(self):return self._busy
    @Property(str,notify=changed)
    def job(self):return self._text(self._job)
    @Property(bool,notify=changed)
    def loaded(self):return self.document is not None
    @Property(bool,notify=changed)
    def dirty(self):return bool(self.document and self.document.dirty)
    @Property(QObject,constant=True)
    def model(self):return self._model
    @Property(int,notify=changed)
    def currentIndex(self):return self._current
    @Property('QVariantMap',notify=changed)
    def current(self):return self._present(self._rows[self._current]) if self._rows else {'index':-1,'number':0,'time':'','text':'','source':'','flags':[],'flagText':'','approved':False,'proposal':'','sourceVerified':False}
    @Property(str,notify=changed)
    def title(self):return self.document.origin_path.name if self.document else ''
    @Property(str,notify=changed)
    def outputPath(self):return str(self.document.target) if self.document else ''
    @Property(str,notify=changed)
    def sourcePath(self):return self.document.source_path if self.document else ''
    @Property(str,notify=changed)
    def videoPath(self):return self.document.video_path if self.document else ''
    @Property('QVariantList',notify=changed)
    def projects(self):return self._projects
    @Property(str,notify=changed)
    def selectedProject(self):return self._project
    @Property(str,notify=changed)
    def reviewProject(self):return self.document.project if self.document else ''
    @Property('QVariantList',notify=changed)
    def terms(self):return self.registry.terms(self._project) if self._project else []
    @Property('QVariantList',notify=changed)
    def folders(self):return self.registry.folders(self._project) if self._project else []
    @Property('QVariantList',notify=changed)
    def versions(self):
        labels={'original':'Original','edit':'Edição','before_edit':'Antes da edição','restore':'Restauração','independent':'Cópia independente'}
        return [dict(version,reasonLabel=self._text(labels.get(version['reason'],version['reason']))) for version in reversed(self.workspace.versions(self.document))] if self.document else []
    @Property('QVariantMap',notify=changed)
    def sourceInfo(self):return self._source_info
    @Property(int,notify=changed)
    def selectedCount(self):return len(self._selected)
    @Property(str,notify=changed)
    def summary(self):
        return self.owner.formatText('{total} blocos · {pending} pendentes · {approved} aprovados',{'total':len(self._rows),'pending':sum(bool(row['flags']) and not row['approved'] for row in self._rows),'approved':sum(row['approved'] for row in self._rows)})
    def _present(self,row):
        return dict(row,checked=row['index'] in self._selected,flagText=' · '.join(self._text(FLAGS.get(flag,flag)) for flag in row['flags']))
    def _sync(self):self._model.sync([self._present(row) for row in self._rows])
    def _reload_rows(self):
        if self.document:
            style=self.registry.style(self.document.project) if self.document.project else {}
            self.document.line_width=style.get('line_width',42);self.document.max_cps=style.get('max_cps',20)
            self._rows=self.document.rows()
        self.changed.emit()
    def _submit(self,label,work,callback,cancellable=False):
        if self._busy or self.owner._busy:self._notify('Aguarde o processamento atual terminar.');return False
        if hasattr(self.owner.runtime,'configure_resources'):self.owner.runtime.configure_resources(self.owner._settings)
        self._busy=True;self._cancellable=cancellable;self._job=label;self._cancel.clear();self.changed.emit();self.owner.changed.emit()
        def run():
            try:result=work();payload=(callback,result,None)
            except Exception as exc:payload=(callback,None,str(exc))
            self._done.emit(payload)
        self._thread=threading.Thread(target=run,name='studio-review',daemon=False);self._thread.start();return True
    @Slot(object)
    def _finish(self,payload):
        callback,result,error=payload;self._busy=False;self._job=''
        try:
            if error:self._notify(error)
            elif not self._cancel.is_set():callback(result)
        except Exception as exc:self._notify(str(exc))
        self.changed.emit();self.owner.changed.emit()
        if self.owner._closing and not self.owner.busy:self.owner.requestClose()
    def cancel(self):
        if not self._cancellable:
            self._notify('A operação de arquivos terminará antes de fechar.');return
        self._cancel.set()
        if self._busy:self.owner.runtime.kill_all_active_procs()
    def shutdown(self):
        self._fansub.timer.stop();self._draft_timer.stop();self._autosave()
        if self._busy:self.cancel()
    def join(self):
        if self._thread:self._thread.join()
    def _autosave(self):
        if self.document and self.document.dirty:
            try:self.workspace.autosave(self.document)
            except OSError as exc:self._notify(str(exc))
    @Slot()
    def chooseDocument(self):
        path,_=QFileDialog.getOpenFileName(None,self._text('Abrir legenda para revisão'),str(self.root/'outputs'),'SRT / ASS / VTT / JSON (*.srt *.ass *.vtt *.review_required.json)',options=QFileDialog.DontUseNativeDialog)
        if path:self.openDocument(path)
    @Slot(str)
    def openDocument(self,path):
        if self.dirty:self._notify('Salve a revisão antes de abrir outra legenda.');return
        def loaded(result):
            self.document,self._rows=result;self._current=0;self._selected=set();self._reload_rows();self.opened.emit()
        def work():
            doc=self.workspace.open(path);return doc,doc.rows()
        self._submit('Abrindo revisão',work,loaded)
    @Slot(int)
    def select(self,index):
        if 0<=index<len(self._rows):self._current=index;self.changed.emit()
    @Slot(int,bool)
    def toggle(self,index,checked):
        if 0<=index<len(self._rows):
            if checked:self._selected.add(index)
            else:self._selected.discard(index)
            self.changed.emit()
    @Slot(str)
    def editCurrent(self,text):
        if not self.document or self._busy:return
        i=self._current
        if self.document.values[i]==text:return
        self.document.values[i]=text;self.document.approved.discard(i)
        self._rows[i].update(text=text,approved=False)
        # Structural timing flags are invariant while text is edited.
        import subtitle_quality as Q
        flags=[flag for flag in self._rows[i]['flags'] if flag not in ('empty','long_line','reading_speed','too_many_lines')]
        if len(text.replace('\\N','\n').splitlines())>2:flags.append('too_many_lines')
        if not text.strip():flags.append('empty')
        if any(len(Q.plain(line))>getattr(self.document,"line_width",42) for line in text.replace('\\N','\n').splitlines()):flags.append('long_line')
        a,b=self.document.bounds[i]
        if a is not None and b is not None and b>a and len(Q.plain(text))/(b-a)>getattr(self.document,"max_cps",20):flags.append('reading_speed')
        self._rows[i]['flags']=flags;self._draft_timer.start();self.changed.emit()
    @Slot()
    def approve(self):
        if not self.document or self._busy:return
        i=self._current
        if any(flag in self._rows[i]['flags'] for flag in ('empty','invalid_time')):self._notify('Corrija o bloco vazio ou o tempo inválido antes de aprovar.');return
        self.document.approved.add(i);self._rows[i]['approved']=True;self._draft_timer.start();self.changed.emit()
    @Slot(result=bool)
    def save(self):
        if not self.document or self._busy:return False
        try:
            path=self.workspace.save(self.document);self._reload_rows();self.owner.refreshResults();self._notify(self._text('Cópia revisada salva: {path}').format(path=path));return True
        except Exception as exc:self._notify(str(exc));return False
    @Slot(result=bool)
    def saveIndependent(self):
        if not self.document or self._busy:return False
        try:
            path=self.workspace.fork(self.document);self._reload_rows();self.owner.refreshResults();self._notify(self._text('Cópia revisada salva: {path}').format(path=path));return True
        except Exception as exc:self._notify(str(exc));return False

    @Slot(str)
    def restoreVersion(self,identifier):
        if not self.document or self._busy:return
        try:self.workspace.restore(self.document,identifier);self._reload_rows();self.owner.refreshResults()
        except Exception as exc:self._notify(str(exc))
    @Slot()
    def chooseSource(self):
        if not self.document or self._busy:return
        path,_=QFileDialog.getOpenFileName(None,self._text('Escolher legenda original'),str(self.root),'SRT / ASS / VTT (*.srt *.ass *.vtt)',options=QFileDialog.DontUseNativeDialog)
        if path:
            try:self.document.attach_source(path);self.document.metadata_dirty=True;self._reload_rows();self._draft_timer.start()
            except Exception as exc:self._notify(str(exc))
    @Slot()
    def chooseVideo(self):
        if not self.document or self._busy:return
        path,_=QFileDialog.getOpenFileName(None,self._text('Escolher vídeo da revisão'),str(self.root),self._text('Vídeos')+' (*.mkv *.mp4 *.avi *.mov *.webm *.m4v)',options=QFileDialog.DontUseNativeDialog)
        if path:self.document.video_path=path;self.document.audio_stream=None;self.document.metadata_dirty=True;self._draft_timer.start();self.changed.emit()
    @Slot()
    def playCurrent(self,lead=1):
        if not self.document:return
        doc=self.document;start,end=doc.bounds[self._current]
        if start is None or end is None or not doc.video_path or not Path(doc.video_path).is_file():self._notify('Escolha um vídeo e um bloco com tempo válido.');return
        target=self.root/'outputs/studio/previews'/(uuid.uuid4().hex+'.mp4');target.parent.mkdir(parents=True,exist_ok=True)
        def work():
            from whisper_audio import inspect_audio
            try:stream=inspect_audio(doc.video_path,self.root/'tools/ffmpeg/ffprobe.exe',selection=str(doc.audio_stream) if doc.audio_stream is not None else 'auto')
            except ValueError:stream=None
            audio=['-map','0:'+str(stream['index'])] if stream else []
            cmd=[str(self.root/'tools/ffmpeg/ffmpeg.exe'),'-y','-v','error','-ss',str(max(0,start-lead)),'-i',doc.video_path,'-t',str(min(30,max(3,end-start+lead+1))),'-map','0:v:0?',*audio,'-c:v','libx264','-preset','veryfast','-crf','26','-pix_fmt','yuv420p','-c:a','aac',str(target)]
            if self.owner.runtime.run_capture(cmd,self.owner.pipeline.log,cwd=self.root,cancel_event=self._cancel):raise ValueError('Não foi possível criar a prévia do vídeo.')
            if not target.is_file():raise ValueError('A prévia do vídeo não foi criada.')
            return str(target)
        self._submit('Preparando prévia do vídeo',work,self.owner.openPath,True)
    @Slot(str)
    def shortcut(self,action):
        if self.owner.busy or QApplication.activeModalWidget() is not None:return
        actions={'previous':lambda:self.navigate(-1),'next':lambda:self.navigate(1),'approve':self.approveNext,'save':self.save,'play':self.playCurrent,'back':self.playBack}
        if action in actions:actions[action]()
    @Slot()
    def playBack(self):self.playCurrent(5)
    @Slot(int)
    def navigate(self,delta):
        if not self._busy and self.document:self.select(max(0,min(len(self._rows)-1,self._current+delta)))
    @Slot()
    def approveNext(self):
        if not self.document or self._busy:return
        self.approve()
        if self._current in self.document.approved:self.navigate(1)
    @Slot()
    def retranslateSelected(self):
        if not self.document:return
        indices=sorted(self._selected or {self._current});doc=self.document
        if any(not doc.verified[i] for i in indices):self._notify('Associe uma origem com tempos correspondentes antes de retraduzir.');return
        if doc.dirty and not self.save():return
        folder=self.root/'outputs/studio/retranslate'/uuid.uuid4().hex;inputs={}
        for i in indices:
            path=folder/(str(i)+'.srt');atomic_write_text(path,'1\n'+doc.times[i]+'\n'+doc.original_texts[i]+'\n');inputs[str(path.resolve())]=i
            from speech_context import write_context
            context=doc.source_context
            terms={**context.get('confirmed_terms',{}),**(self.registry.confirmed(doc.project) if doc.project else {})}
            write_context(path,context.get('source_file') or doc.source_path,terms,context.get('speech_terms'),context.get('uncertain_ranges'),source_kind='subtitle',series_project=doc.project or context.get('series_project'))
        def work():
            rt=self.owner.runtime
            if not rt._ensure_ollama_ready(log_fn=self.owner.pipeline.log,required_model='translategemma:12b',cancel_event=self._cancel):raise ValueError('Não foi possível preparar o TranslateGemma no Ollama.')
            outputs={}
            def line(text):
                self.owner.pipeline.log(text)
                if text.startswith('[RESULT] '):
                    data=json.loads(text[9:])
                    if data.get('kind')=='translation' and str(Path(data['input']).resolve()) in inputs:outputs[inputs[str(Path(data['input']).resolve())]]=data['output']
            rt.run_capture([rt.runtime_python(),str(rt.OLLAMA_SCRIPT),*inputs,'--outdir',str(folder/'translated'),'--model','translategemma:12b','--review','auto'],line,cwd=self.root,cancel_event=self._cancel)
            import ollama_script as O
            proposals={}
            for i,path in outputs.items():
                if Path(path).is_file():
                    text=O.parse_srt(Path(path).read_text(encoding='utf-8'))[0][2]
                    proposals[i]=text.replace('\n',r'\N') if doc.ext=='.ass' else text
            if not proposals:raise ValueError('Nenhuma sugestão validada foi produzida. Consulte o registro.')
            return proposals
        def accepted(proposals):
            if self.document is doc:
                doc.proposals.update(proposals)
                for i,text in proposals.items():self._rows[i]['proposal']=text
                self.changed.emit();self._notify(self._text('{count} sugestões prontas para conferir.').format(count=len(proposals)))
        self._submit('Retraduzindo seleção',work,accepted,True)
    @Slot()
    def applyProposal(self):
        if self.document and self.document.proposals.get(self._current):self.editCurrent(self.document.proposals[self._current])
    @Slot()
    def rememberCurrent(self):
        if not self.document:return
        doc=self.document;i=self._current
        if not doc.project or not doc.verified[i] or i not in doc.approved:self._notify('Escolha um anime, associe a origem e aprove o bloco antes de memorizar.');return
        try:
            import subtitle_quality as Q
            Q.render_memory(doc.original_texts[i],doc.values[i],ass=doc.ext=='.ass')
            self.registry.remember(doc.project,doc.original_texts[i],doc.values[i]);self._notify('Correção confirmada na memória do anime.')
        except Exception as exc:self._notify(str(exc))
    @Slot()
    def refreshProjects(self):
        try:self._projects=self.registry.projects()
        except (OSError,ValueError) as exc:self._notify(str(exc));self._projects=[]
        if not any(p['id']==self._project for p in self._projects):self._project=''
        self.changed.emit()
    @Slot(str)
    def setProject(self,identifier):self._project=identifier if any(p['id']==identifier for p in self._projects) else '';self.changed.emit()
    @Slot(str)
    def setReviewProject(self,identifier):
        if not self.document or self._busy:return
        if identifier and not any(p['id']==identifier for p in self._projects):return
        self.document.project=identifier;self.document.metadata_dirty=True;self._draft_timer.start();self._reload_rows()
    @Slot(str)
    def createProject(self,name):
        try:self._project=self.registry.create(name);self.refreshProjects()
        except Exception as exc:self._notify(str(exc))
    @Slot(str,str,bool)
    def saveTerm(self,source,target,confirmed):
        if not self._project:self._notify('Escolha um anime.');return
        try:self.registry.set_term(self._project,source,target,confirmed);self.changed.emit()
        except Exception as exc:self._notify(str(exc))
    @Slot(str)
    def removeTerm(self,source):
        try:self.registry.remove_term(self._project,source);self.changed.emit()
        except Exception as exc:self._notify(str(exc))
    @Slot()
    def bindSeason(self):
        if not self._project:self._notify('Escolha um anime.');return
        folder=QFileDialog.getExistingDirectory(None,self._text('Vincular pasta de temporada'),str(self.root),options=QFileDialog.DontUseNativeDialog)
        if folder:
            try:self.registry.bind_folder(self._project,folder);self.changed.emit()
            except Exception as exc:self._notify(str(exc))
    @Slot(str)
    def unbindSeason(self,key):
        try:self.registry.unbind_folder(self._project,key);self.changed.emit()
        except Exception as exc:self._notify(str(exc))
    @Slot()
    def createBackup(self):
        if self.dirty and not self.save():return
        self._submit('Criando backup',self.workspace.backup,lambda path:self._notify(self._text('Backup salvo: {path}').format(path=path)))
    @Slot()
    def chooseRestoreBackup(self):
        if self.dirty:self._notify('Salve a revisão antes de restaurar o backup.');return
        path,_=QFileDialog.getOpenFileName(None,self._text('Restaurar backup do Studio'),str(self.root/'backups/studio'),'ZIP (*.zip)',options=QFileDialog.DontUseNativeDialog)
        if not path:return
        def restored(safety):
            self.owner._settings=self.owner._load_settings();self.owner._apply_ui_preferences();self.owner.preferencesChanged.emit();self.refreshProjects()
            if self.document and self.document.path.is_file():self.document=self.workspace.open(self.document.path);self._reload_rows()
            self._notify(self._text('Backup restaurado. Cópia anterior: {path}').format(path=safety));self.owner.refreshResults()
        self._submit('Restaurando backup',lambda:self.workspace.restore_backup(path),restored)
    @Slot(str)
    def inspectInput(self,identifier):
        item=next((i for i in self.owner._items if i['id']==identifier),None)
        if not item or identifier in self.owner._active_ids:return
        def work():
            path=Path(item['path']);streams=[] if path.suffix.lower() in ('.srt','.ass','.vtt','.sup') else probe(path,self.root)
            options=validate_options(item.get('options'))
            if not options['series_project']:options['series_project']=self.registry.resolve(path)
            return dict(id=identifier,name=item['name'],path=str(path),streams=streams,options=options)
        def ready(info):self._source_info=info;self.changed.emit();self.sourceReady.emit()
        self._submit('Inspecionando faixas',work,ready)
    @Slot(str)
    def chooseInputSubtitle(self,identifier):
        path,_=QFileDialog.getOpenFileName(None,self._text('Escolher legenda original'),str(self.root),'SRT / ASS / VTT / SUP (*.srt *.ass *.vtt *.sup)',options=QFileDialog.DontUseNativeDialog)
        if path and self._source_info.get('id')==identifier:
            self._source_info['options']['source_subtitle']=path;self.changed.emit()
    @Slot(str,'QVariantMap',result=bool)
    def saveInputOptions(self,identifier,options):
        item=next((i for i in self.owner._items if i['id']==identifier),None)
        if not item or identifier in self.owner._active_ids:return False
        try:
            options=validate_options(options)
            if options['source_mode']=='external' and not Path(options['source_subtitle']).is_file():raise ValueError('Selecione um arquivo de legenda válido.')
            if options['audio_stream']!='auto':
                from whisper_audio import language_code
                audio=next((stream for stream in self._source_info.get('streams',[]) if stream['kind']=='audio' and str(stream['index'])==options['audio_stream']),None)
                options['audio_language']=(language_code(audio.get('language')) or 'auto') if audio else 'auto'
                if options['audio_language']=='und':options['audio_language']='auto'
            previous=item.get('options');item['options']=options
            if not self.owner._save_queue():
                if previous is None:item.pop('options',None)
                else:item['options']=previous
                return False
            self.owner.changed.emit();return True
        except Exception as exc:self._notify(str(exc));return False
