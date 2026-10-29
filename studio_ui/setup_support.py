"""Portable environment checks and explicit, cancellable model preparation."""
from pathlib import Path
import json
import os
import shutil
import socket
import subprocess
import time

MODELS = {'large-v3': 'Systran/faster-whisper-large-v3',
          'large-v3-turbo': 'mobiuslabsgmbh/faster-whisper-large-v3-turbo'}


def inspect(root):
    from whisper_audio import local_faster_model
    root = Path(root)
    required = ['runtime/python/python.exe', 'runtime/python/pythonw.exe',
                'tools/ffmpeg/ffmpeg.exe', 'tools/ffmpeg/ffprobe.exe', 'ollama.exe',
                'studio_ui/qml/qmldir']
    missing = [p for p in required if not (root / p).is_file()]
    translation = root / 'ollama_models_v2/manifests/registry.ollama.ai/library/translategemma/12b'
    translation_ready = False
    try:
        manifest = json.loads(translation.read_text())
        digests = [item['digest'] for item in [manifest['config'], *manifest['layers']]]
        translation_ready = all((root / 'ollama_models_v2/blobs' / d.replace(':', '-')).is_file() for d in digests)
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return dict(missing=missing, translation=translation_ready,
                whisper={key: Path(local_faster_model(key, root)).is_dir() for key in MODELS},
                free_gb=round(shutil.disk_usage(root).free / 1024**3, 1))


def download(root, model, progress, cancel):
    root = Path(root).resolve()
    if model not in (*MODELS, 'translation'):
        raise ValueError('Modelo inválido.')
    def check():
        if cancel.is_set():
            raise RuntimeError('Download interrompido. Você pode tentar novamente.')
    check()
    needed = (10 if model == 'translation' else 4) * 1024**3
    if shutil.disk_usage(root).free < needed:
        raise ValueError('Espaço insuficiente para baixar o modelo.')
    if model != 'translation':
        from huggingface_hub import HfApi, hf_hub_download
        from tqdm.auto import tqdm
        repo = MODELS[model]
        info = HfApi().model_info(repo, files_metadata=True)
        names = {'model.bin', 'config.json', 'tokenizer.json', 'vocabulary.json', 'preprocessor_config.json'}
        files = [f for f in info.siblings if f.rfilename in names]
        if not {'model.bin', 'config.json', 'tokenizer.json'} <= {f.rfilename for f in files}:
            raise RuntimeError('O repositório do modelo está incompleto.')
        total = sum(f.size or 0 for f in files)
        completed = 0
        class Progress(tqdm):
            def update(self, n=1):
                check()
                result = super().update(n)
                progress('Baixando modelo de transcrição', min(1, (completed + self.n) / total) if total else 0)
                return result
        for f in files:
            check()
            progress('Baixando modelo de transcrição', completed / total if total else 0)
            hf_hub_download(repo, f.rfilename, revision=info.sha,
                            cache_dir=str(root / 'cache/hub'), tqdm_class=Progress)
            check()
            completed += f.size or 0
        # Pin this validated revision for local_faster_model, including offline launches.
        from pipeline_io import atomic_write_text
        ref = root / 'cache/hub' / ('models--' + repo.replace('/', '--')) / 'refs/main'
        ref.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(ref, info.sha)
        progress('Modelo disponível', 1)
        return inspect(root)
    import requests
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    base = f'http://127.0.0.1:{port}'
    env = os.environ.copy()
    home = root / '.ollama_home'; home.mkdir(exist_ok=True)
    env.update(OLLAMA_HOST=f'127.0.0.1:{port}', OLLAMA_MODELS=str(root / 'ollama_models_v2'),
               USERPROFILE=str(home), HOME=str(home), OLLAMA_NUM_PARALLEL='1')
    log = root / 'logs/studio/model_setup.log'; log.parent.mkdir(parents=True, exist_ok=True)
    with log.open('ab') as output:
        process = subprocess.Popen([str(root / 'ollama.exe'), 'serve'], cwd=root, env=env,
            stdout=output, stderr=output, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        for _ in range(100):
            check()
            if process.poll() is not None:
                raise RuntimeError('Ollama não iniciou. Consulte logs/studio/model_setup.log.')
            try:
                requests.get(base + '/api/version', timeout=1).raise_for_status()
                break
            except requests.RequestException:
                time.sleep(.2)
        else:
            raise RuntimeError('Ollama demorou para iniciar.')
        success = False
        with requests.post(base + '/api/pull', json={'model': 'translategemma:12b', 'stream': True},
                           stream=True, timeout=(10, 15)) as response:
            response.raise_for_status()
            for line in response.iter_lines(chunk_size=1024):
                check()
                if not line:
                    continue
                data = json.loads(line)
                if data.get('error'):
                    raise RuntimeError(data['error'])
                progress('Baixando modelo de tradução', data.get('completed', 0) / data['total'] if data.get('total') else 0)
                success = data.get('status') == 'success'
        if not success or not inspect(root)['translation']:
            raise RuntimeError('Download incompleto. Tente novamente para retomar.')
        progress('Modelo disponível', 1)
        return inspect(root)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait()
