"""Install the translation model in the portable model store."""
from pathlib import Path
import json
import os
import subprocess
import sys
import time
import requests

ROOT = Path(__file__).resolve().parents[1]
BASE = 'http://127.0.0.1:11439'
MODEL = 'translategemma:12b'


def main():
    env = os.environ.copy()
    env.update(OLLAMA_MODELS=str(ROOT / 'ollama_models_v2'),
               OLLAMA_HOST='127.0.0.1:11439',
               USERPROFILE=str(ROOT / '.ollama_home'), HOME=str(ROOT / '.ollama_home'),
               OLLAMA_MAX_LOADED_MODELS='1', OLLAMA_NUM_PARALLEL='1')
    log = (ROOT / 'build/translategemma_server.log')
    log.parent.mkdir(exist_ok=True)
    process = None
    try:
        try:
            requests.get(BASE + '/api/version', timeout=2).raise_for_status()
        except requests.RequestException:
            with log.open('ab') as output:
                process = subprocess.Popen([str(ROOT / 'ollama.exe'), 'serve'], env=env,
                    cwd=ROOT, stdout=output, stderr=output,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            for _ in range(30):
                try:
                    requests.get(BASE + '/api/version', timeout=2).raise_for_status()
                    break
                except requests.RequestException:
                    time.sleep(1)
            else:
                raise RuntimeError('Ollama não iniciou; consulte ' + str(log))
        last = None
        with requests.post(BASE + '/api/pull', json={'model': MODEL, 'stream': True},
                           stream=True, timeout=(10, 180)) as response:
            response.raise_for_status()
            success = False
            for line in response.iter_lines():
                if not line: continue
                data = json.loads(line)
                if data.get('error'): raise RuntimeError(data['error'])
                percent = int(data.get('completed', 0) * 100 / data['total']) if data.get('total') else None
                status = (data.get('status'), None if percent is None else percent // 5 * 5)
                if status != last:
                    print(status, flush=True); last = status
                success = data.get('status') == 'success'
            if not success: raise RuntimeError('Download incompleto.')
        details = requests.post(BASE + '/api/show', json={'model': MODEL}, timeout=30).json()
        print('DETAILS', json.dumps(details.get('details'), ensure_ascii=False), flush=True)
    finally:
        if process is not None:
            process.terminate()
            process.wait(timeout=30)


if __name__ == '__main__':
    main()
