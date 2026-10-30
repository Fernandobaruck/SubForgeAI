"""Qt actions for consistency across episodes; preview and selection before writes."""
from __future__ import annotations
import json
from pathlib import Path
from PySide6.QtCore import QObject,Property,Signal,Slot
from PySide6.QtWidgets import QFileDialog
from review_workspace import digest,json_read
from season_tools import STYLE_DEFAULTS,discover,episode_summary,reflow,synced_raw,replace_visible


class SeasonController(QObject):
    changed=Signal()
    def __init__(self,review):
        super().__init__(review);self.review=review;self._docs=[];self._summaries=[];self._hits=[];self._preview=[];self._checked=set();self._folder='';self._issues=[];self._kind='';self._sync_raw='';self._sync_sha=''
        review.changed.connect(self.changed.emit)
    @property
    def owner(self):return self.review.owner
    def notify(self,text):self.review._notify(text)
    def ready(self):return not self.owner.busy
    @Property('QVariantMap',notify=changed)
    def style(self):
        try:return self.review.registry.style(self.review.selectedProject) if self.review.selectedProject else dict(STYLE_DEFAULTS)
        except (OSError,ValueError):return dict(STYLE_DEFAULTS)
    @Property('QVariantList',notify=changed)
    def summaries(self):
        labels={'whisper':'Whisper','embedded':'Legenda embutida','external':'Legenda externa','ocr':'OCR','subtitle':'Legenda','unknown':'Não informada','auto':'Automático','extract':'Extrair legendas'}
        return [dict(row,sourceLabel=self.review._text(labels.get(row.get('source'),row.get('source','')))) for row in self._summaries]
    @Property('QVariantList',notify=changed)
    def hits(self):return self._hits
    @Property('QVariantList',notify=changed)
    def preview(self):return [dict(row,checked=i in self._checked) for i,row in enumerate(self._preview)]
    @Property(str,notify=changed)
    def folder(self):return self._folder
    @Property(str,notify=changed)
    def issues(self):return '\n'.join(self._issues)
    @Property(int,notify=changed)
    def selectedCount(self):return len(self._checked)
    @Property(str,notify=changed)
    def previewKind(self):return self._kind
    @Property('QVariantMap',notify=changed)
    def currentSummary(self):
        doc=self.review.document
        if not doc:return {}
        try:
            style=self.review.registry.style(doc.project) if doc.project else {}
            return episode_summary(doc,style)
        except (OSError,ValueError):return {}
    @Slot('QVariantMap')
    def saveStyle(self,value):
        if not self.ready():return
        try:
            if not self.review.selectedProject:raise ValueError('Escolha um anime.')
            self.review.registry.set_style(self.review.selectedProject,dict(value))
            if self.review.document and self.review.document.project==self.review.selectedProject:self.review._reload_rows()
            else:self.review.changed.emit()
            self.notify('Guia de estilo salvo. Vale para novas traduções e retraduções.')
        except Exception as exc:self.notify(str(exc))
    @Slot()
    def chooseFolder(self):
        if not self.ready():return
        path=QFileDialog.getExistingDirectory(None,self.review._text('Escolher pasta de legendas'),str(self.review.root/'outputs'))
        if path:self.loadFolder(path)
    @Slot(str)
    def loadFolder(self,path):
        self._load([path],str(path))
    @Slot()
    def loadProject(self):
        if not self.review.selectedProject:self.notify('Escolha um anime.');return
        folders=[item['path'] for item in self.review.registry.folders(self.review.selectedProject)]
        from .pipeline import resolve_dir
        folders.extend([self.review.workspace.reviewed,resolve_dir(self.review.root,self.owner._settings['ollama_out_dir']),resolve_dir(self.review.root,self.owner._settings['whisper_out_dir'])])
        self._load(folders,self.review._text('Temporadas do anime selecionado'),self.review.selectedProject)
    def _load(self,folders,label,project_filter=''):
        if not self.ready():return
        if self.review.dirty and not self.review.save():return
        project=self.review.selectedProject
        def work():
            docs=[];summaries=[];issues=[];seen=set()
            reports={}
            for path in sorted((self.review.root/'outputs/studio/episode_reports').glob('*.json'),key=lambda p:p.stat().st_mtime):
                try:
                    report=json_read(path)
                    for output in report.get('outputs',[]):reports[str(Path(output).resolve()).casefold()]=report
                except (ValueError,OSError):continue
            for path in discover(folders):
                try:
                    doc=self.review.workspace.open(path)
                    associated=doc.project or self.review.registry.resolve(doc.origin_path)
                    if project_filter and associated!=project_filter:continue
                    if project_filter and not doc.project:doc.project=project_filter;doc.metadata_dirty=True
                    if doc.identity in seen:continue
                    seen.add(doc.identity);docs.append(doc)
                    style=self.review.registry.style(doc.project or project) if doc.project or project else {}
                    row=episode_summary(doc,style);report=reports.get(str(doc.origin_path).casefold(),{})
                    row.update(seconds=report.get('elapsed_seconds'),preparationSeconds=report.get('preparation_batch_seconds'),state=report.get('state',''),error=report.get('error',''),source=report.get('source_mode') or row['source'])
                    summaries.append(row)
                except Exception as exc:issues.append(path.name+': '+str(exc))
            # Failures with no subtitle output also belong in the episode summary.
            latest={}
            for path in sorted((self.review.root/'outputs/studio/episode_reports').glob('*.json'),key=lambda p:p.stat().st_mtime):
                try:
                    record=json_read(path);latest[record.get('input','')]=record
                except (OSError,ValueError):continue
            for report in latest.values():
                try:
                    source=Path(report.get('input',''))
                    in_scope=report.get('project')==project_filter if project_filter else any(source.resolve().is_relative_to(Path(f).resolve()) for f in folders if Path(f).is_dir())
                    if report.get('state') in ('Erro','Interrompido') and in_scope:summaries.append(dict(file=source.name,path='',total=0,pending=0,approved=0,fast=0,long=0,maxCps=0,source=report.get('source_mode','auto'),seconds=report.get('elapsed_seconds'),preparationSeconds=report.get('preparation_batch_seconds'),state=report['state'],error=report.get('error','')))
                except (OSError,ValueError):continue
            return docs,summaries,issues
        def done(result):
            self._docs,self._summaries,self._issues=result;self._folder=label;self._hits=[];self._preview=[];self._checked=set();self.changed.emit()
        self.review._submit('Analisando temporada',work,done)
    @Slot(str,bool)
    def search(self,query,case_sensitive=False):
        if not self.ready():return
        query=query.strip();self._hits=[]
        if not query:self.changed.emit();return
        needle=query if case_sensitive else query.casefold()
        for doc in self._docs:
            for i,(text,source) in enumerate(zip(doc.values,doc.original_texts)):
                hay=text+'\n'+source
                if needle in (hay if case_sensitive else hay.casefold()):
                    self._hits.append(dict(path=str(doc.path),file=doc.origin_path.name,index=i,number=i+1,time=doc.times[i],source=source,text=text))
                    if len(self._hits)>=1000:self.notify('Busca limitada aos primeiros 1000 resultados. Refine o termo.');self.changed.emit();return
        self.changed.emit()
    @Slot(str,int)
    def openHit(self,path,index):
        if not self.ready():return
        self.review.openDocument(path)
        # _finish invokes loaded then emits changed; select after the document is ready.
        def select():
            self.review.select(index);self.review.opened.disconnect(select)
        if self.review.busy:self.review.opened.connect(select)
    def _make_preview(self,kind,docs,transform):
        if not self.ready():return
        if self.review.dirty and not self.review.save():return
        self._preview=[];self._checked=set();self._kind=kind;self.changed.emit()
        rows=[]
        try:
            for doc in docs:
                frozen=digest(doc.render().encode())
                for i,text in enumerate(doc.values):
                    after=transform(doc,text,i)
                    if after!=text:rows.append(dict(path=str(doc.path),file=doc.origin_path.name,index=i,number=i+1,time=doc.times[i],before=text,after=after,document_sha=frozen,loaded_sha=doc.loaded_sha))
            if len(rows)>5000:raise ValueError('Prévia muito grande: selecione uma pasta menor.')
            self._preview=rows;self._kind=kind;self._checked=set();self.changed.emit()
        except Exception as exc:self.notify(str(exc))
    @Slot(str,str,bool,bool)
    def previewReplace(self,old,new,case_sensitive,whole):
        self._make_preview('replace',self._docs,lambda doc,text,index:replace_visible(text,old,new,case_sensitive,whole))
    @Slot()
    def previewWrap(self):
        doc=self.review.document
        if not doc:return
        style=self.review.registry.style(doc.project) if doc.project else STYLE_DEFAULTS
        self._make_preview('wrap',[doc],lambda doc,text,index:text if doc.annotations.get(index,{}).get('kind','dialogue')!='dialogue' or doc.annotations.get(index,{}).get('simultaneous') else reflow(text,style['line_width'],doc.ext=='.ass'))
    @Slot(int,bool)
    def check(self,index,checked):
        if 0<=index<len(self._preview):
            if checked:self._checked.add(index)
            else:self._checked.discard(index)
            self.changed.emit()
    @Slot(bool)
    def checkAll(self,checked):self._checked=set(range(len(self._preview))) if checked else set();self.changed.emit()
    @Slot()
    def apply(self):
        if not self.ready() or not self._checked:return
        if self.review.dirty:self.notify('Salve a revisão antes de aplicar a prévia.');return
        selected=[self._preview[i] for i in sorted(self._checked)]
        def work():
            groups={};prepared=[]
            for row in selected:groups.setdefault(row['path'],[]).append(row)
            for path,rows in groups.items():
                doc=self.review.workspace.open(path)
                if doc.loaded_sha!=rows[0]['loaded_sha'] or digest(doc.render().encode())!=rows[0]['document_sha']:raise ValueError('A legenda mudou desde a prévia. Gere a prévia novamente.')
                for row in rows:
                    if doc.values[row['index']]!=row['before']:raise ValueError('A legenda mudou desde a prévia. Gere a prévia novamente.')
                    doc.values[row['index']]=row['after'];doc.approved.discard(row['index'])
                prepared.append(doc)
            saved=[];errors=[]
            for doc in prepared:
                try:saved.append(str(self.review.workspace.save(doc)))
                except Exception as exc:errors.append(doc.origin_path.name+': '+str(exc))
            return saved,errors
        def done(result):
            saved,errors=result;self._issues=errors;self._preview=[];self._checked=set();self._hits=[]
            doc=self.review.document
            if doc and str(doc.target) in saved:self.review.document=self.review.workspace.open(doc.target);self.review._reload_rows()
            self.owner.refreshResults();self.notify(self.review._text('{count} cópias revisadas salvas.').format(count=len(saved)));self.changed.emit()
            # Reload summaries from those exact saved copies, without changing the scope.
            for i,old in enumerate(self._docs):
                if str(old.target) in saved:self._docs[i]=self.review.workspace.open(old.target)
            existing={row['path']:row for row in self._summaries}
            self._summaries=[dict(existing.get(str(d.origin_path),existing.get(str(d.path),{})),**episode_summary(d,self.review.registry.style(d.project) if d.project else {})) for d in self._docs];self.changed.emit()
        self.review._submit('Aplicando correções selecionadas',work,done)
    @Slot(float,float)
    def previewSync(self,offset,scale):
        if not self.ready() or not self.review.document:return
        self._preview=[];self._checked=set();self._kind='';self._sync_raw='';self.changed.emit()
        doc=self.review.document
        try:
            self._sync_raw=synced_raw(doc,offset,scale);self._sync_sha=digest(doc.render().encode());self._kind='sync'
            from review_workspace import _parse_only
            parsed=_parse_only(doc.path,self._sync_raw.encode());self._preview=[dict(number=i+1,file=doc.origin_path.name,index=i,before=doc.times[i],after=str(parsed.bounds[i][0])+' → '+str(parsed.bounds[i][1])) for i in sorted({0,len(doc.values)-1})];self._checked=set();self.changed.emit()
        except Exception as exc:self.notify(str(exc))
    @Slot()
    def applySync(self):
        if not self.ready() or self._kind!='sync' or not self.review.document:return
        doc=self.review.document
        try:
            if digest(doc.render().encode())!=self._sync_sha:raise ValueError('A legenda mudou desde a prévia. Gere a prévia novamente.')
            doc.set_raw(self._sync_raw);doc.approved=set();self.review._reload_rows();self.review._draft_timer.start();self._preview=[];self._kind='';self.changed.emit()
        except Exception as exc:self.notify(str(exc))
