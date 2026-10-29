"""Portable environment checks and explicit, cancellable model preparation."""
from pathlib import Path
import json
import os
import shutil
import socket
import subprocess
import time

# Download sizes from https://ollama.com/library/translategemma (Q4_K_M).
# VRAM ranges are planning estimates for short subtitle contexts, not benchmarks.
TRANSLATION_MODELS = {
    'translategemma:4b': dict(name='TranslateGemma 4B', download_gb=3.3, disk_gb=5,
        vram='4–6 GB', recommended_gb=6, description='Menor uso de memória; opção para máquinas mais modestas.',
        gpus='NVIDIA: RTX 2060 6 GB · AMD: RX 7600 8 GB · Intel: Arc A750 8 GB'),
    'translategemma:12b': dict(name='TranslateGemma 12B', download_gb=8.1, disk_gb=10,
        vram='10–12 GB', recommended_gb=12, description='Padrão do projeto; equilíbrio entre capacidade e uso de memória.',
        gpus='NVIDIA: RTX 3060 12 GB / RTX 5070 12 GB · AMD: RX 7800 XT 16 GB · Intel: Arc A770 16 GB / B580 12 GB'),
    'translategemma:27b': dict(name='TranslateGemma 27B', download_gb=17, disk_gb=21,
        vram='20–24 GB', recommended_gb=24, description='Maior exigência de memória; qualidade e velocidade precisam ser comparadas no seu conteúdo.',
        gpus='NVIDIA: RTX 3090 / 4090 24 GB · AMD: RX 7900 XTX 24 GB · Intel: modelos com 24 GB ou mais, sujeitos a validação'),
}


from whisper_audio import WHISPER_REPOSITORIES
MODELS = WHISPER_REPOSITORIES
# Conservative planning ranges for single-file FP16 inference, not measured limits.
# Reference: upstream Whisper model table and Faster-Whisper benchmarks; engines differ.
WHISPER_GUIDE = {
    'tiny': dict(name='Whisper Tiny',download_gb=.08,vram='1–2 GB',recommended_gb=3,
        description='Mais leve; menor precisão, especialmente em japonês com música ou efeitos.',
        gpus='NVIDIA: GTX 1650 4 GB · AMD: RX 6600 8 GB · Intel: Arc A380 6 GB'),
    'base': dict(name='Whisper Base',download_gb=.15,vram='1–2 GB',recommended_gb=3,
        description='Leve; melhora o reconhecimento em relação ao Tiny, com limitações em falas difíceis.',
        gpus='NVIDIA: GTX 1650 4 GB · AMD: RX 6600 8 GB · Intel: Arc A380 6 GB'),
    'small': dict(name='Whisper Small',download_gb=.49,vram='2–3 GB',recommended_gb=4,
        description='Opção intermediária para pouca VRAM; pode perder nomes e falas rápidas.',
        gpus='NVIDIA: GTX 1650 4 GB · AMD: RX 6600 8 GB · Intel: Arc A380 6 GB'),
    'medium': dict(name='Whisper Medium',download_gb=1.53,vram='3–5 GB',recommended_gb=6,
        description='Mais capacidade que Small; exige mais memória e pode ser mais lento que Turbo.',
        gpus='NVIDIA: RTX 2060 6 GB · AMD: RX 6600 8 GB · Intel: Arc A750 8 GB'),
    'large-v3-turbo': dict(name='Whisper Large v3 Turbo',download_gb=1.63,vram='3–6 GB',recommended_gb=8,
        description='Prioriza velocidade com boa capacidade de reconhecimento; padrão do projeto.',
        gpus='NVIDIA: RTX 3060 Ti 8 GB · AMD: RX 6600 8 GB · Intel: Arc A750 8 GB'),
    'large-v3': dict(name='Whisper Large v3',download_gb=3.1,vram='5–10 GB',recommended_gb=12,
        description='Modelo mais completo desta seleção; prioriza reconhecimento e exige mais recursos.',
        gpus='NVIDIA: RTX 3060 12 GB / RTX 5070 12 GB · AMD: RX 6700 XT 12 GB · Intel: Arc A770 16 GB / B580 12 GB'),
}



def inspect(root, translation_model="translategemma:12b"):
    if translation_model not in TRANSLATION_MODELS:
        raise ValueError("Modelo de tradução inválido.")
    from whisper_audio import local_faster_model
    root = Path(root)
    required = ['runtime/python/python.exe', 'runtime/python/pythonw.exe',
                'tools/ffmpeg/ffmpeg.exe', 'tools/ffmpeg/ffprobe.exe', 'ollama.exe',
                'studio_ui/qml/qmldir']
    missing = [p for p in required if not (root / p).is_file()]
    translations = {}
    for model in TRANSLATION_MODELS:
        translation = root / 'ollama_models_v2/manifests/registry.ollama.ai/library/translategemma' / model.split(':')[1]
        ready = False
        try:
            manifest = json.loads(translation.read_text())
            digests = [item['digest'] for item in [manifest['config'], *manifest['layers']]]
            ready = all((root / 'ollama_models_v2/blobs' / d.replace(':', '-')).is_file() for d in digests)
        except (OSError, ValueError, KeyError, TypeError):
            pass
        translations[model] = ready
    from studio_ui.vulkan_support import installed
    return dict(whisper_vulkan={key:installed(root,key) for key in MODELS}, missing=missing, translation=translations[translation_model], translations=translations,
                whisper={key: Path(local_faster_model(key, root)).is_dir() for key in MODELS},
                free_gb=round(shutil.disk_usage(root).free / 1024**3, 1))


def download(root, model, progress, cancel):
    if model == "translation": model = "translategemma:12b"
    root = Path(root).resolve()
    if model in tuple('vulkan-'+key for key in MODELS):
        from studio_ui.vulkan_support import prepare
        prepare(root, model.removeprefix('vulkan-'), progress, cancel)
        return inspect(root)
    if model not in (*MODELS, *TRANSLATION_MODELS):
        raise ValueError('Modelo inválido.')
    def check():
        if cancel.is_set():
            raise RuntimeError('Download interrompido. Você pode tentar novamente.')
    check()
    needed = (TRANSLATION_MODELS[model]['disk_gb'] if model in TRANSLATION_MODELS else WHISPER_GUIDE[model]['download_gb']+0.5) * 1024**3
    if shutil.disk_usage(root).free < needed:
        raise ValueError('Espaço insuficiente para baixar o modelo.')
    if model in MODELS:
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
        with requests.post(base + '/api/pull', json={'model': model, 'stream': True},
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
        if not success or not inspect(root, model)['translation']:
            raise RuntimeError('Download incompleto. Tente novamente para retomar.')
        progress('Modelo disponível', 1)
        return inspect(root, model)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait()
