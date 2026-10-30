"""Pinned portable whisper.cpp Vulkan runtime and exact model downloads."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import zipfile
from studio_ui.gpu_policy import GPURequiredError

RUNTIME_URL = 'https://github.com/nyancodex/whisper-server-vulkan-windows/releases/download/v0.1.0/whisper-server-bundle.zip'
RUNTIME_SHA256 = '587d04a2805737436d134ab9e02c80437f41a7cb64018a7cd4d8f65a76a56af1'
RUNTIME_FILES = ('whisper-cli.exe', 'whisper-server.exe', 'whisper.dll', 'ggml.dll', 'ggml-base.dll', 'ggml-cpu.dll', 'ggml-vulkan.dll', 'MSVCP140.dll', 'VCRUNTIME140.dll', 'VCRUNTIME140_1.dll')
from whisper_audio import WHISPER_REPOSITORIES
MODELS = {name:'ggml-'+name+'.bin' for name in WHISPER_REPOSITORIES}


def model_path(root, model):
    if model not in MODELS: raise ValueError('Modelo Vulkan inválido.')
    return Path(root) / 'models/whispercpp' / MODELS[model]


def installed(root, model):
    path = model_path(root, model)
    marker = path.with_suffix('.verified.json')
    try:
        data = json.loads(marker.read_text(encoding='utf-8'))
        return path.is_file() and path.stat().st_size == data['size'] and all((Path(root)/'tools/whispercpp'/name).is_file() for name in RUNTIME_FILES)
    except (OSError, ValueError, KeyError): return False


def ensure_ready(root, model, progress, cancel):
    """Repair a missing Vulkan installation before a transcription starts."""
    root = Path(root)
    if not installed(root, model):
        progress('Preparando Whisper Vulkan: componentes ou modelo ausentes', 0)
        prepare(root, model, progress, cancel)
    if cancel.is_set():
        raise RuntimeError('Preparação interrompida.')
    if not installed(root, model):
        raise GPURequiredError('Preparação do Whisper Vulkan incompleta. Abra Preparar para começar e prepare o modelo Vulkan selecionado.')
    # A successful download alone does not prove hardware acceleration works.
    probe(root)
    return root/'tools/whispercpp/whisper-cli.exe', model_path(root, model)


def extract_runtime(archive, root):
    if hashlib.sha256(Path(archive).read_bytes()).hexdigest() != RUNTIME_SHA256:
        raise ValueError('Checksum inválido do Whisper Vulkan.')
    target = Path(root)/'tools/whispercpp'; target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        for name in RUNTIME_FILES:
            info = z.getinfo(name)  # Exact allowlist: no archive path is used as a destination.
            if info.file_size > 200 * 1024**2: raise ValueError('Componente Vulkan inválido.')
            temp = target/(name+'.new')
            with z.open(info) as source, temp.open('wb') as output: shutil.copyfileobj(source, output)
            temp.replace(target/name)


def prepare(root, model, progress, cancel):
    import requests
    from huggingface_hub import HfApi
    root = Path(root)
    target = model_path(root, model)
    def check():
        if cancel.is_set(): raise RuntimeError('Download interrompido. Você pode tentar novamente.')
    def fetch(url, path, total=0):
        check(); path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(path.suffix+'.part')
        with requests.get(url, stream=True, timeout=(10, 15)) as response:
            response.raise_for_status(); done=0
            with temp.open('wb') as output:
                for block in response.iter_content(1024*1024):
                    check(); output.write(block); done += len(block)
                    progress('Baixando Whisper Vulkan', min(.98, done/total) if total else 0)
        check(); temp.replace(path)
    check()
    from .setup_support import WHISPER_GUIDE
    if shutil.disk_usage(root).free < (WHISPER_GUIDE[model]['download_gb']+.5)*1024**3:
        raise ValueError('Espaço insuficiente para baixar o Whisper Vulkan selecionado.')
    archive = root/'cache/downloads/whisper-vulkan-v0.1.0.zip'
    if not archive.is_file() or hashlib.sha256(archive.read_bytes()).hexdigest()!=RUNTIME_SHA256:
        fetch(RUNTIME_URL, archive, 19616442)
    extract_runtime(archive, root)
    info = HfApi().model_info('ggerganov/whisper.cpp', files_metadata=True)
    entry = next(f for f in info.siblings if f.rfilename == MODELS[model])
    digest = entry.lfs.sha256 if entry.lfs else None
    if not digest or not re.fullmatch('[a-f0-9]{64}', digest): raise ValueError('O modelo oficial não forneceu SHA256.')
    def checksum(path):
        h=hashlib.sha256()
        with path.open('rb') as source:
            for chunk in iter(lambda:source.read(1024*1024),b''): check(); h.update(chunk)
        return h.hexdigest()
    if not target.is_file() or checksum(target)!=digest:
        fetch('https://huggingface.co/ggerganov/whisper.cpp/resolve/'+info.sha+'/'+MODELS[model], target, entry.size)
    if checksum(target)!=digest:
        target.unlink(missing_ok=True); raise ValueError('Checksum inválido do modelo Vulkan.')
    from pipeline_io import atomic_write_text
    atomic_write_text(target.with_suffix('.verified.json'),json.dumps(dict(size=target.stat().st_size,sha256=digest,revision=info.sha)))
    progress('Modelo disponível',1)


def probe(root):
    cli = Path(root)/'tools/whispercpp/whisper-cli.exe'
    if not cli.is_file() or not (cli.parent/'ggml-vulkan.dll').is_file():
        raise GPURequiredError('Prepare o Whisper Vulkan em Preparar para começar antes de transcrever nesta GPU.')
    result = subprocess.run([str(cli),'--help'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding='utf-8', errors='replace', timeout=30,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    devices=[]
    for index,name in re.findall(r'ggml_vulkan:\s*(\d+)\s*=\s*([^\r\n]+)',result.stdout):
        if not re.search(r'llvmpipe|lavapipe|swiftshader|software|basic render',name,re.I):
            devices.append(dict(index=int(index),name=name.split('|')[0].strip()))
    if not devices: raise GPURequiredError('Nenhuma GPU Vulkan de hardware foi detectada. Confira o driver; a IA não será executada em CPU.')
    # Prefer a non-NVIDIA device when present, since this path serves AMD/Intel.
    return next((d for d in devices if 'nvidia' not in d['name'].lower()),devices[0])


class VulkanWhisper:
    """Load first, verify the actual backend, then allow transcription requests."""
    def __init__(self, root, model, device):
        import socket, time
        import requests
        self.process = None
        self.log_path = Path(root)/('logs/studio/whisper_vulkan_'+str(os.getpid())+'.log')
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
        self.base='http://127.0.0.1:'+str(port)
        print('[GPU] Carregando Whisper Vulkan em '+self.base,flush=True)
        command=[str(Path(root)/'tools/whispercpp/whisper-server.exe'),
            '--host','127.0.0.1','--port',str(port),'-m',str(model),'-dev',str(device['index']),'-bs','5']
        try:
            with self.log_path.open('w',encoding='utf-8') as output:
                self.process=subprocess.Popen(command,stdout=output,stderr=output,cwd=root,
                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            deadline=time.monotonic()+180
            while time.monotonic()<deadline:
                log=self.log_path.read_text(encoding='utf-8',errors='replace')
                if self.process.poll() is not None: raise GPURequiredError('Whisper Vulkan não iniciou. Consulte '+str(self.log_path))
                if re.search(r'no GPU found|failed to initialize.*backend|failed to allocate',log,re.I):
                    raise GPURequiredError('Whisper Vulkan não conseguiu carregar o modelo na GPU. Libere VRAM; a CPU não será utilizada.')
                try:
                    response=requests.get(self.base+'/health',timeout=.5)
                    ready=response.status_code==200
                except requests.RequestException: ready=False
                if ready:
                    self.validate_log(log)
                    print('[GPU] Whisper Vulkan: '+device['name']+'; modelo carregado antes da inferência.',flush=True)
                    return
                time.sleep(.1)
            raise GPURequiredError('Whisper Vulkan demorou para carregar o modelo. Consulte '+str(self.log_path))
        except BaseException:
            self.close();raise

    @staticmethod
    def validate_log(log):
        if not re.search(r'whisper_backend_init_gpu[^\n]*using Vulkan\d* backend',log):
            raise GPURequiredError('Whisper não confirmou o backend Vulkan. Inferência bloqueada antes de enviar o áudio.')
        if re.search(r'whisper_model_load:[^\n]*CPU[^\n]*total size\s*=\s*[1-9]',log,re.I):
            raise GPURequiredError('Whisper carregou pesos na CPU; inferência bloqueada.')
        if re.search(r'no GPU found|failed to initialize.*backend|failed to allocate|fallback.*CPU',log,re.I):
            raise GPURequiredError('GPU Vulkan indisponível ou sem memória; inferência bloqueada.')

    def transcribe(self, audio, language, task, prompt):
        import requests
        self.validate_log(self.log_path.read_text(encoding='utf-8',errors='replace'))
        with Path(audio).open('rb') as source:
            response=requests.post(self.base+'/inference',files={'file':(Path(audio).name,source,'audio/wav')},
                data={'response_format':'srt','language':language or 'auto','translate':'true' if task=='translate' else 'false',
                      'prompt':prompt,'temperature':'0.0'},timeout=(10,3600))
        response.raise_for_status()
        self.validate_log(self.log_path.read_text(encoding='utf-8',errors='replace'))
        result=response.content.decode("utf-8-sig")
        if '-->' not in result: raise GPURequiredError('Whisper Vulkan não retornou uma legenda SRT válida.')
        return result

    def close(self):
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait()
