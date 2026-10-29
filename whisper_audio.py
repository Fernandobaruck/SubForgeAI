"""Audio selection and local model resolution for anime transcription."""
from pathlib import Path
import json
import os
import re
import subprocess

LANGUAGES = {'jpn':'ja','eng':'en','por':'pt','ptb':'pt','spa':'es','fra':'fr',
             'fre':'fr','deu':'de','ger':'de','ita':'it','kor':'ko','zho':'zh','chi':'zh','rus':'ru'}


def language_code(value):
    value = str(value or '').lower().replace('_','-').split('-')[0]
    if value in ('', 'und', 'auto'): return None
    return LANGUAGES.get(value, value if len(value)==2 else None)


def is_commentary(stream):
    disposition=stream.get('disposition',{})
    return bool(disposition.get('comment') or disposition.get('visual_impaired') or
                re.search(r'commentary|commentaire|coment[aá]rio|audio description',stream.get('tags',{}).get('title',''),re.I))


def choose_stream(streams, language=None, selection='auto'):
    audio = [s for s in streams if s.get('codec_type')=='audio']
    if not audio: raise ValueError('O arquivo não contém uma faixa de áudio.')
    wanted = language_code(language)
    if str(selection) != 'auto':
        if not str(selection).isdigit(): raise ValueError('Faixa inválida: use auto ou o índice da stream.')
        candidates = [s for s in audio if s['index']==int(selection)]
        if not candidates: raise ValueError(f'A stream {selection} não é uma faixa de áudio disponível.')
        selected = candidates[0]
        actual = language_code(selected.get('tags',{}).get('language'))
        if wanted and actual and wanted!=actual:
            raise ValueError(f'Idioma solicitado ({wanted}) difere da faixa selecionada ({actual}).')
        return selected
    if wanted:
        candidates = [s for s in audio if language_code(s.get('tags',{}).get('language'))==wanted]
        if not candidates:
            candidates = [s for s in audio if language_code(s.get('tags',{}).get('language')) is None]
        if not candidates: raise ValueError(f'Não há faixa no idioma {wanted}; confira o idioma ou selecione outra faixa.')
    else:
        regular = [s for s in audio if not is_commentary(s)] or audio
        japanese = [s for s in regular if language_code(s.get('tags',{}).get('language'))=='ja']
        candidates = japanese or regular
    def score(s):
        disposition=s.get('disposition',{})
        return (not is_commentary(s), bool(disposition.get('original')), bool(disposition.get('default')), -int(s['index']))
    return max(candidates,key=score)


def inspect_audio(path, ffprobe, language=None, selection='auto'):
    result=subprocess.run([str(ffprobe),'-v','error','-show_streams','-of','json',str(path)],
        capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=30,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode: raise RuntimeError('Não foi possível inspecionar as faixas de áudio: '+result.stderr[-500:])
    return choose_stream(json.loads(result.stdout).get('streams',[]),language,selection)


WHISPER_REPOSITORIES = {name: 'Systran/faster-whisper-'+name
    for name in ('tiny','base','small','medium','large-v3')}
WHISPER_REPOSITORIES['large-v3-turbo'] = 'mobiuslabsgmbh/faster-whisper-large-v3-turbo'


def local_faster_model(model, root):
    supplied=Path(model)
    if supplied.is_dir(): return str(supplied.resolve())
    repository=WHISPER_REPOSITORIES.get(model)
    if not repository: return model
    store=Path(root)/'cache/hub'/('models--'+repository.replace('/','--'))
    snapshots=store/'snapshots'
    candidates=[]
    try:
        revision=(store/'refs/main').read_text(encoding='utf-8').strip()
        if re.fullmatch(r'[a-fA-F0-9]{40}',revision):candidates.append(snapshots/revision)
    except OSError:pass
    if snapshots.is_dir():candidates.extend(sorted(snapshots.iterdir(),key=lambda p:p.stat().st_mtime,reverse=True))
    for path in candidates:
        if all((path/name).is_file() for name in ('model.bin','config.json','tokenizer.json')):
            return str(path.resolve())
    return model
