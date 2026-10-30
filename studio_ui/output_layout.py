"""Keep deliverables separate from recoverable processing metadata."""
from pathlib import Path
import hashlib,json,os
from pipeline_io import atomic_write_text

SUFFIXES=('.source.json','.quality.json','.transcription.json','.ocr.json','.export.json')

def internal_folder(path):
    parent=Path(path).parent
    return parent if parent.name=='.subforge' else parent/'.subforge'

def sidecar_path(path,suffix):
    """Read/write existing layouts, including portable legacy subtitles."""
    path=Path(path);legacy=Path(str(path)+suffix)
    stored=internal_folder(path)/(path.name+suffix)
    return stored if stored.is_file() and not legacy.is_file() else legacy

def is_internal(path):
    return '.subforge' in Path(path).parts

def compact_result(final,intermediate=None):
    """Archive only an explicitly supplied generated intermediate, never input."""
    final=Path(final).resolve()
    if not final.is_file():raise FileNotFoundError(final)
    context=sidecar_path(final,'.source.json')
    context_data=json.loads(context.read_text(encoding='utf-8-sig')) if context.is_file() else None
    if context_data is not None and not isinstance(context_data,dict):raise ValueError('Proveniência da legenda inválida.')
    folder=internal_folder(final);folder.mkdir(parents=True,exist_ok=True)
    # A hidden folder on Windows; other platforms already hide dot directories.
    if os.name=='nt':
        import ctypes
        attrs=ctypes.windll.kernel32.GetFileAttributesW(str(folder))
        if attrs!=-1:ctypes.windll.kernel32.SetFileAttributesW(str(folder),attrs|2)
    archived=None
    if intermediate is not None:
        source=Path(intermediate).resolve()
        if source!=final:
            if source.parent!=final.parent or source.suffix.lower() not in ('.srt','.vtt','.ass'):
                raise ValueError('O intermediário deve ser uma legenda gerada na mesma pasta do resultado.')
            if source.is_file():
                archived=folder/source.name
                if archived.exists() and archived.read_bytes()!=source.read_bytes():
                    token=hashlib.sha256(source.read_bytes()).hexdigest()[:12]
                    archived=folder/(source.stem+'.'+token+source.suffix)
                # Move metadata first, retaining all reports for the archived cue text.
                for suffix in SUFFIXES:
                    old=sidecar_path(source,suffix)
                    if old.is_file():
                        dest=folder/(archived.name+suffix)
                        if old!=dest:os.replace(old,dest)
                os.replace(source,archived)
                quality=sidecar_path(archived,'.quality.json')
                if quality.is_file():
                    atomic_write_text(folder/(final.name+'.quality.json'),quality.read_text(encoding='utf-8-sig'))
    for suffix in SUFFIXES:
        old=Path(str(final)+suffix);target=folder/(final.name+suffix)
        if old.is_file():os.replace(old,target)
    context=sidecar_path(final,'.source.json')
    if archived and context_data is not None:
        data=context_data
        for field in ('visual_source_path','source_file'):
            if data.get(field) and Path(data[field]).resolve()==Path(intermediate).resolve():data[field]=str(archived)
        atomic_write_text(context,json.dumps(data,ensure_ascii=False,indent=2))
    return str(final)
