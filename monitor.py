# -*- coding: utf-8 -*-
"""
monitor.py - Monitor leve para SubForgeAI
CPU/RAM via psutil + GPU/VRAM via NVML (pynvml) com fallback para nvidia-smi.
Objetivo: nunca deixar GPU Load como "—" por falha de NVML/PATH no app frozen.
"""
from __future__ import annotations

import os
import threading
import time
import warnings
import subprocess
import ctypes
from typing import Callable, Optional, Dict, Any

warnings.filterwarnings("ignore", category=FutureWarning)

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


class _NvmlCtypes:
    """Leitor NVML mínimo via ctypes, sem depender do pacote pynvml.

    Por que existe: sem pynvml o monitor caía no nvidia-smi, que em app
    windowed abre uma janela de console a cada segundo (a tela piscava).
    O NVML é uma DLL do próprio driver (nvml.dll / nvidia-ml), então dá para
    falar com ela diretamente.

    Compatível com a API pública usada pelo monitor:
      nvmlInit, nvmlDeviceGetHandleByIndex, nvmlDeviceGetName,
      nvmlDeviceGetTemperature, nvmlDeviceGetUtilizationRates,
      nvmlDeviceGetMemoryInfo, nvmlShutdown.

    Qualquer falha em qualquer etapa marca a instância como indisponível e
    as chamadas passam a levantar exceção — o chamador já trata isso.
    """

    NVML_TEMPERATURE_GPU = 0

    class _Utilization(ctypes.Structure):
        _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]

    class _Memory(ctypes.Structure):
        _fields_ = [
            ("total", ctypes.c_ulonglong),
            ("free", ctypes.c_ulonglong),
            ("used", ctypes.c_ulonglong),
        ]

    def __init__(self) -> None:
        if os.name != "nt":
            raise OSError("NVML ctypes loader é exclusivo do Windows")
        self._lib = None
        last_err: Optional[Exception] = None
        for name in ("nvml.dll", "nvidia-ml.dll", "nvml"):
            try:
                self._lib = ctypes.WinDLL(name)
                break
            except OSError as e:
                last_err = e
        if self._lib is None:
            raise OSError(f"NVML não encontrada: {last_err}")
        self._bound = False

    def _bind(self) -> None:
        if self._bound:
            return
        lib = self._lib
        lib.nvmlInit_v2.restype = ctypes.c_int
        lib.nvmlInit_v2.argtypes = []
        lib.nvmlShutdown.restype = ctypes.c_int
        lib.nvmlShutdown.argtypes = []
        lib.nvmlDeviceGetHandleByIndex_v2.restype = ctypes.c_int
        lib.nvmlDeviceGetHandleByIndex_v2.argtypes = [
            ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p)
        ]
        lib.nvmlDeviceGetName.restype = ctypes.c_int
        lib.nvmlDeviceGetName.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint
        ]
        lib.nvmlDeviceGetTemperature.restype = ctypes.c_int
        lib.nvmlDeviceGetTemperature.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_uint)
        ]
        lib.nvmlDeviceGetUtilizationRates.restype = ctypes.c_int
        lib.nvmlDeviceGetUtilizationRates.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(self._Utilization)
        ]
        lib.nvmlDeviceGetMemoryInfo.restype = ctypes.c_int
        lib.nvmlDeviceGetMemoryInfo.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(self._Memory)
        ]
        self._bound = True

    def nvmlInit(self) -> None:
        self._bind()
        rc = self._lib.nvmlInit_v2()
        if rc != 0:
            raise OSError(f"nvmlInit_v2 falhou (rc={rc})")

    def nvmlShutdown(self) -> None:
        if self._lib is not None:
            try:
                self._lib.nvmlShutdown()
            except Exception:
                pass

    def nvmlDeviceGetHandleByIndex(self, index: int):
        self._bind()
        handle = ctypes.c_void_p()
        rc = self._lib.nvmlDeviceGetHandleByIndex_v2(
            ctypes.c_uint(index), ctypes.byref(handle)
        )
        if rc != 0:
            raise OSError(f"nvmlDeviceGetHandleByIndex falhou (rc={rc})")
        return handle

    def nvmlDeviceGetName(self, handle):
        self._bind()
        buf = ctypes.create_string_buffer(96)
        rc = self._lib.nvmlDeviceGetName(handle, buf, ctypes.c_uint(len(buf)))
        if rc != 0:
            raise OSError(f"nvmlDeviceGetName falhou (rc={rc})")
        return buf.value.decode("utf-8", errors="replace")

    def nvmlDeviceGetTemperature(self, handle, sensor: int) -> float:
        self._bind()
        val = ctypes.c_uint()
        rc = self._lib.nvmlDeviceGetTemperature(
            handle, ctypes.c_int(sensor), ctypes.byref(val)
        )
        if rc != 0:
            raise OSError(f"nvmlDeviceGetTemperature falhou (rc={rc})")
        return float(val.value)

    def nvmlDeviceGetUtilizationRates(self, handle):
        self._bind()
        util = self._Utilization()
        rc = self._lib.nvmlDeviceGetUtilizationRates(handle, ctypes.byref(util))
        if rc != 0:
            raise OSError(f"nvmlDeviceGetUtilizationRates falhou (rc={rc})")
        return util

    def nvmlDeviceGetMemoryInfo(self, handle):
        self._bind()
        mem = self._Memory()
        rc = self._lib.nvmlDeviceGetMemoryInfo(handle, ctypes.byref(mem))
        if rc != 0:
            raise OSError(f"nvmlDeviceGetMemoryInfo falhou (rc={rc})")
        return mem

