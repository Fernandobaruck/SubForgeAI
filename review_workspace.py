"""Safe subtitle editing, technical triage, version history and scoped backups."""
from __future__ import annotations
from studio_ui.output_layout import sidecar_path
import hashlib,json,re,time,uuid,zipfile,os,tempfile
from pathlib import Path,PurePosixPath
from pipeline_io import atomic_write_text,staged_output,directory_lock

TEXT_EXTENSIONS={'.srt','.ass','.vtt'}
MEDIA_EXTENSIONS={'.mkv','.mp4','.avi','.mov','.webm','.m4v','.mpg','.mpeg','.ts','.m2ts','.mp3','.wav','.flac','.m4a','.aac','.ogg'}


def digest(data):return hashlib.sha256(data).hexdigest()

def decode(data):
    if data.startswith((b'\xff\xfe',b'\xfe\xff')):return data.decode('utf-16')
    try:return data.decode('utf-8-sig')
    except UnicodeDecodeError:return data.decode('cp1252')


def json_read(path,default=None):
    path=Path(path)
    return json.loads(path.read_text(encoding='utf-8-sig')) if path.is_file() else ({} if default is None else default)


def atomic_bytes(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.review-write-',dir=str(path.parent));temporary=Path(name)
    try:
        with os.fdopen(fd,'wb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:temporary.unlink(missing_ok=True)


def seconds(stamp):
    if not re.fullmatch(r'(?:\d+:)?\d{2}:\d{2}[.,]\d{2,3}',stamp.strip()):return None
    parts=stamp.replace(',','.').split(':')
    if any(float(value)>=60 for value in parts[-2:]):return None
    return sum(float(value)*60**i for i,value in enumerate(reversed(parts)))


def transaction(root,files):
    """Publish a small set with rollback on write failure; paths stay in root."""
    root=Path(root).resolve();previous={};applied=[]
    for path,data in files.items():
        path=Path(path).resolve()
        if not path.is_relative_to(root):raise ValueError('Destino fora da pasta do projeto.')
        previous[path]=path.read_bytes() if path.is_file() else None
    try:
        for path,data in files.items():
            path=Path(path).resolve();atomic_bytes(path,data);applied.append(path)
    except Exception:
        failures=[]
        for path in reversed(applied):
            try:
                if previous[path] is None:path.unlink(missing_ok=True)
                else:atomic_bytes(path,previous[path])
            except OSError as exc:failures.append(str(exc))
        if failures:raise RuntimeError('Falha ao recuperar arquivos: '+'; '.join(failures))
        raise


def ass_times(raw):
    fields=['layer','start','end','style','name','marginl','marginr','marginv','effect','text'];inside=False;times=[]
    for line in raw.splitlines():
        line=line.strip()
        if line.startswith('['):inside=line.casefold()=='[events]'
        elif inside and line.casefold().startswith('format:'):fields=[part.strip().casefold() for part in line.split(':',1)[1].split(',')]
        elif inside and re.match(r'Dialogue\s*:',line,re.I):
            payload=line.split(':',1)[1].lstrip();index=fields.index('text');front=payload.split(',',index);remaining=len(fields)-index-1
            tail=front[-1].rsplit(',',remaining) if remaining else [front[-1]]
            values=front[:-1]+tail
            try:times.append(values[fields.index('start')].strip()+' --> '+values[fields.index('end')].strip())
            except IndexError:times.append('')
    return times


class SubtitleDocument:
    def __init__(self,path):
        import ollama_script as O
        self.path=Path(path).resolve();self.ext=self.path.suffix.lower()
        if self.ext not in TEXT_EXTENSIONS:raise ValueError('Selecione uma legenda SRT, ASS ou VTT.')
        self.loaded_bytes=self.path.read_bytes();self.loaded_sha=digest(self.loaded_bytes);self.raw=decode(self.loaded_bytes)
        self.template=None;self.source_path='';self.source_bytes=None;self.source_context={};self.video_path='';self.audio_stream=None;self.project='';self.approved=set();self.proposals={};self.source_verified=False;self.metadata_dirty=False;self.independent=False
        self.identity=digest(str(self.path).casefold().encode())[:24]
        self.origin_path=self.path;self.target_expected=None;self.report_path=self.path
        if self.ext=='.srt':
            self.records=O.parse_srt(self.raw);self.values=[record[2] for record in self.records];self.times=[record[1] for record in self.records]
        elif self.ext=='.vtt':
            self.template,self.records=O.parse_vtt(self.raw);self.values=[record[1] for record in self.records];self.times=[record[0] for record in self.records]
        else:
            self.template,self.records=O.parse_ass(self.raw);self.values=[record[1] for record in self.records]
            self.times=ass_times(self.raw)
        if not self.records:raise ValueError('A legenda não contém blocos para revisar.')
        self.bounds=[]
        for stamp in self.times:
            match=re.findall(r'(?:\d+:)?\d{2}:\d{2}[.,]\d{2,3}',stamp)
            self.bounds.append(tuple(seconds(x) for x in match[:2]) if len(match)>=2 else (None,None))
        self.annotations={};self.saved_annotations={};self.saved_bounds=list(self.bounds);self.alignment_bounds=list(self.bounds);self.saved_values=list(self.values);self.saved_approved=set();self.original_texts=['']*len(self.values);self.verified=[False]*len(self.values);self.reported=[[] for _ in self.values]
        self.load_reports()
    @property
    def dirty(self):return self.values!=self.saved_values or self.bounds!=self.saved_bounds or self.annotations!=self.saved_annotations or self.approved!=self.saved_approved or self.metadata_dirty
    def render(self):
        import ollama_script as O
        if self.ext=='.srt':return O.build_srt([(r[0],r[1],value) for r,value in zip(self.records,self.values)])
        pairs=[(r[0],value) for r,value in zip(self.records,self.values)]
        return O.build_ass(self.template,pairs) if self.ext=='.ass' else O.build_vtt(self.template,pairs)
    def set_raw(self,raw):
        import ollama_script as O
        if self.ext=='.srt':
            records=O.parse_srt(raw);template=None;values=[r[2] for r in records];times=[r[1] for r in records]
        elif self.ext=='.vtt':
            template,records=O.parse_vtt(raw);values=[r[1] for r in records];times=[r[0] for r in records]
        else:
            template,records=O.parse_ass(raw);values=[r[1] for r in records];times=ass_times(raw)
        if len(values)!=len(self.values):raise ValueError('A estrutura da versão não corresponde à legenda.')
        bounds=[]
        for stamp in times:
            matches=re.findall(r'(?:\d+:)?\d{2}:\d{2}[.,]\d{2,3}',stamp)
            bounds.append(tuple(seconds(x) for x in matches[:2]) if len(matches)>=2 else (None,None))
        self.raw=raw;self.records=records;self.template=template;self.values=values;self.times=times;self.bounds=bounds

    def load_reports(self):
        quality=json_read(sidecar_path(self.report_path,'.quality.json'))
        for entry in quality.get('findings',[]):
            index=entry.get('block',0)-1
            if 0<=index<len(self.values):
                self.reported[index]=list(entry.get('flags',[]))
                if entry.get('source'):self.original_texts[index]=entry['source']
        for suffix,key in (('.transcription.json','review_findings'),('.ocr.json','records')):
            report=json_read(sidecar_path(self.report_path,suffix))
            for entry in report.get(key,[]):
                if not entry.get('flags'):continue
                start,end=entry.get('start'),entry.get('end')
                if start is not None and end is not None:
                    for i,(a,b) in enumerate(self.bounds):
                        if a is not None and b is not None and min(b,end)>max(a,start):self.reported[i].extend(entry['flags'])
        candidate=quality.get('source')
        if candidate and Path(candidate).is_file() and Path(candidate).resolve()!=self.path:
            self.attach_source(candidate)
        if not self.source_path and self.report_path.is_file() and (sidecar_path(self.report_path,'.transcription.json').is_file() or sidecar_path(self.report_path,'.ocr.json').is_file()):
            self.attach_source(self.report_path)
        from speech_context import read_context
        context=read_context(self.path);self.project=context.get('series_project') or self.source_context.get('series_project') or quality.get('source_provenance',{}).get('series_project','')
        for source in (context.get('source_file'),):
            if source and Path(source).is_file() and Path(source).suffix.lower() in MEDIA_EXTENSIONS:self.video_path=str(Path(source).resolve())
        audit=json_read(sidecar_path(self.report_path,'.transcription.json'))
        self.audio_stream=audit.get('audio_stream')
        if self.source_path:
            audit=json_read(sidecar_path(self.source_path,'.transcription.json'))
            self.audio_stream=audit.get('audio_stream',self.audio_stream)
            context=read_context(self.source_path)
            video=context.get('source_file')
            if video and Path(video).is_file() and Path(video).suffix.lower() in MEDIA_EXTENSIONS:self.video_path=str(Path(video).resolve())
    def attach_source(self,path):
        # Match by exact interval, never by row number when timing differs.
        data=Path(path).read_bytes()
        from speech_context import read_context
        context=read_context(path)
        other=_parse_only(path,data)
        self.source_bytes=data;self.source_context=context
        mapping={}
        for index,bounds in enumerate(other.bounds):mapping.setdefault(bounds,[]).append(index)
        self.original_texts=['']*len(self.values);self.verified=[False]*len(self.values)
        for index,bounds in enumerate(self.alignment_bounds):
            matches=mapping.get(bounds,[])
            if len(matches)==1 and None not in bounds:
                self.original_texts[index]=other.values[matches[0]];self.verified[index]=True
        self.source_path=str(Path(path).resolve());self.source_verified=any(self.verified)
    def flags(self):
        import subtitle_quality as Q
        findings=[[flag for flag in flags if flag not in ('empty','reading_speed','long_line','too_many_lines','overlap','invalid_time','out_of_order')] for flags in self.reported]
        valid=[]
        for i,(text,(start,end)) in enumerate(zip(self.values,self.bounds)):
            flags=findings[i]
            if start is None or end is None or end<=start:flags.append('invalid_time')
            else:valid.append((start,end,i))
            drawing=self.ext=='.ass' and bool(re.search(r'\{[^}]*\\p[1-9]',text))
            if not Q.plain(text).strip() and not any(mark in text for mark in '♪♫♬♩'):flags.append('empty')
            if not drawing:
                if len(re.split(r'\n|\\N',text))>2:flags.append('too_many_lines')
                if any(len(Q.plain(line))>getattr(self,"line_width",42) for line in re.split(r'\n|\\N',text)):flags.append('long_line')
                if start is not None and end is not None and end>start and len(Q.plain(text))/(end-start)>getattr(self,"max_cps",20):flags.append('reading_speed')
            if self.source_path and not self.verified[i]:flags.append('source_unmatched')
            if i and start is not None and self.bounds[i-1][0] is not None and start<self.bounds[i-1][0]:flags.append('out_of_order')
        ordered=sorted(valid);end=None;last=None
        for start,finish,index in ordered:
            if end is not None and start<end-.01:
                intentional=all(self.annotations.get(i,{}).get('simultaneous') for i in (index,last))
                if not intentional:findings[index].append('overlap');findings[last].append('overlap')
            if end is None or finish>end:end=finish;last=index
        return [list(dict.fromkeys(flags)) for flags in findings]
    def rows(self):
        flags=self.flags()
        return [dict(id=str(i),index=i,number=i+1,time=self.times[i],start=self.bounds[i][0] or 0,end=self.bounds[i][1] or 0,
                     source=self.original_texts[i],sourceVerified=self.verified[i],text=text,flags=flags[i],approved=i in self.approved,
                     proposal=self.proposals.get(i,''),kind=self.annotations.get(i,{}).get('kind','dialogue'),simultaneous=self.annotations.get(i,{}).get('simultaneous',False)) for i,text in enumerate(self.values)]


def load_document_without_reports(path):
    # Avoid recursive provenance chains or malicious report cycles.
    # The parser itself is reusable without loading any sidecars.
    return _parse_only(path)


def _parse_only(path,data=None):
    import ollama_script as O
    from subtitle_formats import parse_ass_document,parse_vtt_document
    path=Path(path);raw=decode(path.read_bytes() if data is None else data);ext=path.suffix.lower()
    class Parsed:pass
    value=Parsed()
    if ext=='.srt':
        records=O.parse_srt(raw);value.values=[x[2] for x in records];times=[x[1] for x in records]
    elif ext=='.vtt':
        _,records=parse_vtt_document(raw);value.values=[x[1] for x in records];times=[x[0] for x in records]
    elif ext=='.ass':
        _,records=parse_ass_document(raw);value.values=[x[1] for x in records];times=ass_times(raw)
    else:raise ValueError('Selecione uma legenda SRT, ASS ou VTT.')
    value.bounds=[]
    for stamp in times:
        matches=re.findall(r'(?:\d+:)?\d{2}:\d{2}[.,]\d{2,3}',stamp)
        value.bounds.append(tuple(seconds(x) for x in matches[:2]) if len(matches)>=2 else (None,None))
    return value


class ReviewWorkspace:
    def __init__(self,root):self.root=Path(root).resolve();self.base=self.root/'outputs/studio';self.reviewed=self.base/'reviewed';self.history=self.base/'history'
    def _folder(self,identifier):
        if not re.fullmatch(r'[a-f0-9]{24}',identifier):raise ValueError('Histórico inválido.')
        folder=(self.history/identifier).resolve()
        if not folder.is_relative_to(self.root):raise ValueError('Destino fora da pasta do projeto.')
        return folder
    def open(self,path):
        path=Path(path).resolve()
        if path.name.endswith('.review_required.json'):return self.open_blocked(path)
        meta=json_read(Path(str(path)+'.review.json')) if path.is_relative_to(self.reviewed) else {}
        original=Path(meta.get('origin',path))
        if original.suffix.lower() not in TEXT_EXTENSIONS:raise ValueError('Origem do histórico inválida.')
        identifier=meta.get('identity') or digest(str(original.resolve()).casefold().encode())[:24]
        stem=original.stem[:150]
        target=self.reviewed/(identifier+'__'+stem+original.suffix.lower())
        # Resume the latest saved copy only when its source still matches.
        if meta and path!=target:raise ValueError('Origem do histórico inválida.')
        saved_meta=json_read(Path(str(target)+'.review.json'))
        if path==original and target.is_file() and saved_meta.get('origin_sha')==digest(path.read_bytes()):path=target;meta=saved_meta
        doc=SubtitleDocument(path);doc.identity=identifier;doc.origin_path=original;doc.origin_expected=meta.get('origin_sha') or (digest(original.read_bytes()) if original.is_file() else '');doc.independent=bool(meta.get('independent'));doc.report_path=original
        alignment=meta.get('alignment_bounds') if meta.get('sha256')==doc.loaded_sha else None
        if isinstance(alignment,list) and len(alignment)==len(doc.values) and all(isinstance(b,list) and len(b)==2 and all(v is None or isinstance(v,(int,float)) for v in b) for b in alignment):doc.alignment_bounds=[tuple(b) for b in alignment]
        doc.load_reports();doc.target=target;doc.target_expected=digest(target.read_bytes()) if target.is_file() else None
        from fansub_tools import annotations
        doc.annotations=annotations(meta.get('annotations',{}) if meta.get('sha256')==doc.loaded_sha else {},len(doc.values));doc.saved_annotations={i:dict(v) for i,v in doc.annotations.items()}
        doc.approved={int(i) for i,sha in meta.get('approved',{}).items() if 0<=int(i)<len(doc.values) and sha==digest(doc.values[int(i)].encode())};doc.saved_approved=set(doc.approved)
        snapshot=self._folder(identifier)/meta.get('source_snapshot','__missing__')
        if not snapshot.resolve().is_relative_to(self._folder(identifier).resolve()):raise ValueError('Origem do histórico inválida.')
        if snapshot.is_file():
            if digest(snapshot.read_bytes())!=meta.get('source_snapshot_sha'):raise ValueError('A origem salva no histórico está corrompida.')
            doc.attach_source(snapshot)
        elif meta.get('source') and Path(meta['source']).is_file():doc.attach_source(meta['source'])
        if isinstance(meta.get('reported'),list) and len(meta['reported'])==len(doc.values):doc.reported=meta['reported']
        doc.audio_stream=meta.get('audio_stream',doc.audio_stream);doc.video_path=meta.get('video') or doc.video_path;doc.project=meta.get('project') or doc.project
        draft=json_read(self._folder(identifier)/'draft.json')
        if draft.get('loaded_sha')==doc.loaded_sha and len(draft.get('values',[]))==len(doc.values) and all(isinstance(value,str) for value in draft.get('values',[])):
            doc.annotations=annotations(draft.get('annotations',doc.annotations),len(doc.values))
            before=(doc.project,doc.source_path,doc.video_path,doc.audio_stream)
            if isinstance(draft.get('raw'),str):doc.set_raw(draft['raw'])
            doc.values=draft['values'];doc.approved={i for i in draft.get('approved',[]) if isinstance(i,int) and 0<=i<len(doc.values)}
            doc.project=draft.get('project',doc.project);doc.video_path=draft.get('video',doc.video_path);doc.audio_stream=draft.get('audio_stream',doc.audio_stream)
            if draft.get('source') and Path(draft['source']).is_file():doc.attach_source(draft['source'])
            doc.metadata_dirty=before!=(doc.project,doc.source_path,doc.video_path,doc.audio_stream)
        return doc
    def open_blocked(self,path):
        report=json_read(path);source=Path(report.get('source',''))
        if not source.is_file() or source.suffix.lower() not in TEXT_EXTENSIONS:raise ValueError('A origem da tradução bloqueada não está disponível.')
        if report.get('source_sha256') and digest(source.read_bytes())!=report['source_sha256']:raise ValueError('A origem da tradução bloqueada mudou. Associe a origem atual manualmente.')
        identifier=digest(str(Path(path).resolve()).casefold().encode())[:24]
        target=self.reviewed/(identifier+'__'+source.stem[:150]+source.suffix.lower())
        if target.is_file():return self.open(target)
        doc=SubtitleDocument(source);doc.identity=identifier;doc.target=target;doc.target_expected=None;doc.origin_expected=digest(source.read_bytes())
        doc.attach_source(source);doc.values=['']*len(doc.values);doc.reported=[['not_translated'] for _ in doc.values]
        for entry in report.get('partial_translations',[]):
            i=entry.get('index',-1)
            if 0<=i<len(doc.values) and entry.get('time')==doc.times[i] and entry.get('source')==doc.original_texts[i]:
                doc.values[i]=entry['translation'];doc.reported[i]=[]
        i=report.get('block',0)-1
        if 0<=i<len(doc.values):
            doc.values[i]=report.get('rejected_candidate','');doc.reported[i]=['model_rejected']
        doc.saved_values=list(doc.values);doc.saved_approved=set();return doc

    def versions(self,doc):return json_read(self._folder(doc.identity)/'index.json',[])
    def autosave(self,doc):
        atomic_write_text(self._folder(doc.identity)/'draft.json',json.dumps({'annotations':doc.annotations,'loaded_sha':doc.loaded_sha,'raw':doc.render(),'values':doc.values,'approved':sorted(doc.approved),'project':doc.project,'source':doc.source_path,'video':doc.video_path,'audio_stream':doc.audio_stream},ensure_ascii=False))
    def _snapshot(self,doc,content,reason):
        identifier=time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]
        path=self._folder(doc.identity)/(identifier+doc.ext);atomic_bytes(path,content)
        return {'id':identifier,'file':path.name,'reason':reason,'date':time.strftime('%d/%m/%Y %H:%M:%S'),'sha256':digest(content),'annotations':doc.saved_annotations if reason in ('original','before_edit') else doc.annotations}
    def save(self,doc,reason='edit'):
        with directory_lock(self._folder(doc.identity)):
            return self._save_locked(doc,reason)
    def _save_locked(self,doc,reason):
        target=doc.target
        if not doc.independent and doc.origin_path.is_file() and digest(doc.origin_path.read_bytes())!=doc.origin_expected:
            raise ValueError('A legenda original mudou. Reabra antes de salvar.')
        if digest(doc.path.read_bytes())!=doc.loaded_sha:raise ValueError('A legenda foi alterada fora do editor. Reabra antes de salvar.')
        actual=digest(target.read_bytes()) if target.is_file() else None
        if actual!=doc.target_expected:raise ValueError('A cópia revisada mudou. Reabra antes de salvar.')
        versions=self.versions(doc)
        if not versions:versions.append(self._snapshot(doc,doc.loaded_bytes,'original'))
        if target.is_file() and (not versions or versions[-1]['sha256']!=actual):versions.append(self._snapshot(doc,target.read_bytes(),'before_edit'))
        content=doc.render().encode('utf-8');versions.append(self._snapshot(doc,content,reason))
        snapshot_name='';snapshot_sha=''
        if doc.source_bytes is not None:
            snapshot_sha=digest(doc.source_bytes);snapshot_name='source_'+snapshot_sha[:16]+Path(doc.source_path).suffix.lower()
            snapshot=self._folder(doc.identity)/snapshot_name;atomic_bytes(snapshot,doc.source_bytes)
            from speech_context import write_context
            context=doc.source_context
            write_context(snapshot,context.get('source_file') or doc.source_path,context.get('confirmed_terms',{}),context.get('speech_terms'),context.get('uncertain_ranges'),context.get('source_kind','subtitle'),series_project=doc.project or context.get('series_project'))
        origin_sha=doc.origin_expected
        meta={'identity':doc.identity,'origin':str(doc.origin_path),'origin_sha':origin_sha,'source':doc.source_path,'video':doc.video_path,'audio_stream':doc.audio_stream,'project':doc.project,
              'approved':{str(i):digest(doc.values[i].encode()) for i in doc.approved},'sha256':digest(content),
              'reported':doc.reported,'source_snapshot':snapshot_name,'source_snapshot_sha':snapshot_sha,'annotations':doc.annotations,'independent':doc.independent,'alignment_bounds':doc.alignment_bounds}
        transaction(self.root,{target:content,Path(str(target)+'.review.json'):json.dumps(meta,ensure_ascii=False,indent=2).encode(),self._folder(doc.identity)/'index.json':json.dumps(versions,ensure_ascii=False,indent=2).encode()})
        doc.target_expected=digest(content)
        doc.path=target;doc.loaded_bytes=content;doc.loaded_sha=digest(content)
        doc.saved_annotations={i:dict(v) for i,v in doc.annotations.items()};doc.saved_bounds=list(doc.bounds);doc.saved_values=list(doc.values);doc.saved_approved=set(doc.approved);doc.metadata_dirty=False;self.autosave(doc)
        return target
    def fork(self,doc):
        previous=(doc.identity,doc.target,doc.target_expected,doc.path,doc.independent)
        try:
            doc.identity=uuid.uuid4().hex[:24];doc.target=self.reviewed/(doc.identity+'__'+doc.origin_path.stem[:150]+doc.ext);doc.target_expected=None;doc.independent=True
            base=self._folder(doc.identity)/('base'+doc.ext);atomic_bytes(base,doc.loaded_bytes);doc.path=base
            return self.save(doc,'independent')
        except Exception:
            doc.identity,doc.target,doc.target_expected,doc.path,doc.independent=previous
            raise

    def restore(self,doc,identifier):
        version=next((v for v in self.versions(doc) if v['id']==identifier),None)
        if version is None:raise ValueError('Versão não encontrada.')
        path=self._folder(doc.identity)/version['file']
        if not path.resolve().is_relative_to(self._folder(doc.identity).resolve()):raise ValueError('Versão inválida.')
        content=path.read_bytes()
        if digest(content)!=version['sha256']:raise ValueError('A versão do histórico está corrompida.')
        parsed=_parse_only(path)
        if len(parsed.values)!=len(doc.values):raise ValueError('A estrutura da versão não corresponde à legenda.')
        old=doc.render();approved=set(doc.approved);old_annotations=dict(doc.annotations)
        try:
            doc.set_raw(decode(content));doc.approved=set()
            from fansub_tools import annotations
            doc.annotations=annotations(version.get('annotations',{}),len(doc.values));result=self.save(doc,'restore');doc.proposals={};return result
        except Exception:doc.set_raw(old);doc.approved=approved;doc.annotations=old_annotations;raise
    def backup(self):
        import io
        files=[]
        for relative in ('config.json','glossary.json','series_projects','series_glossaries','series_memories','series_speech','outputs/studio/reviewed','outputs/studio/history','outputs/studio/episode_reports','export_presets','outputs/studio/exports'):
            path=self.root/relative
            if path.is_file():files.append(path)
            elif path.is_dir():files.extend(p for p in path.rglob('*') if p.is_file() and not p.is_symlink())
        if sum(path.stat().st_size for path in files)>512*1024*1024:raise ValueError('Backup maior que o limite de segurança.')
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w',compression=zipfile.ZIP_DEFLATED) as archive:
            for path in files:
                if path.resolve().is_relative_to(self.root) and path.suffix.lower() in ('.json','.srt','.ass','.vtt'):archive.writestr(path.relative_to(self.root).as_posix(),path.read_bytes())
        target=(self.root/'backups/studio'/('studio_'+time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]+'.zip')).resolve()
        if not target.is_relative_to(self.root):raise ValueError('Destino fora da pasta do projeto.')
        atomic_bytes(target,buffer.getvalue());return target
    def restore_backup(self,path):
        files={};allowed=('series_projects/','series_glossaries/','series_memories/','series_speech/','outputs/studio/reviewed/','outputs/studio/history/','outputs/studio/episode_reports/','export_presets/','outputs/studio/exports/')
        with zipfile.ZipFile(path) as archive:
            if sum(x.file_size for x in archive.infolist())>512*1024*1024:raise ValueError('Backup maior que o limite de segurança.')
            for info in archive.infolist():
                name=info.filename
                if info.is_dir():continue
                rel=PurePosixPath(name)
                if '\\' in name or rel.is_absolute() or '..' in rel.parts or ':' in name or (info.external_attr>>16)&0o170000==0o120000:raise ValueError('Caminho de backup inválido.')
                if name not in ('config.json','glossary.json') and not name.startswith(allowed):raise ValueError('O backup contém arquivos fora do escopo permitido.')
                if rel.suffix.lower() not in ('.json','.srt','.ass','.vtt'):raise ValueError('Tipo de arquivo não permitido no backup.')
                target=self.root.joinpath(*rel.parts).resolve()
                if not target.is_relative_to(self.root):raise ValueError('Caminho de backup inválido.')
                if target in files:raise ValueError('Arquivo duplicado no backup.')
                data=archive.read(info)
                if rel.suffix=='.json':json.loads(data.decode('utf-8-sig'))
                files[target]=data
        if not files:raise ValueError('Backup vazio.')
        safety=self.backup();transaction(self.root,files);return safety
