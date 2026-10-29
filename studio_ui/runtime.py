"""Adapt toolkit-independent process helpers, with a portable, observable Ollama startup."""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path
from urllib.request import urlopen


class Runtime:
    def __init__(self, processes, root):
        self.processes, self.root = processes, Path(root)
        self._server = None
        self._lock = threading.Lock()
        self._resources={}

    def __getattr__(self, name):
        return getattr(self.processes, name)

    def configure_resources(self,settings):
        from maintenance_tools import resources
        self._resources=resources(settings)
        if os.name=='nt' and self._server is not None and self._server.poll() is None:
            try:import psutil
            except ImportError:return
            try:
                psutil.Process(self._server.pid).nice(psutil.BELOW_NORMAL_PRIORITY_CLASS if self._resources['resource_background'] else psutil.NORMAL_PRIORITY_CLASS)
            except (OSError,psutil.Error):pass
    def run_capture(self,cmd,on_line,cwd=None,cancel_event=None):
        return self.processes.run_capture(cmd,on_line,cwd=cwd,cancel_event=cancel_event,resource_settings=self._resources)

    def runtime_python(self):
        path = Path(self.processes.runtime_python())
        console = path.with_name('python.exe')
        return str(console) if path.name.lower() == 'pythonw.exe' and console.is_file() else str(path)

    def _tags(self):
        try:
            with urlopen(self.processes.OLLAMA_BASE_URL + '/api/tags', timeout=.7) as response:
                data = json.loads(response.read().decode('utf-8'))
            return [item.get('name') or item.get('model') for item in data.get('models', [])]
        except (OSError, ValueError):
            return []

    def _ensure_ollama_ready(self, log_fn=None, required_model=None, cancel_event=None):
        log = log_fn or (lambda text: None)
        def cancelled(): return cancel_event is not None and cancel_event.is_set()
        if cancelled(): return False
        self._export_environment()
        if required_model in self._tags(): return True
        with self._lock:
            if self._server is None or self._server.poll() is not None:
                cli = self.processes._find_ollama_cli()
                if not cli:
                    log('[ERRO] Ollama não encontrado na instalação portátil.')
                    return False
                host = self.processes._pick_managed_ollama_host()
                self.processes.OLLAMA_BASE_URL = 'http://' + host
                home = self.root / '.ollama_home'
                home.mkdir(parents=True, exist_ok=True)
                from maintenance_tools import resource_env
                env = os.environ.copy();env.update(resource_env(self._resources))
                from studio_ui.gpu_policy import cuda_available, ollama_environment
                vulkan = not cuda_available()
                env.update(ollama_environment(vulkan))
                log('[GPU] Ollama: '+('Vulkan' if vulkan else 'CUDA')+'; inferência exige modelo integral na GPU.')
                env.update(OLLAMA_HOST=host, OLLAMA_MODELS=str(self.processes.OLLAMA_MODELS_DIR),
                           USERPROFILE=str(home), HOME=str(home),
                           OLLAMA_MAX_LOADED_MODELS='1', OLLAMA_NUM_PARALLEL='1')
                log_path = self.root / 'logs/studio/ollama_server.log'
                log_path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    with log_path.open('ab') as output:
                        self._server = subprocess.Popen([cli, 'serve'], cwd=self.root, env=env,
                            stdout=output, stderr=output,
                            **dict(self.processes._subprocess_hide_window_kwargs(),creationflags=self.processes._subprocess_hide_window_kwargs().get('creationflags',0) | (getattr(subprocess,'BELOW_NORMAL_PRIORITY_CLASS',0) if self._resources.get('resource_background') else 0)))
                except OSError as exc:
                    log(f'[ERRO] Não foi possível iniciar o Ollama: {exc}')
                    return False
                log(f'[INFO] Ollama portátil: {host}; registro em {log_path}')
            server = self._server
        self._export_environment()
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if cancelled():
                self._stop_managed_ollama_server(log_fn=log)
                return False
            if server.poll() is not None:
                log(f'[ERRO] Ollama encerrou (código {server.returncode}). Consulte logs/studio/ollama_server.log.')
                return False
            if required_model in self._tags():
                log('[OK] TranslateGemma disponível no Ollama local.')
                return True
            time.sleep(.15)
        log('[ERRO] Ollama não disponibilizou o modelo. Consulte logs/studio/ollama_server.log.')
        return False

    def _export_environment(self):
        os.environ['SUBFORGEAI_OLLAMA_BASE_URL'] = self.processes.OLLAMA_BASE_URL
        os.environ['OLLAMA_MODELS'] = str(self.processes.OLLAMA_MODELS_DIR)

    def _stop_managed_ollama_server(self, log_fn=None):
        with self._lock:
            server, self._server = self._server, None
        if server is None or server.poll() is not None: return
        if log_fn: log_fn('[INFO] Encerrando o servidor Ollama iniciado pelo Studio.')
        self.processes._kill_process_tree(server.pid)
        try: server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.terminate()