_PSUTIL = None  # type: ignore

_PYNVML = None  # type: ignore


def _safe_float(x):
    try:
        if x is None:
            return None
        return float(x)
    except Exception:
        return None


def _find_nvidia_smi() -> Optional[str]:
    """Localiza nvidia-smi mesmo quando PATH do app frozen é 'seco'."""
    try:
        from shutil import which
        p = which("nvidia-smi")
        if p:
            return p
    except Exception:
        pass

    # Caminhos comuns no Windows
    candidates = [
        r"C:\Windows\System32\nvidia-smi.exe",
        r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe",
        r"C:\Program Files (x86)\NVIDIA Corporation\NVSMI\nvidia-smi.exe",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


# Sinaliza que o nvidia-smi não deve mais ser tentado nesta execução.
# Motivo: em app windowed (console=False) cada subprocesso abre e fecha uma
# janela de console — chamá-lo a cada segundo fazia a tela piscar sem parar.
_SMI_DISABLED = {"flag": False}


def _subprocess_no_window_kwargs() -> dict:
    """Impede que subprocessos abram janela de console no Windows.

    CREATE_NO_WINDOW só existe no Windows; nos demais sistemas devolve {}.
    """
    kwargs: dict = {}
    if os.name == "nt":
        creationflags = 0
        creationflags |= getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        # DETACHED_PROCESS evita que o processo filho herde o console do pai.
        # Combinado com CREATE_NO_WINDOW garante que nada apareça na tela.
        kwargs["creationflags"] = creationflags
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0  # SW_HIDE
        kwargs["startupinfo"] = si
    return kwargs


def _gpu_util_from_nvidia_smi() -> Optional[float]:
    """
    Retorna utilização da GPU (0-100) via nvidia-smi.

    Preferimos isso como fallback porque algumas configs/GPUs retornam
    NVML_ERROR_NOT_SUPPORTED para utilization rates, mesmo com temp/mem
    funcionando.

    IMPORTANTE: esta função é chamada a cada tick do monitor. Se falhar
    (binário ausente, timeout, saída inesperada), ela se DESABILITA
    permanentemente para a sessão e passa a retornar None na hora, sem
    spawnar processo. Isso evita o piscar de janelas do console e o custo
    de iniciar um processo por segundo.
    """
    if _SMI_DISABLED["flag"]:
        return None

    smi = _find_nvidia_smi()
    if not smi:
        _SMI_DISABLED["flag"] = True
        return None

    # CSV sem header/unidades
    cmd = [
        smi,
        "--query-gpu=utilization.gpu",
        "--format=csv,noheader,nounits",
    ]
    try:
        # timeout curto pra não travar a UI
        out = subprocess.check_output(
            cmd,
            stderr=subprocess.STDOUT,
            timeout=1.2,
            universal_newlines=True,
            **_subprocess_no_window_kwargs(),
        )
        # pode vir com múltiplas GPUs -> pega a primeira linha
        line = (out.strip().splitlines() or [""])[0].strip()
        # line deve ser um número (ex: "12")
        v = _safe_float(line)
        if v is None:
            _SMI_DISABLED["flag"] = True
            return None
        # clamp
        if v < 0:
            v = 0.0
        elif v > 100:
            v = 100.0
        return float(v)
    except Exception:
        # Uma falha aqui tende a se repetir (driver ausente, permissão,
        # binário quebrado). Desliga o fallback em vez de tentar de novo
        # a cada segundo.
        _SMI_DISABLED["flag"] = True
        return None


class SystemMonitor:
    def __init__(self, on_update: Callable[[Dict[str, Any]], None], interval: float = 1.0):
        self.on_update = on_update
        self.interval = max(0.2, float(interval))
        self._stop = threading.Event()
        self._t: Optional[threading.Thread] = None

        self._nvml_ok = False
        self._nvml_handle = None
        self._nvml_api = None
        self._gpu_name = None

        self._init_nvml()

    def _init_nvml(self):
        nv = _get_pynvml()
        if nv is None:
            # pynvml não instalado: usa o leitor direto via ctypes.
            # Isso evita depender de nvidia-smi, que abria janelas de console
            # a cada segundo no app windowed (a tela piscava sem parar).
            try:
                nv = _NvmlCtypes()
            except Exception:
                self._nvml_ok = False
                self._nvml_handle = None
                self._gpu_name = None
                return
        try:
            nv.nvmlInit()
            h = nv.nvmlDeviceGetHandleByIndex(0)
            name = nv.nvmlDeviceGetName(h)
            if isinstance(name, bytes):
                name = name.decode("utf-8", errors="replace")
            self._nvml_handle = h
            self._gpu_name = str(name)
            self._nvml_ok = True
            self._nvml_api = nv
        except Exception:
            self._nvml_ok = False
            self._nvml_handle = None
            self._gpu_name = None

    def start(self):
        if self._t and self._t.is_alive():
            return
        self._stop.clear()
        self._t = threading.Thread(target=self._run, name="SystemMonitor", daemon=True)
        self._t.start()

    def stop(self):
        self._stop.set()
        try:
            if self._t:
                self._t.join(timeout=1.5)
        except Exception:
            pass
        # Libera a NVML; sem isso a DLL fica carregada até o processo morrer.
        api = getattr(self, "_nvml_api", None)
        if api is not None and hasattr(api, "nvmlShutdown"):
            try:
                api.nvmlShutdown()
            except Exception:
                pass
            self._nvml_ok = False
            self._nvml_api = None

    def _cpu_temp_best_effort(self) -> Optional[float]:
        try:
            ps = _get_psutil()
            if ps and hasattr(ps, "sensors_temperatures"):
                temps = ps.sensors_temperatures(fahrenheit=False) or {}
                vals = []
                for entries in temps.values():
                    for e in entries or []:
                        v = getattr(e, "current", None)
                        if isinstance(v, (int, float)) and v > 0:
                            vals.append(float(v))
                if vals:
                    return max(vals)
        except Exception:
            pass
        return None

    def _gpu_snapshot(self) -> dict:
        # defaults
        gpu_name = self._gpu_name or "—"
        gpu_temp = None
        vram_pct = None
        gpu_pct = None

        # Usa a MESMA instância NVML resolvida em _init_nvml (pynvml ou o
        # leitor ctypes). Antes daqui só se olhava _get_pynvml(), então o
        # fallback ctypes nunca era consultado e o código caía no
        # nvidia-smi a cada tick.
        nv = getattr(self, "_nvml_api", None) or _get_pynvml()
        if self._nvml_ok and nv is not None and self._nvml_handle is not None:
            sensor = getattr(nv, "NVML_TEMPERATURE_GPU", 0)
            try:
                gpu_temp = nv.nvmlDeviceGetTemperature(self._nvml_handle, sensor)
            except Exception:
                gpu_temp = None

            try:
                mem = nv.nvmlDeviceGetMemoryInfo(self._nvml_handle)
                used = float(getattr(mem, "used", 0.0))
                total = float(getattr(mem, "total", 0.0))
                vram_pct = (used / total) * 100.0 if total > 0 else None
            except Exception:
                vram_pct = None

            # GPU utilization (0-100) via NVML
            try:
                util = nv.nvmlDeviceGetUtilizationRates(self._nvml_handle)
                gpu_pct = getattr(util, "gpu", None)
            except Exception:
                gpu_pct = None

        # Se NVML não trouxe util, tenta nvidia-smi (auto-desabilita na 1ª falha)
        if gpu_pct is None:
            gpu_pct = _gpu_util_from_nvidia_smi()

        # Nunca deixar None no app (evita "—"): se não conseguir, cai pra 0.
        gpu_pct_f = _safe_float(gpu_pct)
        if gpu_pct_f is None:
            gpu_pct_f = 0.0

        return {
            "gpu_name": gpu_name,
            "gpu_temp": _safe_float(gpu_temp),
            "gpu_pct": float(max(0.0, min(100.0, gpu_pct_f))),
            "vram_pct": _safe_float(vram_pct),
        }

    def _run(self):
        try:
            ps = _get_psutil()
            if ps:
                ps.cpu_percent(interval=None)
        except Exception:
            pass

        while not self._stop.is_set():
            snap: Dict[str, Any] = {}
            try:
                ps = _get_psutil()
                if ps:
                    snap["cpu_pct"] = _safe_float(ps.cpu_percent(interval=None))
                    vm = ps.virtual_memory()
                    snap["ram_pct"] = _safe_float(getattr(vm, "percent", None))
            except Exception:
                snap["cpu_pct"] = None
                snap["ram_pct"] = None

            snap["cpu_temp"] = self._cpu_temp_best_effort()
            snap.update(self._gpu_snapshot())

            try:
                self.on_update(snap)
            except Exception:
                pass

            self._stop.wait(self.interval)
