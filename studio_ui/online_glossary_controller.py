"""Review-before-import online glossaries and explicit browser-based contributions."""
import json
import re
from datetime import datetime, timezone
from urllib.parse import urlencode
from PySide6.QtCore import QObject, Property, Signal, Slot, QUrl
from PySide6.QtGui import QDesktopServices
from .online_glossary import Store, preview, fingerprint, apply, text
from release_info import REPOSITORY


class OnlineGlossaryController(QObject):
    changed = Signal()
    suggestionReady = Signal(str)
    def __init__(self, review):
        super().__init__(review)
        self.review = review; self.store = Store(review.root)
        self._catalog, self._stamp = self.store.cached_catalog()
        self._query = ''; self._rows = []; self._selected = set(); self._entry = None
        self._project = review._project; self._expected = ''; self._status = 'Consulte o catálogo quando desejar. Nenhuma consulta é automática.'
        self._share = set(); self._share_expected=''; self._share_language='en'; self._ai = ''; self._history_text = ''
        review.changed.connect(self._project_changed)
        review.owner.preferencesChanged.connect(self.changed.emit)

    def tr(self, value): return self.review.owner.translate(value)
    def _project_changed(self):
        if self._project != self.review._project:
            self._project = self.review._project; self._rows = []; self._selected.clear(); self._entry = None; self._share.clear(); self._ai = ''; self._history_text = ''
            self.suggestionReady.emit('')
            self.changed.emit()
        else:self.changed.emit()

    @Property('QVariantList', notify=changed)
    def catalog(self):
        return [dict(row) for row in self._catalog if self._query.casefold() in (row['title']+' '+row['description']).casefold()]
    @Property('QVariantList', notify=changed)
    def rows(self):
        labels = {'new':'Novo: será importado como sugestão', 'same':'Já existe no glossário local', 'conflict':'Conflito: tradução local preservada'}
        return [dict(row, index=i, checked=i in self._selected, label=self.tr(labels[row['status']])) for i, row in enumerate(self._rows)]
    @Property(str, notify=changed)
    def status(self): return self.tr(self._status)
    @Property(str, notify=changed)
    def stamp(self): return str(self._stamp)
    @Property(str, notify=changed)
    def title(self): return self._entry['title'] if self._entry else ''
    @Property(int, notify=changed)
    def selectedCount(self): return len(self._selected)
    @Property(str, notify=changed)
    def aiSuggestion(self): return self._ai
    @Property(str, notify=changed)
    def shareLanguage(self): return self._share_language
    @Slot(str)
    def setShareLanguage(self,value):
        if value in ('en','ja'):self._share_language=value;self.changed.emit()
    @Property(str, notify=changed)
    def historyText(self): return self._history_text
    @Property('QVariantList', notify=changed)
    def shareRows(self):
        return [dict(row, index=i, checked=row['source'] in self._share) for i,row in enumerate(self.review.terms) if row['confirmed']]
    @Property(str, notify=changed)
    def contribution(self):
        if not self._project: return ''
        local=self.review.terms
        if fingerprint(local)!=self._share_expected:return ''
        selected = [dict(source=row['source'],target=row['target']) for row in local if row['confirmed'] and row['source'] in self._share]
        if not selected: return ''
        name = next(p['name'] for p in self.review.projects if p['id']==self._project)
        return json.dumps(dict(anime=name,source_language=self._share_language,target_language='pt-BR',terms=selected),ensure_ascii=False,indent=2)
    @Slot(str)
    def search(self, value): self._query=value[:160]; self.changed.emit()
    @Slot()
    def refresh(self):
        def done(result):
            self._catalog,self._stamp,offline=result
            if self._entry and not any(row['id']==self._entry['id'] and row['sha256']==self._entry['sha256'] for row in self._catalog):
                self._entry=None;self._rows=[];self._selected.clear()
            self._status='Consulta indisponível: exibindo o catálogo salvo.' if offline else 'Catálogo atualizado. Escolha um glossário para conferir.'
            self.changed.emit()
        self.review._submit('Consultando glossários online',lambda:self.store.refresh(self.review._cancel),done,True)
    @Slot(str)
    def load(self, identifier):
        entry=next((row for row in self._catalog if row['id']==identifier),None)
        if not entry or not self._project:return
        project=self._project
        def done(result):
            if self.review._project!=project:return
            local=self.review.registry.terms(project)
            self._rows=preview(local,result[0]);self._expected=fingerprint(local);self._selected.clear();self._entry=entry
            self._status='Consulta indisponível: prévia recuperada do cache.' if result[1] else 'Confira e selecione os termos. Nenhum termo foi importado ainda.'
            self.changed.emit()
        self.review._submit('Baixando glossário para prévia',lambda:self.store.load(entry,self.review._cancel),done,True)
    @Slot(int,bool)
    def select(self,index,checked):
        if self.review.owner.busy or not 0<=index<len(self._rows) or not self._rows[index]['eligible']:return
        if checked:self._selected.add(index)
        else:self._selected.discard(index)
        self.changed.emit()
    @Slot()
    def selectNew(self):
        if self.review.owner.busy:return
        self._selected={i for i,row in enumerate(self._rows) if row['eligible']};self.changed.emit()
    @Slot()
    def importSelected(self):
        if self.review.owner.busy or not self._entry or not self._project:return
        try:
            incoming=[dict(source=row['source'],target=row['target']) for row in self._rows]
            origin=dict(collection=self._entry['id'],revision=self._entry['revision'],sha256=self._entry['sha256'],imported_at=datetime.now(timezone.utc).isoformat(timespec='seconds'))
            apply(self.review.registry,self._project,incoming,self._selected,self._expected,origin)
            self._rows=preview(self.review.registry.terms(self._project),incoming);self._selected.clear()
            self._expected=fingerprint(self.review.registry.terms(self._project));self._status='Sugestões importadas. Confirme os termos na aba Animes para usá-los na tradução.'
            self.review.changed.emit();self.changed.emit()
        except Exception as exc:self.review._notify(str(exc))
    @Slot(str,bool)
    def selectShare(self,source,checked):
        local=self.review.terms;expected=fingerprint(local)
        if expected!=self._share_expected:self._share.clear()
        self._share_expected=expected
        if checked and any(row['source']==source and row['confirmed'] for row in local):self._share.add(source)
        else:self._share.discard(source)
        self.changed.emit()
    @Slot()
    def contribute(self):
        value=self.contribution
        if not value:
            if self._share:self.review._notify('O glossário local mudou. Atualize a seleção antes de compartilhar.')
            return
        if len(value)>40000:
            self.review._notify('Selecione menos termos para abrir a contribuição no navegador.');return
        # Only explicitly selected terms prefill the browser form. Submission
        # remains a separate human action in GitHub, never an automatic API POST.
        fields=dict(template='glossary.yml',title='[Glossário] '+next(p['name'] for p in self.review.projects if p['id']==self._project),terms=value)
        query=urlencode(fields)
        if len(query)>1800:
            fields.pop('terms');query=urlencode(fields)
            self.review._notify('Para propostas grandes, copie a proposta e cole no campo Termos do GitHub.')
        QDesktopServices.openUrl(QUrl('https://github.com/'+REPOSITORY+'/issues/new?'+query))
    @Slot()
    def copyContribution(self):
        if self.contribution:
            from PySide6.QtGui import QGuiApplication
            QGuiApplication.clipboard().setText(self.contribution)
    @Slot()
    def remoteHistory(self):
        if self._entry:QDesktopServices.openUrl(QUrl('https://github.com/'+REPOSITORY+'/commits/main/community/glossary/'+self._entry['id']+'.json'))
    @Slot(str,str)
    def saveSuggestion(self, source, target):
        if self.review.owner.busy or not self._project:return
        try:
            source,target=text(source),text(target)
            if any(row['source'].casefold()==source.casefold() for row in self.review.terms):
                raise ValueError('Este termo já existe. Edite-o na aba Animes para resolver a diferença.')
            self.review.registry.set_term(self._project,source,target,False);self.review.changed.emit()
        except Exception as exc:self.review._notify(str(exc))
    @Slot()
    def localHistory(self):
        if not self._project:return
        folder=self.review.registry.base/self._project/'history'
        result=[]
        for path in sorted(folder.glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True):
            if not re.fullmatch('[a-f0-9]{16}.json',path.name) or path.stat().st_size>2*1024*1024:continue
            try:
                rows=json.loads(path.read_text(encoding='utf-8-sig'))
                if not isinstance(rows,list):continue
                result.append(datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec='seconds')+' · '+path.stem+'\n'+'\n'.join(row['source']+' → '+row['target'] for row in rows if isinstance(row,dict) and isinstance(row.get('source'),str) and isinstance(row.get('target'),str)))
                if len(result)==10:break
            except (OSError,ValueError,KeyError):continue
        self._history_text='\n\n'.join(result);self.changed.emit()
    @Slot(str,str)
    def suggest(self,source,language):
        if not self._project or language not in ('en','ja'):return
        try:source=text(source)
        except ValueError as exc:self.review._notify(str(exc));return
        existing=next((row for row in self.review.terms if row['source'].casefold()==source.casefold() and row['confirmed']),None)
        if existing:
            self._ai=existing['target'];self.suggestionReady.emit(self._ai);self.changed.emit()
            self.review._notify('Este termo já tem tradução confirmada. A versão local foi preservada.');return
        self._ai='';self.suggestionReady.emit('');self.changed.emit();project=self._project
        def work():
            from .glossary_ai import suggest
            runtime=self.review.owner.runtime
            if not runtime._ensure_ollama_ready(required_model='translategemma:12b',cancel_event=self.review._cancel):
                if self.review._cancel.is_set():raise ValueError('Consulta interrompida.')
                raise ValueError('Prepare o TranslateGemma antes de pedir sugestões.')
            return suggest(runtime.processes.OLLAMA_BASE_URL,source,language,self.review._cancel)
        def done(value):
            if self.review._project==project:self._ai=value;self.suggestionReady.emit(value);self.changed.emit()
        self.review._submit('Sugerindo termo com IA local',work,done,True)
