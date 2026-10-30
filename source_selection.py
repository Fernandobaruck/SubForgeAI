"""Explicit source selection and small non-destructive subtitle samples."""
from studio_ui.output_layout import sidecar_path
import json,re,subprocess,uuid
from pathlib import Path
from pipeline_io import atomic_write_text,staged_output
from speech_context import read_context,write_context

MODES=('auto','whisper','embedded','external','ocr')


def validate_options(options):
    options=dict(options or {});mode=options.get('source_mode','auto')
    if mode not in MODES:raise ValueError('Fonte de legenda inválida.')
    audio=str(options.get('audio_stream','auto'));subtitle=str(options.get('subtitle_stream',''))
    if not re.fullmatch(r'auto|\d+',audio) or subtitle and not subtitle.isdigit():raise ValueError('Índice de faixa inválido.')
    identifier=str(options.get('series_project',''))
    if identifier and not re.fullmatch(r'[a-f0-9]{32}',identifier):raise ValueError('Anime inválido.')
    language=str(options.get('audio_language',''))
    if language and not re.fullmatch(r'auto|[a-z]{2,3}(?:-[a-zA-Z]{2})?',language):raise ValueError('Idioma de áudio inválido.')
    seconds=float(options.get('sample_seconds',0));start=float(options.get('sample_start',0))
    if seconds not in (0,60) or not 0<=start<=24*3600:raise ValueError('Intervalo de teste inválido.')
    return dict(source_mode=mode,audio_stream=audio,audio_language=language,subtitle_stream=subtitle,source_subtitle=str(options.get('source_subtitle','')),series_project=identifier,sample_seconds=seconds,sample_start=start)


def probe(path,root):
    tool=Path(root)/'tools/ffmpeg/ffprobe.exe'
    result=subprocess.run([str(tool),'-v','error','-show_streams','-show_format','-of','json',str(path)],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=30,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode:raise ValueError('Não foi possível listar as faixas: '+result.stderr[-300:])
    data=json.loads(result.stdout);return [dict(index=int(s['index']),kind=s.get('codec_type',''),codec=s.get('codec_name',''),language=s.get('tags',{}).get('language','und'),title=s.get('tags',{}).get('title','')) for s in data.get('streams',[]) if s.get('codec_type') in ('audio','subtitle')]


def subset_text(document,indices):
    import ollama_script as O
    indices=set(indices)
    if not indices:raise ValueError('Nenhum bloco no intervalo selecionado.')
    if document.ext=='.srt':return O.build_srt([record for i,record in enumerate(document.records) if i in indices])
    raw=document.raw;ranges=[]
    separators=list(re.finditer(r'\r?\n[ \t]*\r?\n',raw)) if document.ext=='.vtt' else []
    for i,(start,end) in enumerate(document.template.slots):
        if i in indices:continue
        if document.ext=='.ass':
            a=raw.rfind('\n',0,start)+1;b=raw.find('\n',end);b=len(raw) if b<0 else b+1
        else:
            a=max((s.end() for s in separators if s.end()<=start),default=0)
            b=min((s.end() for s in separators if s.start()>=end),default=len(raw))
        ranges.append((a,b))
    for a,b in sorted(set(ranges),reverse=True):raw=raw[:a]+raw[b:]
    return raw


def subtitle_sample(path,folder,start,duration=60):
    from review_workspace import SubtitleDocument
    doc=SubtitleDocument(path);indices=[i for i,(a,b) in enumerate(doc.bounds) if a is not None and b is not None and min(b,start+duration)>max(a,start)]
    target=Path(folder)/(Path(path).stem+'.sample'+Path(path).suffix.lower())
    atomic_write_text(target,subset_text(doc,indices))
    context=read_context(path)
    write_context(target,context.get('source_file') or path,context.get('confirmed_terms',{}),context.get('speech_terms'),context.get('uncertain_ranges'),context.get('source_kind','subtitle'))
    if context.get('series_project'):
        data=json.loads(sidecar_path(target,'.source.json').read_text(encoding='utf-8'));data['series_project']=context['series_project'];atomic_write_text(sidecar_path(target,'.source.json'),json.dumps(data,ensure_ascii=False))
    return target


def context_copy(path,folder,origin,root,identifier=''):
    path=Path(path);target=Path(folder)/(uuid.uuid4().hex[:12]+'_'+path.name)
    target.parent.mkdir(parents=True,exist_ok=True)
    with staged_output(target) as temporary:temporary.write_bytes(path.read_bytes())
    context=read_context(path)
    media=Path(origin).suffix.lower() not in ('.srt','.ass','.vtt','.sup','.idx','.sub')
    write_context(target,origin if media else context.get('source_file') or origin,context.get('confirmed_terms',{}),context.get('speech_terms'),context.get('uncertain_ranges'),context.get('source_kind','subtitle'))
    if identifier:
        from series_registry import apply_project
        apply_project(target,origin,root,identifier)
    return target
