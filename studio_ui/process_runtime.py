"""Portable worker environment, resource discovery and owned process control.

This module has no dependency on any GUI toolkit. Functions migrated from the
classic controller retain their process/cancellation behavior.
"""
from __future__ import annotations
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.request import urlopen
from embed_script import mux_softsub

APP_DIR = Path(__file__).resolve().parents[1]
WHISPER_SCRIPT = APP_DIR / 'whisper_script.py'
OLLAMA_SCRIPT = APP_DIR / 'ollama_script.py'
EXTRACT_SCRIPT = APP_DIR / 'extract_subs.py'
_ACTIVE_PROCS: set[subprocess.Popen] = set()
_ACTIVE_PROCS_LOCK = threading.Lock()
OLLAMA_BASE_URL = (os.environ.get('SUBFORGEAI_OLLAMA_BASE_URL') or 'http://127.0.0.1:11434').rstrip('/')


def runtime_python():
    """Prefer a configured interpreter, then the shipped worker interpreter."""
    try:
        cfg = json.loads((APP_DIR / 'config.json').read_text(encoding='utf-8-sig'))
        configured = cfg.get('runtime_python') if isinstance(cfg, dict) else None
        if configured:
            path = Path(configured).expanduser()
            if not path.is_absolute(): path = APP_DIR / path
            if path.is_file(): return str(path.resolve())
    except (OSError, ValueError, TypeError): pass
    for relative in ('runtime/python/python.exe', 'runtime/python.exe', 'runtime/python/bin/python'):
        path = APP_DIR / relative
        if path.is_file(): return str(path)
    raise FileNotFoundError('Python portátil não encontrado em runtime/python.')


def _subprocess_hide_window_kwargs() -> dict:
    """On Windows, prevent console windows from flashing when running helper commands."""
    if os.name != "nt":
        return {}
    kw: dict = {}
    try:
        kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    except Exception:
        kw["creationflags"] = 0x08000000
    try:
        si = subprocess.STARTUPINFO()
        si.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 1)
        si.wShowWindow = 0  # SW_HIDE
        kw["startupinfo"] = si
    except Exception:
        pass
    return kw


def _app_search_roots() -> list[Path]:
    """Pastas onde recursos do app podem estar, em ordem de preferência.

    Motivo: o .exe pode rodar tanto na raiz da distribuição quanto numa
    subpasta (por exemplo SubForgeAI_v2/), enquanto tools/, runtime/ e
    ollama_models/ continuam na raiz. Procurar também no diretório-pai evita
    "FFmpeg não encontrado" só porque o executável foi movido um nível.

    Ordem: APP_DIR, depois o pai (uma vez), e por fim _MEIPASS quando houver.
    Pastas repetidas ou inválidas são descartadas.
    """
    roots: list[Path] = []
    for cand in (
        APP_DIR,
        APP_DIR.parent,
        Path(getattr(sys, "_MEIPASS", "")) if getattr(sys, "_MEIPASS", None) else None,
    ):
        if cand is None:
            continue
        try:
            if cand not in roots and cand.is_dir():
                roots.append(cand)
        except OSError:
            pass
    return roots


def _find_local_ffmpeg_dir() -> Path | None:
    """Retorna a pasta que contém ffmpeg.exe (portable) se existir."""
    if os.name != "nt":
        return None
    suffixes = [
        ("tools", "ffmpeg"),
        ("tools", "ffmpeg", "bin"),
        ("runtime", "ffmpeg"),
        ("runtime", "ffmpeg", "bin"),
    ]
    for root in _app_search_roots():
        for parts in suffixes:
            d = root.joinpath(*parts)
            try:
                if (d / "ffmpeg.exe").is_file():
                    return d
            except OSError:
                pass
    return None


