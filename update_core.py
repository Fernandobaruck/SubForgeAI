"""Signed app-only updates with bounded downloads, scoped writes and crash recovery."""
from __future__ import annotations
import base64,hashlib,json,os,re,shutil,stat,tempfile,time,uuid,zipfile
from contextlib import contextmanager
from pathlib import Path,PurePosixPath
from urllib.request import Request,build_opener,HTTPRedirectHandler
from urllib.error import HTTPError
from release_info import VERSION,REPOSITORY,PUBLIC_KEY_B64,RUNTIME_ID
from release_crypto import verify

ROOT_FILES=set('embed_script.py extract_subs.py fansub_tools.py glossary_support.py maintenance_tools.py monitor.py ollama_script.py pgs_ocr.py pipeline_io.py profile_manager.py review_workspace.py season_tools.py series_registry.py source_selection.py speech_context.py speech_refinement.py studio_bootstrap.py studio_launcher.py subtitle_editor.py subtitle_formats.py subtitle_quality.py verificar_ollama.py whisper_audio.py whisper_script.py release_info.py release_crypto.py update_core.py studio_update_worker.py SubForgeAI_Studio.exe'.split())|{'SubForgeAI Studio.exe'}
MAX_PACKAGE=300*1024*1024
def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf-8')
def sha(data):return hashlib.sha256(data).hexdigest()
def file_sha(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        while chunk:=stream.read(8*1024*1024):digest.update(chunk)
    return digest.hexdigest()
def version_tuple(value):
    if not isinstance(value,str) or not re.fullmatch(r'\d{1,4}\.\d{1,4}\.\d{1,4}',value):raise ValueError('Versão de atualização inválida.')
    return tuple(map(int,value.split('.')))
def allowed(relative):
    if not isinstance(relative,str) or '\\' in relative or ':' in relative or '\x00' in relative:return False
    path=PurePosixPath(relative)
    if path.is_absolute() or str(path)!=relative or any(p in ('.','..','') or p.endswith((' ','.')) or re.match(r'(?i)^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)',p) for p in path.parts):return False
    if relative in ROOT_FILES:return True
    if relative=='docs/STUDIO.md':return True
    if path.parts[:1]==('_studio_boot',) and len(path.parts)>1:return '__pycache__' not in path.parts
    if path.parts[:1]==('studio_ui',) and len(path.parts)>1:return '__pycache__' not in path.parts and (path.suffix in ('.py','.qml','.json','.txt') or path.name=='qmldir')
    if path.parts[:2]==('assets','brand'):return path.suffix.lower() in ('.png','.ico','.svg','.jpg','.webp')
    return False
def safe_target(root,relative):
    if not allowed(relative):raise ValueError('O pacote contém um caminho não permitido.')
    root=Path(root).resolve();path=root.joinpath(*PurePosixPath(relative).parts)
    if not path.resolve().is_relative_to(root):raise ValueError('Caminho de atualização fora da instalação.')
    if path.exists() and not path.is_file():raise ValueError('O pacote contém um caminho não permitido.')
    for parent in (path,*path.parents):
        if parent==root:break
        if parent.exists() or parent.is_symlink():
            info=parent.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400:raise ValueError('Links não são permitidos nos arquivos da atualização.')
    return path
def write_bytes(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);fd,name=tempfile.mkstemp(prefix='.update-write-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
        os.replace(name,path)
    finally:Path(name).unlink(missing_ok=True)
def save_json(path,data):write_bytes(path,canonical(data))
def internal_root(root):
    root=Path(root).resolve();cache=root/'.updates'
    for path in (cache,cache/'jobs'):
        if path.exists() or path.is_symlink():
            info=path.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400 or not path.resolve().is_relative_to(root):raise ValueError('A pasta de atualização não pode ser um link.')
    cache.mkdir(exist_ok=True);return cache
@contextmanager
def app_lease(root,exclusive=False):
    path=internal_root(root)/'app.lock'
    if os.name!='nt':
        yield;return
    import ctypes
    api=ctypes.WinDLL('kernel32',use_last_error=True);api.CreateFileW.argtypes=[ctypes.c_wchar_p,ctypes.c_ulong,ctypes.c_ulong,ctypes.c_void_p,ctypes.c_ulong,ctypes.c_ulong,ctypes.c_void_p];api.CreateFileW.restype=ctypes.c_void_p
    handle=api.CreateFileW(str(path),0xc0000000 if exclusive else 0x80000000,0 if exclusive else 1,None,4,0x80,None)
    if handle==ctypes.c_void_p(-1).value:raise ValueError('Feche as outras instâncias do Studio antes de instalar ou recuperar a atualização.')
    try:yield
    finally:api.CloseHandle.argtypes=[ctypes.c_void_p];api.CloseHandle(handle)

def validate_envelope(envelope,public=None):
    try:
        payload=envelope['manifest'];signature=base64.b64decode(envelope['signature'],validate=True)
        if not verify(base64.b64decode(public or PUBLIC_KEY_B64),canonical(payload),signature):raise ValueError('Assinatura da atualização inválida.')
        version_tuple(payload['version'])
        if payload.get('schema')!=1 or payload.get('repository')!=REPOSITORY or payload.get('runtime')!=RUNTIME_ID:raise ValueError('Pacote incompatível com esta instalação.')
        if type(payload.get('zip_size')) is not int or not 0<payload['zip_size']<=MAX_PACKAGE or not re.fullmatch('[a-f0-9]{64}',payload.get('zip_sha256','')):raise ValueError('Manifesto de atualização inválido.')
        files=payload['files'];seen=set()
        if not isinstance(files,list) or not 1<=len(files)<=2000:raise ValueError('Manifesto de atualização inválido.')
        for entry in files:
            name=entry['path']
            if not allowed(name) or name.casefold() in seen or type(entry['size']) is not int or entry['size']<0 or not re.fullmatch('[a-f0-9]{64}',entry['sha256']):raise ValueError('Manifesto de atualização inválido.')
            seen.add(name.casefold())
        if sum(e['size'] for e in files)>MAX_PACKAGE:raise ValueError('Pacote maior que o limite permitido.')
        required={'studio_launcher.py','release_info.py','update_core.py','release_crypto.py','studio_update_worker.py','studio_ui/backend.py','studio_ui/qml/Main.qml'}
        if not required<={e['path'] for e in files}:raise ValueError('Pacote de aplicativo incompleto.')
        return payload
    except (KeyError,TypeError,UnicodeError) as exc:raise ValueError('Manifesto de atualização inválido.') from exc

def check_url(url):
    from urllib.parse import urlsplit
    parsed=urlsplit(url)
    if parsed.scheme!='https' or parsed.username or parsed.password or parsed.port not in (None,443) or parsed.hostname not in ('api.github.com','github.com','release-assets.githubusercontent.com','objects.githubusercontent.com'):raise ValueError('Endereço de atualização não permitido.')
    return url
class _Redirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):return super().redirect_request(req,fp,code,msg,headers,check_url(newurl))
def fetch(url,limit,cancel=None,destination=None,progress=None):
    check_url(url);request=Request(url,headers={'User-Agent':'SubForgeAI-Studio/'+VERSION,'Accept':'application/vnd.github+json' if 'api.github.com' in url else 'application/octet-stream'})
    out=Path(destination).open('wb') if destination else None;chunks=[];count=0
    try:
        with build_opener(_Redirect()).open(request,timeout=30) as response:
            while chunk:=response.read(256*1024):
                if cancel and cancel.is_set():raise ValueError('Atualização cancelada.')
                count+=len(chunk)
                if count>limit:raise ValueError('Download maior que o tamanho permitido.')
                if out:out.write(chunk)
                else:chunks.append(chunk)
                if progress:progress(count,limit)
        return b''.join(chunks) if not out else count
    finally:
        if out:out.close()

def latest_release(cancel=None):
    try:data=json.loads(fetch('https://api.github.com/repos/'+REPOSITORY+'/releases/latest',2*1024*1024,cancel))
    except HTTPError as exc:
        if exc.code==404:return None
        if exc.code in (403,429):raise ValueError('O GitHub limitou as consultas. Tente novamente mais tarde.') from exc
        raise
    if data.get('draft') or data.get('prerelease'):raise ValueError('A release não é uma versão estável publicada.')
    tag=data.get('tag_name','');version=tag.removeprefix('v');version_tuple(version)
    prefix='https://github.com/'+REPOSITORY+'/releases/download/'+tag+'/'
    assets={a.get('name'):a for a in data.get('assets',[])};base='SubForgeAI-update-'+version
    required=[base+'.zip',base+'.manifest.json']
    for name in required:
        if name not in assets or assets[name].get('browser_download_url')!=prefix+name:raise ValueError('A release ainda não possui um pacote de atualização completo.')
    envelope=json.loads(fetch(prefix+required[1],2*1024*1024,cancel));payload=validate_envelope(envelope)
    if payload['version']!=version:raise ValueError('A versão do manifesto não corresponde à release.')
    return dict(version=version,notes=str(data.get('body') or '')[:60000],page='https://github.com/'+REPOSITORY+'/releases/tag/'+tag,zip_url=prefix+required[0],envelope=envelope)

def prepare(root,release,cancel=None,progress=None):
    root=Path(root).resolve();payload=validate_envelope(release['envelope'])
    if version_tuple(payload['version'])<=version_tuple(VERSION):raise ValueError('O pacote não é mais recente que a versão instalada.')
    job=internal_root(root)/'jobs'/uuid.uuid4().hex;job.mkdir(parents=True)
    required=sum(e['size'] for e in payload['files'])*3+payload['zip_size']+50*1024*1024
    if shutil.disk_usage(root).free<required:raise ValueError('Espaço insuficiente para atualizar com backup.')
    package=job/'package.zip';fetch(release['zip_url'],payload['zip_size'],cancel,package,progress)
    if package.stat().st_size!=payload['zip_size'] or file_sha(package)!=payload['zip_sha256']:raise ValueError('O pacote baixado falhou na verificação de integridade.')
    extract_verified(root,job,payload,package,cancel);save_json(job/'manifest.json',release['envelope']);return job
def extract_verified(root,job,payload,package,cancel=None):
    if file_sha(package)!=payload['zip_sha256'] or Path(package).stat().st_size!=payload['zip_size']:raise ValueError('O pacote baixado falhou na verificação de integridade.')
    expected={e['path']:e for e in payload['files']};seen=set();stage=Path(job)/'stage'
    with zipfile.ZipFile(package) as archive:
        if len(archive.infolist())!=len(expected):raise ValueError('O conteúdo do ZIP não corresponde ao manifesto.')
        for entry in archive.infolist():
            name=entry.filename
            if name not in expected or name.casefold() in seen or entry.is_dir() or (entry.external_attr>>16)&0o170000==0o120000 or entry.file_size!=expected[name]['size']:raise ValueError('O conteúdo do ZIP não corresponde ao manifesto.')
            safe_target(root,name);target=safe_target(stage,name)
            if cancel and cancel.is_set():raise ValueError('Atualização cancelada.')
            data=archive.read(entry)
            if sha(data)!=expected[name]['sha256']:raise ValueError('Arquivo do pacote com hash inválido.')
            write_bytes(target,data);seen.add(name.casefold())
    import ast
    module=ast.parse((stage/'release_info.py').read_text('utf-8'))
    versions=[ast.literal_eval(node.value) for node in module.body if isinstance(node,ast.Assign) and any(isinstance(target,ast.Name) and target.id=='VERSION' for target in node.targets)]
    if versions!=[payload['version']]:raise ValueError('A versão interna do pacote não corresponde ao manifesto.')


def job_path(root,job):
    root=Path(root).resolve();internal_root(root);job=Path(job).resolve()
    if job.parent!=root/'.updates/jobs' or not re.fullmatch('[a-f0-9]{32}',job.name):raise ValueError('Pasta de atualização inválida.')
    return job
def clear_code_cache(root,entries):
    root=Path(root).resolve()
    for entry in entries:
        source=safe_target(root,entry['path']);folder=source.parent/'__pycache__'
        if source.suffix!='.py' or not folder.is_dir() or folder.is_symlink() or not folder.resolve().is_relative_to(root):continue
        if getattr(folder.lstat(),'st_file_attributes',0)&0x400:continue
        for path in folder.glob(source.stem+'.*.pyc'):
            if path.is_symlink() or not path.resolve().is_relative_to(root):continue
            try:path.unlink()
            except OSError:pass
def rollback(root,job):
    root=Path(root).resolve();job=job_path(root,job);journal=json.loads((job/'journal.json').read_text('utf-8'))
    for entry in journal['entries']:
        target=safe_target(root,entry['path']);old=entry['old'];new=entry['new'];actual=file_sha(target) if target.is_file() else None
        if actual not in (old,new):raise ValueError('Um arquivo mudou após a atualização; a restauração foi interrompida.')
        if old is not None and file_sha(safe_target(job/'backup',entry['path']))!=old:raise ValueError('Backup de atualização corrompido.')
    for entry in reversed(journal['entries']):
        target=safe_target(root,entry['path'])
        if entry['old'] is not None:
            if target.is_file() and file_sha(target)==entry['old']:continue
            write_bytes(target,safe_target(job/'backup',entry['path']).read_bytes())
        elif target.exists():target.unlink()
    clear_code_cache(root,journal['entries']);journal['status']='rolled_back';save_json(job/'journal.json',journal);return journal
def apply(root,job,health=None):
    root=Path(root).resolve();job=job_path(root,job);payload=validate_envelope(json.loads((job/'manifest.json').read_text('utf-8')));entries=[]
    # All file hashes and targets are checked before the first modification.
    for entry in payload['files']:
        source=safe_target(job/'stage',entry['path']);target=safe_target(root,entry['path'])
        if file_sha(source)!=entry['sha256']:raise ValueError('Os arquivos preparados mudaram. Baixe o pacote novamente.')
        old=file_sha(target) if target.is_file() else None
        if old is not None:write_bytes(safe_target(job/'backup',entry['path']),target.read_bytes())
        entries.append(dict(path=entry['path'],old=old,new=entry['sha256']))
    journal=dict(status='applying',version=payload['version'],created=time.time(),entries=entries);save_json(job/'journal.json',journal)
    try:
        for entry in entries:
            target=safe_target(root,entry['path']);actual=file_sha(target) if target.is_file() else None
            if actual!=entry['old']:raise ValueError('A instalação mudou antes da substituição dos arquivos.')
            if entry['old']==entry['new']:continue
            write_bytes(target,safe_target(job/'stage',entry['path']).read_bytes())
        clear_code_cache(root,entries);journal['status']='validating';save_json(job/'journal.json',journal)
        if health and not health():raise ValueError('A nova versão não passou na verificação de inicialização.')
        journal['status']='committed';save_json(job/'journal.json',journal)
    except Exception:
        rollback(root,job);raise
    return journal

def live_pid(pid):
    if type(pid) is not int or pid<=0:return False
    if os.name=='nt':
        import ctypes
        api=ctypes.WinDLL('kernel32');api.OpenProcess.argtypes=[ctypes.c_ulong,ctypes.c_int,ctypes.c_ulong];api.OpenProcess.restype=ctypes.c_void_p;handle=api.OpenProcess(0x100000,False,pid)
        if not handle:return False
        try:
            api.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_ulong];return api.WaitForSingleObject(handle,0)==258
        finally:api.CloseHandle.argtypes=[ctypes.c_void_p];api.CloseHandle(handle)
    try:os.kill(pid,0);return True
    except OSError:return False
def recover(root,lease_owned=False):
    root=Path(root).resolve();lock=root/'.updates/install.lock'
    internal_root(root)
    pending=[p for p in (root/'.updates/jobs').glob('*/journal.json') if json.loads(p.read_text('utf-8')).get('status') in ('applying','validating')]
    recovered=[]
    # The OS file lease, not a reusable PID, proves whether an installer is alive.
    if (pending or lock.exists()) and not lease_owned:
        with app_lease(root,True):return recover(root,True)
    for journal in pending:rollback(root,journal.parent);recovered.append(str(journal.parent))
    if lock.exists():lock.unlink()
    return recovered
