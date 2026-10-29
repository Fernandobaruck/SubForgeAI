"""Local inventory and tightly scoped, preview-bound temporary-file cleanup."""
from __future__ import annotations
import os,re,json,stat,time,hashlib
from pathlib import Path

def resources(values):
    def number(key,low,high,default):
        try:value=float(values.get(key,default))
        except (TypeError,ValueError):return default
        return int(value) if value.is_integer() and low<=value<=high else default
    return dict(resource_cpu_threads=number('resource_cpu_threads',0,min(256,os.cpu_count() or 1),0),
                resource_gpu_layers=number('resource_gpu_layers',-1,100,-1),resource_background=values.get('resource_background',False) is True)

def resource_env(values):
    values=resources(values);env={'SUBFORGEAI_CPU_THREADS':str(values['resource_cpu_threads']),'SUBFORGEAI_GPU_LAYERS':str(values['resource_gpu_layers'])}
    if values['resource_cpu_threads']:
        env.update({key:str(values['resource_cpu_threads']) for key in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','NUMEXPR_NUM_THREADS')})
    return env

def _ordinary(path,root):
    """Reject links/junctions at every level; callers never follow reparse points."""
    path=Path(path).absolute();root=Path(root).resolve()
    try:
        if not path.resolve().is_relative_to(root):return False
        for part in (path,*path.parents):
            if part==root:break
            info=part.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400:return False
        return True
    except OSError:return False

def scan_models(root,ollama_root=None):
    root=Path(root).resolve();rows=[]
    stores=[Path(ollama_root)] if ollama_root else [root/'ollama_models_v2',root/'ollama_models']
    for store in stores:
        manifests=store/'manifests'
        if not manifests.is_dir():continue
        for manifest in sorted(manifests.rglob('*')):
            if not manifest.is_file() or not _ordinary(manifest,store):continue
            try:
                data=json.loads(manifest.read_text(encoding='utf-8'))
                if not isinstance(data,dict) or not isinstance(data.get('layers'),list) or not isinstance(data.get('config'),dict) or any(not isinstance(layer,dict) for layer in data['layers']):raise ValueError('Manifesto inválido')
                layers=[data['config'],*data['layers']];files=[];missing=[]
                if not any(layer.get('mediaType')=='application/vnd.ollama.image.model' for layer in data.get('layers',[])):raise ValueError('Manifesto sem pesos de modelo')
                for layer in layers:
                    name=layer.get('digest','');size=layer.get('size')
                    if not re.fullmatch(r'sha256:[a-f0-9]{64}',name) or type(size) is not int or size<0:raise ValueError('Manifesto inválido')
                    path=store/'blobs'/name.replace(':','-')
                    if not _ordinary(path,store) or not path.is_file() or path.stat().st_size!=size:missing.append(name)
                    else:files.append(dict(path=str(path),size=size,sha256=name.split(':')[1]))
                relative=manifest.relative_to(manifests);name='/'.join(relative.parts[2:-1])+':'+relative.name if len(relative.parts)>=3 else str(relative)
                rows.append(dict(name=name,type='Ollama',path=str(store),bytes=sum(x.get('size',0) for x in layers),offline=not missing,status='ready' if not missing else 'incomplete',files=files,detail=', '.join(missing)))
            except (OSError,ValueError,TypeError) as exc:rows.append(dict(name=manifest.name,type='Ollama',path=str(store),bytes=0,offline=False,status='invalid',files=[],detail=str(exc)))
    hub=root/'cache/hub'
    if hub.is_dir():
        for store in sorted(hub.glob('models--*')):
            snapshots=store/'snapshots';candidates=[]
            if not _ordinary(store,root):continue
            reference=store/'refs/main'
            if reference.is_file():
                revision=reference.read_text(encoding='utf-8').strip()
                if re.fullmatch(r'[a-f0-9]{40}',revision):candidates.append(snapshots/revision)
            if snapshots.is_dir():candidates.extend(sorted(snapshots.iterdir(),key=lambda p:p.stat().st_mtime,reverse=True))
            chosen=next((p for p in candidates if all((p/n).is_file() and (p/n).stat().st_size>0 and (p/n).resolve().is_relative_to(store.resolve()) for n in ('model.bin','config.json','tokenizer.json'))),None)
            files=[]
            if chosen:
                # HF snapshots may use symlinks to immutable blobs within this same model store.
                for path in chosen.rglob('*'):
                    if path.is_file() and path.resolve().is_relative_to(store.resolve()):
                        expected=path.resolve().name;files.append(dict(path=str(path.resolve()),size=path.stat().st_size,sha256=expected if re.fullmatch('[a-f0-9]{64}',expected) else ''))
            rows.append(dict(name=store.name.removeprefix('models--').replace('--','/'),type='Hugging Face',path=str(chosen or store),bytes=sum(f['size'] for f in files),offline=chosen is not None,status='ready' if chosen else 'incomplete',files=files,detail=''))
    # Demucs/Whisper checkpoints are useful for judging the complete offline pipeline.
    for parent in (hub/'checkpoints',root/'cache/torch/hub/checkpoints'):
        if parent.is_dir():
            for path in sorted(parent.glob('*')):
                if path.is_file() and _ordinary(path,root):rows.append(dict(name=path.name,type='Checkpoint',path=str(parent),bytes=path.stat().st_size,offline=True,status='present',files=[dict(path=str(path),size=path.stat().st_size,sha256='')],detail=''))
    for path in sorted((root/'runtime/python/Lib/site-packages/rapidocr/models').glob('*.onnx')):
        if path.is_file() and _ordinary(path,root):
            size=path.stat().st_size;rows.append(dict(name=path.stem,type='OCR ONNX',path=str(path.parent),bytes=size,offline=size>0,status='present' if size else 'incomplete',files=[dict(path=str(path),size=size,sha256='')],detail=''))
    return rows

def verify_model(row,cancel=None):
    verified=0;unhashed=0
    for entry in row.get('files',[]):
        path=Path(entry['path'])
        if not path.is_file() or path.stat().st_size!=entry['size']:raise ValueError('Arquivo do modelo ausente ou com tamanho diferente.')
        if not entry.get('sha256'):unhashed+=1;continue
        sha=hashlib.sha256()
        with path.open('rb') as stream:
            while chunk:=stream.read(8*1024*1024):
                if cancel and cancel.is_set():raise ValueError('Verificação cancelada.')
                sha.update(chunk)
        if sha.hexdigest()!=entry['sha256']:raise ValueError('A verificação encontrou um arquivo de modelo corrompido.')
        verified+=1
    if not row.get('offline'):raise ValueError('O modelo está incompleto.')
    return dict(verified=verified,unhashed=unhashed)

def cleanup_category(relative):
    parts=relative.parts
    if len(parts)>=4 and parts[:3]==('outputs','studio','previews'):return 'previews'
    if len(parts)==3 and parts[:2]==('logs','studio') and re.fullmatch(r'\d{8}_\d{6}_[a-f0-9]+\.log',parts[-1]):return 'logs'
    if relative.suffix=='.pyc' and '__pycache__' in parts and (parts[0]=='__pycache__' or parts[0] in ('studio_ui','tools','tests')):return 'python'
    return ''

def cleanup_preview(root,days=7,protected=()):
    root=Path(root).resolve();days=int(days)
    if not 0<=days<=3650:raise ValueError('Intervalo de limpeza inválido.')
    protected={str(Path(p).resolve()).casefold() for p in protected if p};candidates=[];cutoff=time.time()-days*86400
    starts=[root/'outputs/studio/previews',root/'logs/studio',root/'__pycache__']
    starts.extend(root/name for name in ('studio_ui','tools','tests'))
    for start in starts:
        if not start.is_dir() or not _ordinary(start,root):continue
        for base,dirs,files in os.walk(start,followlinks=False):
            dirs[:]=[d for d in dirs if _ordinary(Path(base,d),root)]
            for name in files:
                path=Path(base,name);rel=path.relative_to(root);category=cleanup_category(rel)
                if not category or not _ordinary(path,root) or str(path.resolve()).casefold() in protected:continue
                info=path.stat()
                if days>0 and info.st_mtime>cutoff or not stat.S_ISREG(info.st_mode):continue
                candidates.append(dict(id=hashlib.sha256(str(path).encode()).hexdigest()[:24],path=str(path),relative=str(rel),category=category,bytes=info.st_size,mtime=info.st_mtime_ns,inode=info.st_ino))
                if len(candidates)>10000:raise ValueError('Prévia de limpeza muito grande. Escolha um intervalo maior.')
    return sorted(candidates,key=lambda x:x['relative'])

def delete_preview(root,entries,protected=()):
    root=Path(root).resolve();protected={str(Path(p).resolve()).casefold() for p in protected if p};removed=[];errors=[]
    for entry in entries:
        path=Path(entry['path'])
        try:
            # Verify the absolute resolved target and all ancestors immediately before unlink.
            if not path.is_absolute() or not path.resolve().is_relative_to(root) or not _ordinary(path,root) or not cleanup_category(path.relative_to(root)) or str(path.resolve()).casefold() in protected:raise ValueError('Arquivo fora do escopo de limpeza.')
            info=path.stat()
            if (info.st_size,info.st_mtime_ns,info.st_ino)!=(entry['bytes'],entry['mtime'],entry['inode']):raise ValueError('O arquivo mudou desde a prévia.')
            path.unlink();removed.append(entry)
        except (OSError,ValueError) as exc:errors.append(path.name+': '+str(exc))
    return dict(removed=len(removed),bytes=sum(e['bytes'] for e in removed),errors=errors)