def _build_subprocess_env(python_exe: str | None = None) -> dict:
    """Ambiente controlado para subprocess (mais portável e previsível).

    - Força UTF-8
    - Evita user-site/global interferindo (principalmente em modo EXE)
    - Redireciona caches/modelos para dentro da pasta do app
    """
    env = os.environ.copy()

    # UTF-8 robusto
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"

    # Isolamento: evita pegar pacotes do User-Site (muito comum dar conflito)
    env.setdefault("PYTHONNOUSERSITE", "1")
    env.setdefault("PIP_DISABLE_PIP_VERSION_CHECK", "1")
    env.setdefault("PIP_NO_PYTHON_VERSION_WARNING", "1")
    env.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

    # Caches/modelos dentro do app (portabilidade)
    # IMPORTANTE: usa o cache já populado, procurando também na pasta-pai.
    # Se o .exe roda em SubForgeAI_v2/ e os modelos Whisper (5 GB) estão em
    # SubForgeAI/cache/, apontar para SubForgeAI_v2/cache faria o Whisper
    # rebaixar tudo de novo. Preferimos o cache que já tem conteúdo.
    def _pick_cache_root() -> str:
        candidates: list[Path] = []
        for root in _app_search_roots():
            candidates.append(root / "cache")
        populated = [c for c in candidates if (c / "hub").is_dir()]
        if populated:
            try:
                return str(max(populated, key=lambda c: len(list((c / "hub").iterdir()))).resolve())
            except Exception:
                return str(populated[0].resolve())
        return str((APP_DIR / "cache").resolve())

    cache_root = _pick_cache_root()
    try:
        Path(cache_root).mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    # Whisper costuma usar ~/.cache/whisper (via XDG_CACHE_HOME)
    env.setdefault("XDG_CACHE_HOME", cache_root)
    env.setdefault("HF_HOME", cache_root)
    env.setdefault("TRANSFORMERS_CACHE", cache_root)
    env.setdefault("TORCH_HOME", cache_root)
    env.setdefault("PADDLE_HOME", cache_root)

    # Se estivermos usando python de um venv, força PATH a priorizar o venv
    # (evita carregar DLLs/pacotes do Python global)
    try:
        if python_exe:
            p = Path(python_exe)
            if p.name.lower().startswith("python") and p.parent.name.lower() in ("scripts", "bin"):
                venv_root = p.parent.parent
                env.setdefault("VIRTUAL_ENV", str(venv_root))
                scripts_dir = str(p.parent)
                env["PATH"] = scripts_dir + os.pathsep + env.get("PATH", "")
    except Exception:
        pass

    # Limpa variáveis que costumam quebrar import/paths
    env.pop("PYTHONPATH", None)

    # ffmpeg portable (garante que subprocesses enxerguem o ffmpeg mesmo sem PATH global)
    ffdir = _find_local_ffmpeg_dir()
    if ffdir:
        p = str(ffdir)
        cur = env.get("PATH", "")
        parts = [x for x in cur.split(os.pathsep) if x]
        if not any(x.lower() == p.lower() for x in parts):
            env["PATH"] = p + os.pathsep + cur

    # Ollama (portable): garante que os subprocesses (ollama_script.py) falem com o mesmo server/porta
    try:
        env["OLLAMA_MODELS"] = str(OLLAMA_MODELS_DIR.resolve())
    except Exception:
        pass
    try:
        env["SUBFORGEAI_OLLAMA_BASE_URL"] = str(OLLAMA_BASE_URL)
    except Exception:
        pass

    return env


def _register_proc(p: subprocess.Popen) -> None:
    try:
        with _ACTIVE_PROCS_LOCK:
            _ACTIVE_PROCS.add(p)
    except Exception:
        pass


def _unregister_proc(p: subprocess.Popen) -> None:
    try:
        with _ACTIVE_PROCS_LOCK:
            _ACTIVE_PROCS.discard(p)
    except Exception:
        pass


def _kill_process_tree(pid: int) -> None:
    """Kill a process tree on Windows; best-effort."""
    if pid <= 0:
        return
    try:
        if os.name == "nt":
            # /T = terminate child processes, /F = force
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                **_subprocess_hide_window_kwargs(),
            )
        else:
            # POSIX best-effort
            os.kill(pid, 15)
    except Exception:
        pass


