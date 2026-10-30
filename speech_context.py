"""Content-bound provenance and confirmed series context for generated subtitles."""
from studio_ui.output_layout import sidecar_path
from pathlib import Path
import hashlib
import json
import re

VERSION = 'speech-context-v1'


def read_context(source):
    source = Path(source)
    sidecar = sidecar_path(source,'.source.json')
    if not sidecar.is_file(): return {}
    try:
        data = json.loads(sidecar.read_text(encoding='utf-8'))
        if data.get('version') != VERSION or data.get('sha256') != hashlib.sha256(source.read_bytes()).hexdigest(): return {}
        terms = data.get('confirmed_terms',{})
        if not isinstance(terms,dict) or any(not isinstance(k,str) or not isinstance(v,str) for k,v in terms.items()): return {}
        return data
    except (OSError,ValueError,TypeError): return {}


def write_context(subtitle, origin, terms, speech_terms=None, uncertain_ranges=None, source_kind="asr", series_project=None):
    from pipeline_io import atomic_write_text
    subtitle,origin = Path(subtitle),Path(origin)
    data = dict(source_kind=source_kind,version=VERSION,sha256=hashlib.sha256(subtitle.read_bytes()).hexdigest(),
                source_file=str(origin.resolve()),series_identity=hashlib.sha256(str(origin.parent.resolve()).casefold().encode()).hexdigest()[:20],
                confirmed_terms=dict(terms),speech_terms=dict(speech_terms or {}),uncertain_ranges=list(uncertain_ranges or []))
    if series_project:data['series_project']=series_project
    # A newly generated file may reuse a visible name whose older intermediate
    # is archived internally. Stage its provenance beside this new file; the
    # pipeline compacts it only after finalizing the deliverable.
    atomic_write_text(Path(str(subtitle)+'.source.json'),json.dumps(data,ensure_ascii=False,indent=2))


def load_speech_terms(origin, app):
    from subtitle_quality import load_mapping
    origin,app=Path(origin),Path(app)
    identity=hashlib.sha256(str(origin.parent.resolve()).casefold().encode()).hexdigest()[:20]
    terms={}
    for path in (app/'series_speech'/f'{identity}.json',origin.parent/'whisper_glossary.json',origin.with_suffix('.whisper_glossary.json')):
        if path.is_file():terms.update(load_mapping(path))
    return terms


def uncertain_cue(timestamp, context):
    values=re.findall(r'(?:\d+:)?\d{2}:\d{2}[.,]\d+',timestamp)
    if len(values)!=2:return False
    def seconds(value):
        parts=value.replace(',','.').split(':')
        return sum(float(p)*60**i for i,p in enumerate(reversed(parts)))
    start,end=map(seconds,values)
    return any(min(end,float(item['end']))-max(start,float(item['start']))>.05
               for item in context.get('uncertain_ranges',[]) if 'start' in item and 'end' in item)
