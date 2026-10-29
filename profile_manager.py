# -*- coding: utf-8 -*-
"""
profile_manager.py - Perfis + detecção RAM/VRAM para SubForgeAI

Objetivos:
- Mapear perfis fixos (Baixo/Médio/Alto/Ultra) -> Faster-Whisper + Ollama
- Detectar RAM total e GPU/VRAM (prioridade NVML/pynvml, fallback nvidia-smi)
- Sugerir um perfil com heurística simples e estável
- Definir device preferido:
    * Se GPU NVIDIA detectada -> "cuda" (sempre tenta)
    * Caso contrário -> "cpu"
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Dict, Tuple
import os
import subprocess


def _get_psutil():
    global _PSUTIL
    if _PSUTIL is None:
        try:
            import psutil  # type: ignore
            _PSUTIL = psutil
        except Exception:
            _PSUTIL = False  # type: ignore
    return None if _PSUTIL is False else _PSUTIL

def _get_pynvml():
    global _PYNVML
    if _PYNVML is None:
        try:
            import pynvml  # type: ignore
            _PYNVML = pynvml
        except Exception:
            _PYNVML = False  # type: ignore
    return None if _PYNVML is False else _PYNVML


_PSUTIL = None  # type: ignore

_PYNVML = None  # type: ignore


@dataclass
class HWInfo:
    ram_gb: float
    gpu_name: str
    vram_gb: float
    has_nvidia: bool


# Perfis exigidos (sem "médio plus")
KEY_TO_PROFILE: Dict[str, Dict[str, str]] = {
    "low": {
        "label": "Baixo",
        "whisper_model": "small",
        "ollama_model": "translategemma:12b",
    },
    "medium": {
        "label": "Médio (Recomendado)",
        "whisper_model": "large-v3-turbo",
        "ollama_model": "translategemma:12b",
    },
    "high": {
        "label": "Alto",
        "whisper_model": "large-v3",
        "ollama_model": "translategemma:12b",
    },
    "ultra": {
        "label": "Ultra",
        "whisper_model": "large-v3",
        "ollama_model": "translategemma:12b",
    },
}

PROFILE_LABELS = [v["label"] for v in KEY_TO_PROFILE.values()]
LABEL_TO_KEY = {v["label"]: k for k, v in KEY_TO_PROFILE.items()}


def _ram_total_bytes_windows() -> Optional[int]:
    """Fallback Windows sem psutil."""
    if os.name != "nt":
        return None
    try:
        import ctypes  # type: ignore

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        st = MEMORYSTATUSEX()
        st.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
            return int(st.ullTotalPhys)
    except Exception:
        return None
    return None


def detect_ram_gb() -> float:
    try:
        ps = _get_psutil()
        if ps is not None:
            total = float(getattr(ps, "virtual_memory")().total)
            return round(total / (1024 ** 3), 1)
    except Exception:
        pass

    b = _ram_total_bytes_windows()
    if b:
        return round(float(b) / (1024 ** 3), 1)

    return 0.0


def _detect_gpu_nvml() -> Tuple[str, float, bool]:
    """Retorna (gpu_name, vram_gb, has_nvidia)."""
    nv = _get_pynvml()
    if nv is None:
        return ("", 0.0, False)

    try:
        nv.nvmlInit()
        h = nv.nvmlDeviceGetHandleByIndex(0)
        name = nv.nvmlDeviceGetName(h)
        if isinstance(name, bytes):
            name = name.decode("utf-8", errors="replace")
        mem = nv.nvmlDeviceGetMemoryInfo(h)
        vram_gb = round(float(mem.total) / (1024 ** 3), 1)
        return (str(name), vram_gb, True)
    except Exception:
        return ("", 0.0, False)
    finally:
        try:
            nv.nvmlShutdown()
        except Exception:
            pass


def _find_nvidia_smi() -> Optional[str]:
    try:
        from shutil import which
        p = which("nvidia-smi")
        if p:
            return p
    except Exception:
        pass

    candidates = [
        r"C:\Windows\System32\nvidia-smi.exe",
        r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe",
        r"C:\Program Files (x86)\NVIDIA Corporation\NVSMI\nvidia-smi.exe",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def _detect_gpu_nvidia_smi() -> Tuple[str, float, bool]:
    smi = _find_nvidia_smi()
    if not smi:
        return ("", 0.0, False)

    cmd = [
        smi,
        "--query-gpu=name,memory.total",
        "--format=csv,noheader,nounits",
    ]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, timeout=1.5, universal_newlines=True)
        line = (out.strip().splitlines() or [""])[0].strip()
        if not line:
            return ("", 0.0, True)
        parts = [p.strip() for p in line.split(",")]
        name = parts[0] if parts else ""
        vram_mib = float(parts[1]) if len(parts) > 1 else 0.0
        vram_gb = round(vram_mib / 1024.0, 1)
        return (name, vram_gb, True)
    except Exception:
        return ("", 0.0, True)


def detect_hw() -> HWInfo:
    ram = detect_ram_gb()

    name, vram, has_nv = _detect_gpu_nvml()
    if not has_nv:
        name, vram, has_nv = _detect_gpu_nvidia_smi()

    return HWInfo(
        ram_gb=float(ram),
        gpu_name=(name or ""),
        vram_gb=float(vram),
        has_nvidia=bool(has_nv),
    )


def preferred_device(hw: HWInfo) -> str:
    # pedido: se tiver NVIDIA, sempre TENTAR CUDA
    return "cuda" if hw.has_nvidia else "cpu"


def suggest_profile_key(hw: HWInfo) -> str:
    """
    Heurística simples:
    Todos os perfis usam TranslateGemma 12B Q4_K_M.
    O perfil altera o Whisper; a tradução em hardware menor pode usar RAM/CPU.
    """
    ram = hw.ram_gb or 0.0
    vram = hw.vram_gb or 0.0

    if hw.has_nvidia:
        if vram >= 12.0 and ram >= 32.0:
            return "ultra"
        if vram >= 8.0 and ram >= 24.0:
            return "high"
        if vram >= 6.0 or ram >= 16.0:
            return "medium"
        return "low"

    if ram >= 24.0:
        return "high"
    if ram >= 16.0:
        return "medium"
    return "low"


def profile_summary(key: str) -> str:
    p = KEY_TO_PROFILE.get(key) or KEY_TO_PROFILE["medium"]
    return f'{p["label"]}: Faster-Whisper {p["whisper_model"]} + Ollama {p["ollama_model"]}'