def kill_all_active_procs() -> None:
    """Terminate any subprocesses launched by the app (best-effort)."""
    try:
        with _ACTIVE_PROCS_LOCK:
            procs = list(_ACTIVE_PROCS)
    except Exception:
        procs = []
    for p in procs:
        try:
            if p.poll() is None:
                _kill_process_tree(getattr(p, "pid", 0) or 0)
                # A restricted environment may reject taskkill's process-tree
                # lookup even though we own this child's process handle.
                if p.poll() is None:
                    p.terminate()
        except Exception:
            pass


def _ensure_unbuffered_python_cmd(cmd: list[str]) -> list[str]:
    """If command starts with python, force unbuffered output (-u)."""
    try:
        if not cmd:
            return cmd
        exe = Path(cmd[0]).name.lower()
        if exe.startswith("python") and "-u" not in cmd[1:5]:
            return [cmd[0], "-u"] + cmd[1:]
    except Exception:
        pass
    return cmd


def run_capture(cmd: list[str], on_line, cwd: Path | None = None, cancel_event=None, resource_settings=None) -> int:
    """Executa um comando e streama stdout para a GUI (UTF-8 robusto)."""
    if cancel_event is not None and cancel_event.is_set():
        return 130
    cmd = _ensure_unbuffered_python_cmd(cmd)
    python_exe = cmd[0] if cmd else None
    env = _build_subprocess_env(python_exe)
    from maintenance_tools import resource_env,resources
    limits=resources(resource_settings or {})
    env.update(resource_env(limits))

    creationflags = 0
    if os.name == "nt":
        # Avoid spawning extra console windows + allow killing the whole tree on exit.
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

    if os.name=='nt' and limits['resource_background']:creationflags |= getattr(subprocess,'BELOW_NORMAL_PRIORITY_CLASS',0)
    p = subprocess.Popen(
        cmd,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        universal_newlines=True,
        env=env,
        creationflags=creationflags,
    )
    assert p.stdout is not None
    _register_proc(p)
    try:
        if cancel_event is not None and cancel_event.is_set():
            _kill_process_tree(p.pid)
        for line in p.stdout:
            on_line(line.rstrip("\n"))
        return p.wait()
    finally:
        _unregister_proc(p)


def _resolve_ollama_models_dir() -> Path:
    """Escolhe a pasta de modelos do Ollama, preferindo uma GRAVÁVEL.

    Por que a gravabilidade importa: além de ler os blobs, o Ollama precisa
    ESCREVER nessa pasta (manifests-v2, cache, locks). Se a pasta vier de uma
    cópia com permissões restritas, o servidor sobe mas /api/tags responde
    500 e a tradução falha.

    Ordem: ollama_models_v2 (cópia gravável), depois ollama_models.
    A varredura cobre APP_DIR e a pasta-pai, como no resto do app.
    """
    names = ("ollama_models_v2", "ollama_models")
    fallback: Path | None = None
    for root in _app_search_roots():
        for name in names:
            cand = root / name
            try:
                if not cand.is_dir():
                    continue
            except OSError:
                continue
            if fallback is None:
                fallback = cand
            try:
                # teste real de escrita: é o que o servidor precisa
                probe = cand / ".sf_write_probe"
                probe.write_text("x", encoding="utf-8")
                probe.unlink(missing_ok=True)
                return cand
            except OSError:
                continue
    if fallback is not None:
        return fallback
    return APP_DIR / "ollama_models"


def _ollama_url(path: str) -> str:
    if not path.startswith("/"):
        path = "/" + path
    return OLLAMA_BASE_URL + path


def _ollama_host_in_use(host: str, port: int) -> bool:
    try:
        import socket
        with socket.create_connection((host, port), timeout=0.15):
            return True
    except Exception:
        return False


def _pick_managed_ollama_host() -> str:
    """Pick a host:port for the managed server, avoiding collision with a tray/server already on 11434."""
    # Prefer default if free, else move to next ports.
    candidates = ["127.0.0.1:11434", "127.0.0.1:11435", "127.0.0.1:11436", "127.0.0.1:11437"]
    for hp in candidates:
        try:
            host, p = hp.split(":")
            port = int(p)
        except Exception:
            continue
        if not _ollama_host_in_use(host, port):
            return hp
    return "127.0.0.1:11435"


