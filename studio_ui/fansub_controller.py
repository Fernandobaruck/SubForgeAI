"""Fansub review, reusable ASS presets, queue organization and estimates."""
from __future__ import annotations
import json,time,uuid,shutil
from pathlib import Path
from PySide6.QtCore import QObject,Property,Signal,Slot,QTimer,QUrl
from PySide6.QtWidgets import QFileDialog
from fansub_tools import suggest,render_ass,validate_preset,PRESET_DEFAULTS,KINDS,organize,estimate
from review_workspace import json_read,digest,atomic_bytes
from pipeline_io import atomic_write_text,reserve_output,staged_output,directory_lock


class FansubController(QObject):
    changed=Signal()
    def __init__(self,review):
        super().__init__(review);self.review=review;self._preset=dict(PRESET_DEFAULTS);self._profile='';self._organization={'rows':[],'missing':[]};self._image='';self._video='';self._reports=[];self._report_time=0
        review.changed.connect(self.changed.emit);review.owner.changed.connect(self.changed.emit)
        self.timer=QTimer(self);self.timer.setInterval(5000);self.timer.timeout.connect(self.changed.emit);self.timer.start()
    def text(self,value):return self.review._text(value)
    def notify(self,value):self.review._notify(value)
    def ready(self):return not self.review.owner.busy
    @Property('QVariantMap',notify=changed)
    def preset(self):return self._preset
    @Property('QVariantList',notify=changed)
    def cues(self):
        if not self.review.document:return []
        kinds={'dialogue':'Diálogo','music':'Música','sign':'Placa'};reasons={'music_marker':'Marcador de música','position_or_style':'Posição ou estilo','':'Sem sugestão automática'}
        return [dict(row,checked=row['index'] in self.review._selected,kindLabel=self.text(kinds[row['kind']]),suggestionLabel=self.text(kinds[row['suggestedKind']]),reasonLabel=self.text(reasons[row['reason']])) for row in suggest(self.review.document)]
    @Property(str,notify=changed)
    def previewImage(self):return QUrl.fromLocalFile(self._image).toString() if self._image else ''
    @Property(str,notify=changed)
    def previewVideo(self):return self._video
    @Property('QVariantMap',notify=changed)
    def organization(self):return self._organization
    def _profile_path(self):
        project=self.review.selectedProject
        if project:
            self.review.registry._id(project);return self.review.registry.base/project/'export_presets.json'
        return self.review.root/'export_presets/global.json'
    @Property('QVariantList',notify=changed)
    def profiles(self):
        try:
            data=json_read(self._profile_path(),[])
            if not isinstance(data,list):return []
            return [dict(name=p['name'],settings=validate_preset(p['settings'])) for p in data if isinstance(p,dict) and isinstance(p.get('name'),str)]
        except (ValueError,OSError):return []
    @Property('QVariantMap',notify=changed)
    def queueStats(self):
        if time.monotonic()-self._report_time>5:
            self._report_time=time.monotonic();self._reports=[]
            paths=sorted((self.review.root/'outputs/studio/episode_reports').glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:200]
            for path in reversed(paths):
                try:self._reports.append(json_read(path))
                except (OSError,ValueError):continue
        owner=self.review.owner;result=estimate(owner._items,self._reports,owner._active_settings if owner._busy else owner._settings)
        from .pipeline import resolve_dir
        disks=[];seen=set()
        for key in ('ollama_out_dir','whisper_out_dir','subs_out_dir','embed_output_dir'):
            if key=='embed_output_dir' and not owner._settings.get('embed_enabled'):continue
            path=resolve_dir(self.review.root,owner._settings[key]);existing=path
            while not existing.exists() and existing!=existing.parent:existing=existing.parent
            try:
                free=shutil.disk_usage(existing).free
                if str(path).casefold() not in seen:disks.append(dict(path=str(path),freeBytes=free));seen.add(str(path).casefold())
            except OSError:continue
        result['disks']=disks
        return result
    @Slot('QVariantMap',result=bool)
    def setPreset(self,value):
        if not self.ready():return False
        try:self._preset=validate_preset(dict(value));self._image='';self._video='';self.changed.emit();return True
        except Exception as exc:self.notify(str(exc));return False
    @Slot(str)
    def saveProfile(self,name):
        if not self.ready():return
        try:
            name=name.strip()
            if not name or len(name)>80:raise ValueError('Informe um nome de padrão com até 80 caracteres.')
            path=self._profile_path()
            with directory_lock(path.parent):
                profiles=[p for p in self.profiles if p['name'].casefold()!=name.casefold()];profiles.append(dict(name=name,settings=self._preset));atomic_write_text(path,json.dumps(profiles,ensure_ascii=False,indent=2))
            self.changed.emit();self.notify('Padrão de exportação salvo.')
        except Exception as exc:self.notify(str(exc))
    @Slot(str)
    def loadProfile(self,name):
        if not self.ready():return
        profile=next((p for p in self.profiles if p['name']==name),None)
        if profile:self._preset=dict(profile['settings']);self._image='';self._video='';self.changed.emit()
    @Slot(str)
    def removeProfile(self,name):
        if not self.ready():return
        try:
            path=self._profile_path()
            with directory_lock(path.parent):atomic_write_text(path,json.dumps([p for p in self.profiles if p['name']!=name],ensure_ascii=False,indent=2))
            self.changed.emit()
        except Exception as exc:self.notify(str(exc))
    @Slot(str,bool)
    def classify(self,kind,simultaneous):
        if not self.ready() or not self.review.document or kind not in KINDS:return
        doc=self.review.document
        for index in self.review._selected or {self.review._current}:
            doc.annotations[index]=dict(kind=kind,simultaneous=bool(simultaneous));doc.approved.discard(index)
        self.review._reload_rows();self.review._draft_timer.start()
    @Slot(int)
    def acceptSuggestion(self,index):
        if not self.ready() or not self.review.document:return
        doc=self.review.document
        if not 0<=index<len(doc.values):return
        row=suggest(doc)[index];doc.annotations[index]=dict(kind=row['suggestedKind'],simultaneous=doc.annotations.get(index,{}).get('simultaneous',False));doc.approved.discard(index);self.review._reload_rows();self.review._draft_timer.start()
    @Slot()
    def exportAss(self):
        if not self.ready() or not self.review.document:return
        doc=self.review.document;preset=dict(self._preset)
        def work():
            content=render_ass(doc,preset);folder=self.review.root/'outputs/studio/exports';folder.mkdir(parents=True,exist_ok=True)
            with reserve_output(folder/(doc.origin_path.stem[:130]+'.ass')) as target:
                with staged_output(target) as temporary:temporary.write_text(content,encoding='utf-8-sig')
                from speech_context import write_context
                write_context(target,doc.video_path or doc.origin_path,doc.source_context.get('confirmed_terms',{}),source_kind='subtitle',series_project=doc.project or None)
                atomic_write_text(Path(str(target)+'.export.json'),json.dumps(dict(source=str(doc.origin_path),source_sha=digest(doc.render().encode()),preset=preset,annotations=doc.annotations,created=time.strftime('%Y-%m-%d %H:%M:%S')),ensure_ascii=False,indent=2))
            return str(target)
        def done(path):self.review.owner.refreshResults();self.notify(self.text('ASS exportado: {path}').format(path=path))
        self.review._submit('Exportando ASS',work,done)
    @Slot()
    def previewAss(self):
        if not self.ready() or not self.review.document:return
        doc=self.review.document
        if not doc.video_path or not Path(doc.video_path).is_file():self.notify('Associe um vídeo antes de gerar a prévia ASS.');return
        start,end=doc.bounds[self.review._current]
        if start is None or end is None or end<=start:self.notify('Escolha um bloco com tempo válido.');return
        folder=self.review.root/'outputs/studio/previews'/uuid.uuid4().hex;folder.mkdir(parents=True,exist_ok=True);preset=dict(self._preset);self._image='';self._video='';self.changed.emit()
        def work():
            # Fixed relative subtitle name avoids drive-letter/filter escaping and injection.
            content=render_ass(doc,preset);(folder/'preview.ass').write_text(content,encoding='utf-8-sig')
            rt=self.review.owner.runtime;ffmpeg=str(self.review.root/'tools/ffmpeg/ffmpeg.exe');cancel=self.review._cancel
            from whisper_audio import inspect_audio
            try:audio=inspect_audio(doc.video_path,self.review.root/'tools/ffmpeg/ffprobe.exe',selection=str(doc.audio_stream) if doc.audio_stream is not None else 'auto')
            except ValueError:audio=None
            begin=max(0,start-.5);duration=min(15,max(3,end-start+1))
            # Restore the original timeline for libass after accurate input seeking.
            cmd=[ffmpeg,'-y','-v','error','-ss',str(begin),'-i',doc.video_path,'-t',str(duration),'-map','0:v:0']
            if audio:cmd+=['-map','0:'+str(audio['index'])]
            cmd+=['-vf',f'setpts=PTS+{begin}/TB,ass=preview.ass,setpts=PTS-STARTPTS','-c:v','libx264','-preset','veryfast','-crf','23','-pix_fmt','yuv420p','-c:a','aac',str(folder/'preview.mp4')]
            if rt.run_capture(cmd,self.review.owner.pipeline.log,cwd=folder,cancel_event=cancel):raise ValueError('Não foi possível renderizar a prévia ASS.')
            cmd=[ffmpeg,'-y','-v','error','-ss',str(min(duration-.1,max(.05,start-begin+(end-start)/2))),'-i',str(folder/'preview.mp4'),'-frames:v','1',str(folder/'preview.png')]
            if rt.run_capture(cmd,self.review.owner.pipeline.log,cwd=folder,cancel_event=cancel):raise ValueError('Não foi possível renderizar a prévia ASS.')
            return str(folder/'preview.png'),str(folder/'preview.mp4')
        def done(result):self._image,self._video=result;self.changed.emit()
        self.review._submit('Renderizando prévia ASS',work,done,True)
    @Slot()
    def playPreview(self):
        if self._video:self.review.owner.openPath(self._video)
    @Slot(str,int)
    def inspectSeason(self,path,expected_end):
        if not self.ready():return
        from .pipeline import MEDIA,SUBTITLES
        def work():
            folder=Path(path)
            if not folder.is_dir():raise ValueError('Selecione uma pasta de temporada válida.')
            paths=[p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in MEDIA|SUBTITLES]
            if len(paths)>2000:raise ValueError('Selecione uma pasta com até 2000 arquivos de mídia e legendas.')
            return organize(paths,expected_end)
        def done(result):self._organization=result;self.changed.emit()
        self.review._submit('Organizando temporada',work,done)
    @Slot(int)
    def chooseSeason(self,expected_end):
        if not self.ready():return
        folder=QFileDialog.getExistingDirectory(None,self.text('Escolher pasta da temporada'),str(self.review.root),options=QFileDialog.DontUseNativeDialog)
        if folder:self.inspectSeason(folder,expected_end)
    @Slot()
    def addOrganized(self):
        if self.ready():self.review.owner.addFiles([row['path'] for row in self._organization['rows']])
    @Slot()
    def sortQueue(self):
        if not self.ready():return
        owner=self.review.owner;previous=list(owner._items);pending=[i for i in previous if i.get('state')!='Concluído'];rows=organize([i['path'] for i in pending])['rows'];order={r['path']:i for i,r in enumerate(rows)};ordered=iter(sorted(pending,key=lambda i:order[i['path']]))
        owner._items=[i if i.get('state')=='Concluído' else next(ordered) for i in previous]
        if not owner._save_queue():owner._items=previous;return
        owner.changed.emit();self.changed.emit()