def _ollama_ps_models() -> tuple[bool, list[str]]:
    try:
        with urlopen(_ollama_url("/api/ps"), timeout=1) as r:
            if not (200 <= getattr(r, "status", 200) < 300):
                return (False, [])
            data = json.loads(r.read().decode("utf-8", errors="replace") or "{}")
            models = []
            for it in data.get("models", []) or []:
                m = (it.get("name") or it.get("model") or "").strip()
                if m:
                    models.append(m)
            return (True, models)
    except Exception:
        return (False, [])


def _find_ollama_cli() -> "Optional[str]":
    """Best-effort path resolution for 'ollama' on Windows (com cache)."""
    global _OLLAMA_CLI_CACHE
    try:
        if isinstance(_OLLAMA_CLI_CACHE, str) and _OLLAMA_CLI_CACHE:
            return _OLLAMA_CLI_CACHE
        if _OLLAMA_CLI_CACHE is False:
            return None
    except Exception:
        pass

    found: "Optional[str]" = None
    # 0) Preferir ollama.exe portátil junto do app.
    #    Varre APP_DIR e a pasta-pai (o .exe pode rodar numa subpasta, como
    #    SubForgeAI_v2/) e também subpastas comuns criadas por instaladores
    #    portáteis: bin/, app/, Ollama/, ollama/.
    #    O instalador oficial com /DIR="F:\SubForgeAI" costuma criar
    #    F:\SubForgeAI\bin\ollama.exe em vez de pôr o exe na raiz.
    try:
        subdirs = ("", "bin", "app", "Ollama", "ollama", "Ollama\\bin", "ollama\\bin")
        for root in _app_search_roots():
            for sub in subdirs:
                cand_local = (root / sub / "ollama.exe") if sub else (root / "ollama.exe")
                try:
                    if cand_local.is_file():
                        found = str(cand_local)
                        break
                except OSError:
                    pass
            if found:
                break
    except Exception:
        pass

    try:
        p = shutil.which("ollama")
        if p and not found:
            found = p
    except Exception:
        pass
    if not found:
        try:
            lad = os.environ.get("LOCALAPPDATA") or ""
            cand = Path(lad) / "Programs" / "Ollama" / "ollama.exe"
            if cand.exists():
                found = str(cand)
        except Exception:
            pass
    if not found:
        try:
            cand = Path("C:/Program Files/Ollama/ollama.exe")
            if cand.exists():
                found = str(cand)
        except Exception:
            pass

    try:
        _OLLAMA_CLI_CACHE = found if found else False
    except Exception:
        pass
    return found


def _ollama_api_unload(model: str, timeout: float = 2.0) -> tuple[bool, str]:
    """Ask Ollama server to unload a model by setting keep_alive=0.
    Returns (ok, info)."""
    model = (model or "").strip()
    if not model:
        return (False, "modelo vazio")
    try:
        from urllib.request import Request, urlopen  # local import (zero deps)
        url = _ollama_url("/api/generate")
        payload = {"model": model, "keep_alive": 0}
        data = json.dumps(payload).encode("utf-8")
        req = Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", errors="replace") or ""

        last = ""
        for line in raw.splitlines():
            if line.strip():
                last = line.strip()
        if not last:
            last = raw.strip()

        try:
            j = json.loads(last) if last else {}
        except Exception:
            j = {}
        reason = (j.get("done_reason") or "").strip()
        if reason == "unload":
            return (True, "unload")
        return (True, reason or "ok")
    except Exception as e:
        return (False, str(e))


def _release_translation_memory(log_fn=None) -> None:
    """Release the app's translation model before loading Whisper."""
    ok, names = _ollama_ps_models()
    if not ok:
        return
    for name in names:
        if name.split(":", 1)[0].split("/")[-1] == "translategemma":
            released, detail = _ollama_api_unload(name, timeout=30)
            if log_fn:
                log_fn(f"[INFO] TranslateGemma: liberar VRAM -> {released} ({detail})")


OLLAMA_MODELS_DIR = _resolve_ollama_models_dir()
