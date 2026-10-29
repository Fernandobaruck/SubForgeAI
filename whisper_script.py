# -*- coding: utf-8 -*-
from __future__ import annotations



# === Anti-hallucination (agressivo, sem custo de performance) ===
# Ajusta cortes em trechos silenciosos e filtra saídas "doidas" (repetição/entropia alta).
# Obs: valores mais agressivos podem cortar fala muito baixa. Se ficar "comendo" diálogos,
# reduza NO_SPEECH ou aumente LOGPROB (mais negativo).
HALLU_NO_SPEECH = 0.50
HALLU_LOGPROB = -1.15
HALLU_COMPRESS = 2.40

# Faster-Whisper VAD (tende a REDUZIR alucinação em silêncio e pode até acelerar por pular trechos mudos)
FW_VAD_FILTER = True
FW_VAD_MIN_SILENCE_MS = 480
FW_VAD_THRESHOLD = 0.38

# === Modo "Trecho difícil" (preenche buracos grandes sem reprocessar o episódio inteiro) ===
# Heurística: se houver um gap grande entre segmentos (ex.: 8s+), reprocessa só aquele trecho
# com parâmetros mais permissivos (menos VAD / thresholds menos agressivos) e injeta os segmentos
# encontrados, sem alterar os segmentos já bons.
DIFFICULT_ENABLE = True
DIFFICULT_GAP_SEC = 5.5          # reprocessa gaps >= este valor
DIFFICULT_PAD_SEC = 0.35         # padding antes/depois do gap ao cortar áudio
DIFFICULT_MAX_GAPS = 16          # limite por arquivo (evita explosão de tempo)
DIFFICULT_MIN_CHUNK_SEC = 2.5    # não reprocessar pedaços minúsculos
DIFFICULT_OVERLAP_SKIP_SEC = 0.25  # não inserir se já houver segmento muito próximo
DIFFICULT_NO_SPEECH = 0.28       # mais permissivo no retry do gap
DIFFICULT_LOGPROB = -1.60
DIFFICULT_DISABLE_VAD = False

# === Retry de baixa confiança (corrige linhas truncadas/garbage sem reprocessar tudo) ===
LOWCONF_ENABLE = True
LOWCONF_SEG_LOGPROB = -1.00
LOWCONF_WORDPROB = 0.45
LOWCONF_PAD_SEC = 0.45
LOWCONF_MIN_DUR = 0.35
LOWCONF_MAX_DUR = 5.0
LOWCONF_MAX_WINDOWS = 14
LOWCONF_MERGE_GAP = 0.55

# === Resgate de falas curtas (janela com voz sem cobertura) ===
SHORT_RESCUE_ENABLE = True
SHORT_RESCUE_FRAME_MS = 20
SHORT_RESCUE_MIN_DUR = 0.22
SHORT_RESCUE_MAX_DUR = 2.20
SHORT_RESCUE_PRE_PAD_SEC = 0.22
SHORT_RESCUE_POST_PAD_SEC = 0.10
SHORT_RESCUE_COVER_PAD_SEC = 0.16
SHORT_RESCUE_JOIN_GAP_SEC = 0.12
SHORT_RESCUE_MAX_WINDOWS = 18
SHORT_RESCUE_OVERLAP_SKIP_SEC = 0.12
SHORT_RESCUE_MIN_TEXT_CORE = 2
SHORT_RESCUE_TARGET_MIN_DUR = 0.16
SHORT_RESCUE_TARGET_MAX_DUR = 1.60
SHORT_RESCUE_LOW_COVER_MAX = 0.22
SHORT_RESCUE_ZERO_COVER_MAX = 0.08
SHORT_RESCUE_ZERO_PRE_PAD_SEC = 0.26
SHORT_RESCUE_ZERO_POST_PAD_SEC = 0.16
SHORT_RESCUE_MIN_WINDOW_OVERLAP_SEC = 0.05
SHORT_RESCUE_MIN_CORE_WINDOW_RATIO = 0.22
SHORT_RESCUE_REPLACE_MAX_OLD_COVER = 0.16
SHORT_RESCUE_EDGE_GUARD_SEC = 0.04
SHORT_RESCUE_ULTRA_MAX_DUR = 1.05
SHORT_RESCUE_ULTRA_COVER_MAX = 0.14
SHORT_RESCUE_ULTRA_PRE_PAD_SEC = 0.30
SHORT_RESCUE_ULTRA_POST_PAD_SEC = 0.12
SHORT_RESCUE_ACCEPT_MIN_QUALITY = -1.52
SHORT_RESCUE_ACCEPT_MIN_AVG_WORDPROB = 0.33
SHORT_RESCUE_ACCEPT_MIN_AVG_LOGPROB = -2.10
SHORT_RESCUE_REPLACE_MIN_SCORE_GAIN = 0.08

# === Max Sync (timing super agressivo, sem GUI) ===
MAXSYNC_ENABLE = True
MAXSYNC_END_TRIM = 0.08  # corta 'cauda' no fim (segundos)
MAXSYNC_FALLBACK_END_TRIM = 0.12  # quando não há word timestamps
MAXSYNC_CLAMP_GAP = 0.02  # não invade o próximo segmento
MAXSYNC_MIN_DUR = 0.30
MAXSYNC_MAX_DUR = 4.5  # duração máxima por legenda (segundos)
MAXSYNC_GAP_SPLIT = 0.48
MAXSYNC_SHORT_WORD_DUR = 1.20
MAXSYNC_SHORT_END_TRIM = 0.03
  # evita duração 0 (segundos)

def _drop_unsupported_kwargs(fn, kwargs: dict):
    """Chama fn(**kwargs) e remove argumentos não suportados (compatibilidade entre versões)."""
    while True:
        try:
            return fn(**kwargs)
        except TypeError as e:
            msg = str(e)
            m = re.search(r"unexpected keyword argument '([^']+)'", msg)
            if not m:
                raise
            bad = m.group(1)
            if bad in kwargs:
                kwargs.pop(bad, None)
                continue
            raise
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import wave
from array import array
from pathlib import Path
from contextlib import ExitStack

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pipeline_io import atomic_write_text, reserve_output, temporary_workspace
from whisper_audio import inspect_audio, language_code, local_faster_model
from speech_context import write_context, load_speech_terms
from speech_refinement import timing_defects, candidate_decision, alignment_window_segments, replace_aligned_window

# diálogo: separar duas falas na mesma linha (ex.: '- ... - ...')
_DASH_CHARS = "-–—"


def _split_dual_speaker_inline(t: str) -> str:
    if not t or "\n" in t:
        return t
    s = (t or "").strip()
    if not s:
        return s

    if s[:1] in _DASH_CHARS:
        s = re.sub(r"^[" + re.escape(_DASH_CHARS) + r"]\s*", "- ", s)
        # split seguro: pontuação + segundo dash
        m = re.search(r"([.!?…]|\.{3})\s*([" + re.escape(_DASH_CHARS) + r"]\s+)", s[2:])
        if m:
            cut = 2 + m.start(2)
            left = s[:cut].rstrip()
            right = s[cut:].lstrip()
            right = re.sub(r"^[" + re.escape(_DASH_CHARS) + r"]\s*", "- ", right)
            return left + "\n" + right
        # fallback: segundo dash com espaço antes
        m2 = re.search(r"\s+([" + re.escape(_DASH_CHARS) + r"]\s+)(?=\S)", s[2:])
        if m2:
            cut = 2 + m2.start(1)
            left = s[:cut].rstrip()
            right = s[cut:].lstrip()
            right = re.sub(r"^[" + re.escape(_DASH_CHARS) + r"]\s*", "- ", right)
            return left + "\n" + right

    return s



def _configure_hf_cache(app_root: Path) -> None:
    """Fixar cache do HuggingFace dentro do projeto (portável).

    Mantém a estrutura padrão: <projeto>/cache/hub/...
    (Não desativa warnings de symlink.)
    """
    cache_root = (app_root / "cache").resolve()
    hub_root = cache_root / "hub"
    cache_root.mkdir(parents=True, exist_ok=True)
    hub_root.mkdir(parents=True, exist_ok=True)

    os.environ.setdefault("HF_HOME", str(cache_root))
    os.environ.setdefault("HF_HUB_CACHE", str(hub_root))
    os.environ.setdefault("HUGGINGFACE_HUB_CACHE", str(hub_root))


def have_ffmpeg() -> bool:
    """True se o ffmpeg está disponível (PATH ou portable em tools/ffmpeg)."""
    return resolve_ffmpeg() is not None



def resolve_ffmpeg() -> str | None:
    """Resolve ffmpeg path (portable first, then PATH)."""
    w = shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")
    if w:
        return w
    root = _find_project_root(Path(__file__).resolve())
    candidates = [
        root / "tools" / "ffmpeg" / "ffmpeg.exe",
        root / "runtime" / "ffmpeg" / "ffmpeg.exe",
        root / "ffmpeg.exe",
    ]
    for c in candidates:
        if c.exists() and c.is_file():
            return str(c)
    return None


def _find_project_root(start: Path) -> Path:
    cur = start
    for _ in range(6):
        if (cur / "config.json").exists() or (cur / "gui.py").exists():
            return cur
        cur = cur.parent
    return start


def _find_whispercpp_cli(root: Path) -> Path | None:
    candidates = [
        root / "tools" / "whispercpp" / "whisper-cli.exe",
        root / "tools" / "whispercpp" / "whisper-cli",
        root / "whisper-cli.exe",
        root / "whisper-cli",
    ]
    for c in candidates:
        if c.exists():
            return c
    # PATH
    p = shutil.which("whisper-cli") or shutil.which("whisper-cli.exe")
    if p:
        return Path(p)
    return None


def _whispercpp_model_path(root: Path, model_name: str) -> Path | None:
    # modelos whispercpp normalmente ficam em models/whispercpp/*.bin
    base = root / "models" / "whispercpp"
    if not base.exists():
        return None
    # tenta casar por nome
    normalized = model_name.strip().lower().replace("/", "-")
    for p in base.glob("*.bin"):
        if normalized in p.name.lower():
            return p
    # fallback: pega qualquer .bin
    any_bin = next(base.glob("*.bin"), None)
    return any_bin


def ffmpeg_extract_wav(inp: Path, out_wav: Path, stream_index: int | None = None) -> int:
    ff = resolve_ffmpeg()
    if not ff:
        print("[ERRO] ffmpeg não encontrado (tools/ffmpeg, runtime/ffmpeg ou PATH).")
        return 127
    cmd = [
        ff,
        "-y",
        "-i",
        str(inp),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-f",
        "wav",
        str(out_wav),
    ]
    if stream_index is not None:
        cmd[cmd.index('-vn'):cmd.index('-vn')] = ['-map', f'0:{stream_index}']
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        if p.returncode != 0:
            print(p.stderr.strip() or p.stdout.strip())
        return p.returncode
    except Exception as e:
        print(f"[ERRO] ffmpeg falhou: {e}")
        return 1


def ffmpeg_extract_hq_audio(inp: Path, out_wav: Path, stream_index: int | None = None) -> int:
    """Extract higher-quality audio for Demucs (44.1kHz stereo)."""
    ff = resolve_ffmpeg()
    if not ff:
        print("[ERRO] ffmpeg não encontrado (tools/ffmpeg, runtime/ffmpeg ou PATH).")
        return 127
    cmd = [
        ff,
        "-y",
        "-i",
        str(inp),
        "-vn",
        "-ac",
        "2",
        "-ar",
        "44100",
        "-f",
        "wav",
        str(out_wav),
    ]
    if stream_index is not None:
        cmd[cmd.index('-vn'):cmd.index('-vn')] = ['-map', f'0:{stream_index}']
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        if p.returncode != 0:
            print(p.stderr.strip() or p.stdout.strip())
        return p.returncode
    except Exception as e:
        print(f"[ERRO] ffmpeg falhou: {e}")
        return 1


def ffmpeg_to_whisper_wav(inp_audio: Path, out_wav: Path) -> int:
    """Convert an audio file to 16kHz mono wav for Whisper."""
    ff = resolve_ffmpeg()
    if not ff:
        print("[ERRO] ffmpeg não encontrado (tools/ffmpeg, runtime/ffmpeg ou PATH).")
        return 127
    cmd = [
        ff,
        "-y",
        "-i",
        str(inp_audio),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-f",
        "wav",
        str(out_wav),
    ]
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        if p.returncode != 0:
            print(p.stderr.strip() or p.stdout.strip())
        return p.returncode
    except Exception as e:
        print(f"[ERRO] ffmpeg falhou: {e}")
        return 1


def ffmpeg_cut_wav(inp_wav: Path, out_wav: Path, start_s: float, end_s: float) -> int:
    """Corta um trecho de WAV (16k/mono) via ffmpeg."""
    ff = resolve_ffmpeg()
    if not ff:
        print("[ERRO] ffmpeg não encontrado (tools/ffmpeg, runtime/ffmpeg ou PATH).")
        return 127
    start_s = max(0.0, float(start_s))
    end_s = max(start_s, float(end_s))
    cmd = [
        ff,
        "-y",
        "-ss", f"{start_s:.3f}",
        "-to", f"{end_s:.3f}",
        "-i", str(inp_wav),
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        "-f", "wav",
        str(out_wav),
    ]
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        if p.returncode != 0:
            print((p.stderr or p.stdout or "").strip())
        return p.returncode
    except Exception as e:
        print(f"[ERRO] ffmpeg_cut_wav falhou: {e}")
        return 1


def _merge_intervals(intervals: list[tuple[float, float]], *, pad: float = 0.0) -> list[tuple[float, float]]:
    if not intervals:
        return []
    pad = max(0.0, float(pad))
    ivs = [(max(0.0, s - pad), max(0.0, e + pad)) for s, e in intervals if e > s]
    ivs.sort(key=lambda x: x[0])
    out = [ivs[0]]
    for s, e in ivs[1:]:
        ps, pe = out[-1]
        if s <= pe:
            out[-1] = (ps, max(pe, e))
        else:
            out.append((s, e))
    return out


def _find_large_gaps_from_segments(seg_list: list[dict], wav_total: float) -> list[tuple[float, float]]:
    """Encontra gaps longos entre segmentos já transcritos."""
    if not seg_list or not wav_total or wav_total <= 0:
        return []
    intervals = []
    for s in seg_list:
        try:
            st = float(s.get("start", 0.0))
            en = float(s.get("end", st))
        except Exception:
            continue
        if en > st:
            intervals.append((st, en))
    intervals = _merge_intervals(intervals, pad=0.0)
    gaps: list[tuple[float, float]] = []
    last = 0.0
    for st, en in intervals:
        if st - last >= DIFFICULT_GAP_SEC:
            gaps.append((last, st))
        last = max(last, en)
    # tail
    if wav_total - last >= DIFFICULT_GAP_SEC:
        gaps.append((last, wav_total))
    # remove gaps muito pequenos
    gaps = [(s, e) for s, e in gaps if (e - s) >= DIFFICULT_MIN_CHUNK_SEC]
    return gaps


def _seg_overlaps_existing(new_seg: dict, existing: list[dict], *, min_overlap: float = DIFFICULT_OVERLAP_SKIP_SEC) -> bool:
    try:
        ns = float(new_seg.get("start", 0.0))
        ne = float(new_seg.get("end", ns))
    except Exception:
        return True
    for s in existing:
        try:
            es = float(s.get("start", 0.0))
            ee = float(s.get("end", es))
        except Exception:
            continue
        # overlap / near-duplicate
        if (min(ne, ee) - max(ns, es)) >= float(min_overlap):
            return True
    return False




def _interval_overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    return max(0.0, min(float(a_end), float(b_end)) - max(float(a_start), float(b_start)))


def _avg_word_probability(words: list[dict] | None) -> float | None:
    if not words:
        return None
    vals = []
    for w in words:
        try:
            p = w.get("prob", None)
        except Exception:
            p = None
        if p is None:
            continue
        try:
            vals.append(float(p))
        except Exception:
            pass
    if not vals:
        return None
    return sum(vals) / float(len(vals))


def _segment_to_dict(seg, *, offset_sec: float = 0.0) -> dict | None:
    try:
        start = float(getattr(seg, "start", 0.0)) + float(offset_sec)
        end = float(getattr(seg, "end", 0.0)) + float(offset_sec)
        text = str(getattr(seg, "text", "") or "")
        avg_logprob = getattr(seg, "avg_logprob", None)
        no_speech_prob = getattr(seg, "no_speech_prob", None)
    except Exception:
        return None

    seg_words = getattr(seg, "words", None)
    words_list = None
    if seg_words:
        try:
            words_list = []
            for w in seg_words:
                ws = float(getattr(w, "start", 0.0)) + float(offset_sec)
                we = float(getattr(w, "end", ws)) + float(offset_sec)
                ww = str(getattr(w, "word", "") or "")
                wp = getattr(w, "probability", None)
                words_list.append({"start": ws, "end": we, "word": ww, "prob": wp})
        except Exception:
            words_list = None

    return {
        "start": start,
        "end": end,
        "text": text,
        "avg_logprob": avg_logprob,
        "no_speech_prob": no_speech_prob,
        "avg_word_prob": _avg_word_probability(words_list),
        "words": words_list,
    }


def _transcribe_segments_to_list(segments, *, offset_sec: float = 0.0, wav_total: float = 0.0, progress_state: dict | None = None) -> list[dict]:
    out: list[dict] = []
    for seg in segments:
        item = _segment_to_dict(seg, offset_sec=offset_sec)
        if not item:
            continue
        out.append(item)

        if progress_state is not None and wav_total and wav_total > 0:
            end = float(item.get("end", 0.0))
            pct = (end / float(wav_total)) * 100.0
            now = time.time()
            if pct - float(progress_state.get("last_pct", -1.0)) >= 1.0 or (now - float(progress_state.get("last_print", 0.0))) >= 1.0 or pct >= 100.0:
                bar = _progress_bar(pct)
                print(f"[PROGRESS] {pct:6.2f}% [{bar}] {_fmt_clock(end)} / {_fmt_clock(wav_total)}")
                progress_state["last_pct"] = pct
                progress_state["last_print"] = now
    return out


def _build_faster_kwargs(
    *,
    language: str | None,
    task: str,
    word_timestamps: bool = True,
    no_speech_threshold: float = HALLU_NO_SPEECH,
    log_prob_threshold: float = HALLU_LOGPROB,
    compression_ratio_threshold: float = HALLU_COMPRESS,
    condition_on_previous_text: bool = False,
    hallucination_silence_threshold: float = 0.8,
    temperature: float = 0.0,
    vad_filter: bool = FW_VAD_FILTER,
    vad_min_silence_ms: int = FW_VAD_MIN_SILENCE_MS,
    vad_threshold: float = FW_VAD_THRESHOLD,
    beam_size: int = 5,
    best_of: int = 5,
    patience: float = 1.0,
) -> dict:
    kwargs = {
        "language": language,
        "task": task,
        "word_timestamps": word_timestamps,
        "no_speech_threshold": no_speech_threshold,
        "log_prob_threshold": log_prob_threshold,
        "compression_ratio_threshold": compression_ratio_threshold,
        "condition_on_previous_text": condition_on_previous_text,
        "hallucination_silence_threshold": hallucination_silence_threshold,
        "temperature": temperature,
        "beam_size": beam_size,
        "best_of": best_of,
        "patience": patience,
        "vad_filter": bool(vad_filter),
    }
    if vad_filter:
        kwargs["vad_parameters"] = {
            "min_silence_duration_ms": int(vad_min_silence_ms),
            "threshold": float(vad_threshold),
        }
    return kwargs


def _window_segments(seg_list: list[dict], start_s: float, end_s: float) -> list[dict]:
    out = []
    for seg in seg_list:
        if _interval_overlap(seg.get("start", 0.0), seg.get("end", 0.0), start_s, end_s) > 0.05:
            out.append(seg)
    return out


def find_stems_python(project_root: Path) -> Path | None:
    """Find the python executable for Demucs inside the project."""
    candidates: list[Path] = []
    if os.name == "nt":
        candidates.extend([
            project_root / "stems_venv" / "Scripts" / "python.exe",
            project_root / "runtime" / "python" / "python.exe",
        ])
    else:
        candidates.extend([
            project_root / "stems_venv" / "bin" / "python",
            project_root / "runtime" / "python" / "python",
        ])

    for cand in candidates:
        if cand.exists():
            return cand
    return None


def locate_vocals_file(stems_out_root: Path) -> Path | None:
    """Locate vocals.wav (or vocals.flac) produced by Demucs under stems_out_root."""
    try:
        for ext in ("wav", "flac", "mp3"):
            for p in stems_out_root.rglob(f"vocals.{ext}"):
                return p
    except Exception:
        return None
    return None


def run_demucs(
    stems_python: Path,
    hq_audio: Path,
    stems_out_root: Path,
    *,
    prefer_device: str = "cuda",
    project_root: Path,
) -> tuple[Path | None, str]:
    """Run Demucs (two-stems=vocals). Returns (vocals_path or None, message)."""
    env = os.environ.copy()
    cache_root = project_root / "cache"
    try:
        cache_root.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    env.setdefault("XDG_CACHE_HOME", str(cache_root))
    env.setdefault("TORCH_HOME", str(cache_root))
    ff = resolve_ffmpeg()
    if ff:
        env["PATH"] = str(Path(ff).parent) + os.pathsep + env.get("PATH", "")

    stems_out_root.mkdir(parents=True, exist_ok=True)

    def _cmd(device: str) -> list[str]:
        return [
            str(stems_python),
            "-m",
            "demucs",
            "--two-stems=vocals",
            "-d",
            device,
            "-o",
            str(stems_out_root),
            str(hq_audio),
        ]

    last_msg = ""
    for dev in (prefer_device, "cpu"):
        try:
            p = subprocess.run(_cmd(dev), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, env=env)
            if p.returncode == 0:
                vocals = locate_vocals_file(stems_out_root)
                if vocals and vocals.exists() and vocals.stat().st_size > 0:
                    return vocals, f"ok ({dev})"
                return None, f"Demucs terminou mas não achei vocals.* ({dev})"
            out = (p.stdout or "").strip()
            if out:
                tail = "\n".join(out.splitlines()[-12:])
                last_msg = f"Demucs falhou ({dev}). Últimas linhas:\n{tail}"
            else:
                last_msg = f"Demucs falhou ({dev}) (exit={p.returncode})."
        except Exception as e:
            last_msg = f"Demucs erro ({dev}): {e}"
    return None, last_msg




def _safe_unlink(p: Path, *, retries: int = 8, delay: float = 0.25) -> bool:
    """Tenta apagar arquivo no Windows com retry (evita wav sobrando por lock temporário)."""
    for _ in range(max(1, int(retries))):
        try:
            p.unlink()
            return True
        except FileNotFoundError:
            return True
        except PermissionError:
            time.sleep(delay)
        except Exception:
            break
    return False


def _safe_rmtree(d: Path, *, retries: int = 8, delay: float = 0.25) -> bool:
    """Remove diretório (recursivo) com retry — útil no Windows quando algum handle demora a soltar."""
    for _ in range(max(1, int(retries))):
        try:
            if not d.exists():
                return True
            shutil.rmtree(d)
            return True
        except FileNotFoundError:
            return True
        except PermissionError:
            time.sleep(delay)
        except Exception:
            break
    return False

def _pick_torch_device(dev: str) -> str:
    dev = (dev or "").strip().lower()
    if dev == "auto":
        dev = "cuda"
    if dev == "cuda":
        try:
            import torch  # type: ignore
            if torch.cuda.is_available():
                return "cuda"
        except Exception:
            pass
        return "cpu"
    return "cpu"


def _run_whispercpp(whisper_cli: Path, model_bin: Path, audio_wav: Path, out_prefix: Path, lang: str, force_cpu: bool) -> tuple[bool, str]:
    # whisper-cli -m model.bin -f input.wav -of outprefix -osrt -l ja
    cmd = [
        str(whisper_cli),
        "-m",
        str(model_bin),
        "-f",
        str(audio_wav),
        "-of",
        str(out_prefix),
        "-osrt",
    ]
    if lang and lang not in ("auto", "automatic"):
        cmd += ["-l", lang]
    if force_cpu:
        cmd += ["--no-gpu"]

    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
        out = p.stdout.strip()
        result_path = Path(str(out_prefix) + ".srt")
        ok = (p.returncode == 0) and result_path.exists() and "-->" in result_path.read_text(encoding="utf-8", errors="replace")
        return ok, out
    except Exception as e:
        return False, f"[ERRO] whispercpp falhou: {e}"


def _read_wav_mono_samples(wav_path: Path) -> tuple[int, array] | tuple[None, None]:
    try:
        with wave.open(str(wav_path), "rb") as wf:
            rate = int(wf.getframerate() or 0)
            channels = int(wf.getnchannels() or 1)
            width = int(wf.getsampwidth() or 2)
            frames = wf.getnframes()
            raw = wf.readframes(frames)
    except Exception:
        return None, None

    try:
        if width == 2:
            data = array("h")
            data.frombytes(raw)
        elif width == 1:
            src = array("B")
            src.frombytes(raw)
            data = array("h", ((int(v) - 128) << 8 for v in src))
        else:
            return None, None
    except Exception:
        return None, None

    if channels > 1:
        try:
            mono = array("h")
            for i in range(0, len(data), channels):
                mono.append(int(sum(data[i:i + channels]) / channels))
            data = mono
        except Exception:
            return None, None

    return rate, data


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    vals = sorted(float(v) for v in values)
    if len(vals) == 1:
        return vals[0]
    q = max(0.0, min(1.0, float(q)))
    pos = q * (len(vals) - 1)
    lo = int(pos)
    hi = min(len(vals) - 1, lo + 1)
    frac = pos - lo
    return vals[lo] * (1.0 - frac) + vals[hi] * frac


def _speech_rms_windows_from_wav(wav_path: Path) -> list[tuple[float, float]]:
    rate, samples = _read_wav_mono_samples(wav_path)
    if not rate or samples is None or not samples:
        return []

    frame_ms = max(10, int(SHORT_RESCUE_FRAME_MS))
    frame_len = max(1, int(rate * frame_ms / 1000.0))
    total = len(samples)
    rms_vals: list[float] = []
    times: list[tuple[float, float]] = []

    for i in range(0, total, frame_len):
        chunk = samples[i:i + frame_len]
        if not chunk:
            continue
        acc = 0.0
        for v in chunk:
            fv = float(v)
            acc += fv * fv
        rms = (acc / float(len(chunk))) ** 0.5
        start = float(i) / float(rate)
        end = float(min(total, i + len(chunk))) / float(rate)
        rms_vals.append(rms)
        times.append((start, end))

    if not rms_vals:
        return []

    p50 = _percentile(rms_vals, 0.50)
    p75 = _percentile(rms_vals, 0.75)
    p90 = _percentile(rms_vals, 0.90)
    thr = max(180.0, p50 * 2.4, p75 * 1.18)
    if p90 > 0:
        thr = min(thr, p90 * 0.92)

    voiced: list[tuple[float, float]] = []
    active_start = None
    last_voiced_end = 0.0

    for (start, end), rms in zip(times, rms_vals):
        is_voiced = rms >= thr
        if is_voiced:
            if active_start is None:
                active_start = start
            last_voiced_end = end
            continue

        if active_start is not None and (start - last_voiced_end) <= SHORT_RESCUE_JOIN_GAP_SEC:
            continue

        if active_start is not None:
            voiced.append((active_start, last_voiced_end))
            active_start = None

    if active_start is not None:
        voiced.append((active_start, last_voiced_end))

    return _merge_windows(
        [(s, e) for s, e in voiced if (e - s) >= SHORT_RESCUE_MIN_DUR and (e - s) <= SHORT_RESCUE_MAX_DUR],
        gap=SHORT_RESCUE_JOIN_GAP_SEC,
    )


def _coverage_ratio(window: tuple[float, float], intervals: list[tuple[float, float]]) -> float:
    ws, we = window
    span = max(0.001, float(we) - float(ws))
    covered = 0.0
    for s, e in intervals:
        covered += _interval_overlap(ws, we, s, e)
    return max(0.0, min(1.0, covered / span))


def _segment_intervals(seg_list: list[dict], *, pad: float = 0.0) -> list[tuple[float, float]]:
    return _merge_intervals(
        [
            (float(s.get("start", 0.0)), float(s.get("end", s.get("start", 0.0))))
            for s in seg_list
            if float(s.get("end", s.get("start", 0.0))) > float(s.get("start", 0.0))
        ],
        pad=pad,
    )


def _segment_window_coverage(window: tuple[float, float], seg_list: list[dict], *, pad: float = 0.0) -> float:
    return _coverage_ratio(window, _segment_intervals(seg_list, pad=pad))


def _find_short_rescue_windows(wav_path: Path, seg_list: list[dict], wav_total: float) -> list[tuple[float, float]]:
    if not SHORT_RESCUE_ENABLE or not wav_path or not Path(wav_path).exists() or wav_total <= 0:
        return []

    voiced_windows = _speech_rms_windows_from_wav(Path(wav_path))
    if not voiced_windows:
        return []

    covered = _segment_intervals(seg_list, pad=SHORT_RESCUE_COVER_PAD_SEC)

    picked: list[tuple[float, float, float, float]] = []
    for ws, we in voiced_windows:
        dur = max(0.0, we - ws)
        if dur < SHORT_RESCUE_MIN_DUR or dur > SHORT_RESCUE_MAX_DUR:
            continue

        cov = _coverage_ratio((ws, we), covered)

        wants_short_retry = (
            SHORT_RESCUE_TARGET_MIN_DUR <= dur <= SHORT_RESCUE_TARGET_MAX_DUR
            and cov <= SHORT_RESCUE_LOW_COVER_MAX
        )
        wants_zero_cover_retry = (
            dur <= SHORT_RESCUE_TARGET_MAX_DUR
            and cov <= SHORT_RESCUE_ZERO_COVER_MAX
        )
        wants_ultra_retry = (
            dur <= SHORT_RESCUE_ULTRA_MAX_DUR
            and cov <= SHORT_RESCUE_ULTRA_COVER_MAX
        )

        if not (wants_short_retry or wants_zero_cover_retry or wants_ultra_retry):
            continue

        if wants_ultra_retry:
            pre_pad = SHORT_RESCUE_ULTRA_PRE_PAD_SEC
            post_pad = SHORT_RESCUE_ULTRA_POST_PAD_SEC
        elif wants_zero_cover_retry:
            pre_pad = SHORT_RESCUE_ZERO_PRE_PAD_SEC
            post_pad = SHORT_RESCUE_ZERO_POST_PAD_SEC
        else:
            pre_pad = SHORT_RESCUE_PRE_PAD_SEC
            post_pad = SHORT_RESCUE_POST_PAD_SEC

        rs = max(0.0, ws - pre_pad)
        re = min(float(wav_total), we + post_pad)
        if (re - rs) < SHORT_RESCUE_MIN_DUR:
            continue

        # Prioridade: fala curtíssima/quase zero cobertura primeiro; depois menor cobertura e menor duração.
        priority = 0 if wants_ultra_retry else (1 if wants_zero_cover_retry else 2)
        picked.append((priority, cov, dur, rs, re))

    picked.sort(key=lambda x: (x[0], x[1], x[2], x[3]))
    merged = _merge_windows([(rs, re) for _priority, _cov, _dur, rs, re in picked], gap=0.06)
    return merged


def _core_window_for_rescue(window: tuple[float, float]) -> tuple[float, float]:
    ws, we = window
    guard = min(SHORT_RESCUE_EDGE_GUARD_SEC, max(0.0, (we - ws) * 0.12))
    cws = min(we, ws + guard)
    cwe = max(cws, we - guard)
    if cwe - cws < 0.08:
        return ws, we
    return cws, cwe


def _prepare_short_rescue_segments(new_segments: list[dict], window: tuple[float, float], wav_total: float) -> list[dict]:
    if not new_segments:
        return []

    ws, we = window
    cws, cwe = _core_window_for_rescue(window)
    min_core_overlap = max(
        SHORT_RESCUE_MIN_WINDOW_OVERLAP_SEC,
        min(0.18, (cwe - cws) * SHORT_RESCUE_MIN_CORE_WINDOW_RATIO),
    )

    filtered = filter_segments({"segments": new_segments, "audio_total": wav_total})
    kept: list[dict] = []
    for seg in filtered:
        txt = _normalize_transcript_text(seg.get("text", ""))
        seg["text"] = txt
        if _looks_suspicious_transcript_text(txt):
            continue
        if _looks_common_localized_hallucination(txt):
            continue
        if _token_core_len(txt) < SHORT_RESCUE_MIN_TEXT_CORE:
            continue

        avg_word_prob = seg.get("avg_word_prob", None)
        avg_logprob = seg.get("avg_logprob", None)
        try:
            if avg_word_prob is not None and float(avg_word_prob) < SHORT_RESCUE_ACCEPT_MIN_AVG_WORDPROB and _token_core_len(txt) < 4:
                continue
        except Exception:
            pass
        try:
            if avg_logprob is not None and float(avg_logprob) < SHORT_RESCUE_ACCEPT_MIN_AVG_LOGPROB and _token_core_len(txt) < 4:
                continue
        except Exception:
            pass
        if _segment_quality_score(seg) < SHORT_RESCUE_ACCEPT_MIN_QUALITY:
            continue

        ss = float(seg.get("start", 0.0))
        ee = float(seg.get("end", ss))
        seg_dur = max(0.0, ee - ss)
        core_ov = _interval_overlap(ss, ee, cws, cwe)
        full_ov = _interval_overlap(ss, ee, ws, we)

        if full_ov < SHORT_RESCUE_MIN_WINDOW_OVERLAP_SEC:
            continue
        if core_ov < min_core_overlap and seg_dur < 0.32 and _token_core_len(txt) < 3:
            continue
        if seg_dur < 0.16 and _token_core_len(txt) < 3:
            continue

        if not _seg_overlaps_existing(seg, kept, min_overlap=0.10):
            kept.append(seg)

    return kept


def _should_replace_short_rescue_window(window: tuple[float, float], old_segments: list[dict], new_segments: list[dict]) -> bool:
    if not new_segments:
        return False

    old_cov = _segment_window_coverage(window, old_segments, pad=0.0)
    new_cov = _segment_window_coverage(window, new_segments, pad=0.0)

    old_bad = sum(1 for s in old_segments if _looks_suspicious_transcript_text(_normalize_transcript_text(s.get("text", ""))))
    new_bad = sum(1 for s in new_segments if _looks_suspicious_transcript_text(_normalize_transcript_text(s.get("text", ""))))
    old_score = sum(_segment_quality_score({**s, "text": _normalize_transcript_text(s.get("text", ""))}) for s in old_segments) / float(len(old_segments) or 1)
    new_score = sum(_segment_quality_score({**s, "text": _normalize_transcript_text(s.get("text", ""))}) for s in new_segments) / float(len(new_segments) or 1)

    if old_cov <= SHORT_RESCUE_REPLACE_MAX_OLD_COVER and new_cov >= max(0.10, old_cov + 0.08) and new_score >= old_score - 0.02:
        return True

    if old_bad > new_bad and new_cov >= old_cov - 0.04 and new_score >= old_score + 0.02:
        return True

    if new_score >= old_score + SHORT_RESCUE_REPLACE_MIN_SCORE_GAIN and new_cov >= old_cov - 0.02:
        return True

    if _should_replace_window(old_segments, new_segments) and new_cov >= old_cov - 0.02 and new_score >= old_score + 0.02:
        return True

    return False


# =========================
# filtros / SRT
# =========================

def clean_text(t: str) -> str:
    t = (t or "").strip()
    t = re.sub(r"\s+", " ", t)
    return t.strip()



_JA_CHAR_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")
_ASCII_WORD_RE = re.compile(r"[A-Za-z]{1,}")
_ONLY_PUNCT_RE = re.compile(r"^[\W_]+$", re.UNICODE)
_REPEAT_CHAR_RE = re.compile(r"([^\s])\1{5,}")
_COMMON_LOCALIZED_HALLU_RE = re.compile(
    r"(ご視聴ありがとうございました|ご覧いただきありがとうございました|チャンネル登録(?:よろしく)?(?:お願いします)?|高評価(?:よろしく)?(?:お願いします)?|字幕(?:制作|翻訳))",
    re.UNICODE,
)
_LEADING_LAUGH_PREFIX_RE = re.compile(
    r"^(?:(?:えへ|へへ|ふふ|うふ|あは|ひひ){1,3}|(?:え|へ|ひ|ふ|う|あ|は){2,6})(?:[〜~ー…っッ、,.!?！？\s]*)+",
    re.UNICODE,
)


def _token_core_len(tok: str) -> int:
    core = re.sub(r"[\W_]+", "", (tok or ""), flags=re.UNICODE)
    return len(core)


def _looks_common_localized_hallucination(t: str) -> bool:
    s = (t or "").strip()
    if not s:
        return False
    return bool(_COMMON_LOCALIZED_HALLU_RE.search(s))


def _strip_leading_japanese_laugh_prefix(t: str) -> str:
    s = (t or "").strip()
    if not s:
        return s
    m = _LEADING_LAUGH_PREFIX_RE.match(s)
    if not m:
        return s
    rest = s[m.end():].strip()
    if not rest:
        return s
    if _token_core_len(rest) < 4:
        return s
    if not _JA_CHAR_RE.search(rest):
        return s
    return rest


def _normalize_transcript_text(t: str) -> str:
    s = clean_text(t)
    if not s:
        return s
    s = _strip_leading_japanese_laugh_prefix(s)
    s = _trim_obvious_trailing_fragment(s)
    return s.strip()


def _trim_obvious_trailing_fragment(t: str) -> str:
    s = (t or "").strip()
    if not s or " " not in s:
        return s
    toks = s.split()
    if len(toks) < 2:
        return s
    tail = toks[-1]
    body = "".join(toks[:-1])
    if not body:
        return s
    if _JA_CHAR_RE.search(body) and _token_core_len(body) >= 5 and _token_core_len(tail) <= 1 and not _ONLY_PUNCT_RE.match(tail):
        return " ".join(toks[:-1]).strip()
    return s


def _looks_repetitive_char_junk(t: str) -> bool:
    s = re.sub(r"\s+", "", (t or ""))
    if not s:
        return False
    if _REPEAT_CHAR_RE.search(s):
        return True
    uniq = set(s)
    if len(s) >= 8 and len(uniq) == 1:
        return True
    if len(s) >= 10 and len(uniq) <= 2:
        top = max(s.count(ch) for ch in uniq)
        if top / float(len(s)) >= 0.78:
            return True
    return False


def _looks_stray_single_char_line(t: str) -> bool:
    s = (t or "").strip()
    if not s:
        return True
    core = re.sub(r"[\W_]+", "", s, flags=re.UNICODE)
    if not core:
        return True
    # A single kana/kanji can be a complete word or interjection. Confidence
    # thresholds already select uncertain segments for retry; length alone
    # must never delete speech from the final transcript.
    return False


def _looks_suspicious_transcript_text(t: str) -> bool:
    s = (t or "").strip()
    if not s:
        return True
    toks = s.split()
    if _looks_common_localized_hallucination(s):
        return True
    if _ASCII_WORD_RE.search(s) and _JA_CHAR_RE.search(s):
        return True
    if _looks_repetitive_char_junk(s):
        return True
    if _looks_stray_single_char_line(s):
        return True
    if len(toks) >= 2 and _token_core_len(toks[-1]) <= 1 and _token_core_len("".join(toks[:-1])) >= 5:
        return True
    short_toks = sum(1 for tok in toks if 0 < _token_core_len(tok) <= 1)
    if len(toks) >= 3 and short_toks >= 2:
        return True
    return False


def _segment_quality_score(seg: dict) -> float:
    score = 0.0
    lp = seg.get("avg_logprob", None)
    wp = seg.get("avg_word_prob", None)
    try:
        score += float(lp)
    except Exception:
        score += -1.80
    try:
        score += max(-0.30, min(0.30, float(wp) - 0.50))
    except Exception:
        pass

    text = clean_text(seg.get("text", ""))
    if _looks_suspicious_transcript_text(text):
        score -= 0.45
    return score


def _accept_gap_candidate(seg: dict) -> bool:
    """New speech in an empty interval needs evidence, not just decoder output."""
    if _looks_suspicious_transcript_text(seg.get('text','')):
        return False
    try:
        if float(seg.get('no_speech_prob') or 0) > .65: return False
        probability = seg.get('avg_word_prob')
        if probability is not None and float(probability) < .45: return False
    except (TypeError, ValueError): return False
    return _segment_quality_score(seg) >= -1.0


def transcription_findings(segments: list[dict], language: str | None) -> list[dict]:
    """Expose uncertainty for review without deleting short legitimate speech."""
    findings = []
    for index, segment in enumerate(segments, 1):
        flags=[]
        probability=segment.get('avg_word_prob')
        if probability is not None and float(probability)<.55:flags.append('low_word_confidence')
        if segment.get('avg_logprob') is not None and float(segment['avg_logprob']) < -1.0:flags.append('low_decoder_confidence')
        text=segment.get('text','')
        if language=='ja' and not _JA_CHAR_RE.search(text) and len(_ASCII_WORD_RE.findall(text))>=3:
            flags.append('unexpected_latin_phrase')
        if flags:findings.append({'block':index,'start':segment['start'],'end':segment['end'],'text':text,'flags':flags})
    return findings


def _merge_windows(windows: list[tuple[float, float]], *, gap: float) -> list[tuple[float, float]]:
    if not windows:
        return []
    windows = sorted(windows, key=lambda x: x[0])
    merged = [windows[0]]
    for s, e in windows[1:]:
        ps, pe = merged[-1]
        if s <= pe + gap:
            merged[-1] = (ps, max(pe, e))
        else:
            merged.append((s, e))
    return merged


def _find_lowconf_windows(seg_list: list[dict]) -> list[tuple[float, float]]:
    windows: list[tuple[float, float]] = []
    for seg in seg_list:
        text = clean_text(seg.get("text", ""))
        start = float(seg.get("start", 0.0))
        end = float(seg.get("end", start))
        dur = max(0.0, end - start)
        avg_logprob = seg.get("avg_logprob", None)
        avg_word_prob = seg.get("avg_word_prob", None)

        lowconf = False
        if LOWCONF_MIN_DUR <= dur <= LOWCONF_MAX_DUR:
            if _looks_suspicious_transcript_text(text):
                lowconf = True
            else:
                try:
                    if avg_logprob is not None and float(avg_logprob) <= LOWCONF_SEG_LOGPROB:
                        lowconf = True
                except Exception:
                    pass
                try:
                    if (not lowconf) and avg_word_prob is not None and float(avg_word_prob) <= LOWCONF_WORDPROB:
                        lowconf = True
                except Exception:
                    pass

        if lowconf:
            windows.append((max(0.0, start - LOWCONF_PAD_SEC), end + LOWCONF_PAD_SEC))

    return _merge_windows(windows, gap=LOWCONF_MERGE_GAP)


def _should_replace_window(old_segments: list[dict], new_segments: list[dict]) -> bool:
    if not new_segments:
        return False
    old_score = sum(_segment_quality_score(s) for s in old_segments) / float(len(old_segments) or 1)
    new_score = sum(_segment_quality_score(s) for s in new_segments) / float(len(new_segments) or 1)

    old_bad = sum(1 for s in old_segments if _looks_suspicious_transcript_text(clean_text(s.get("text", ""))))
    new_bad = sum(1 for s in new_segments if _looks_suspicious_transcript_text(clean_text(s.get("text", ""))))

    if new_score >= old_score + 0.12:
        return True
    if new_bad < old_bad and new_score >= old_score - 0.03:
        return True
    return False


def looks_like_music(t: str) -> bool:
    s = t.strip().lower()
    if not s:
        return True
    # Only explicit non-dialogue markers; ordinary words and lyrics are kept.
    if re.fullmatch(r"(?:\[(?:music|música|instrumental)\]|\((?:music|música|instrumental)\))", s):
        return True
    if re.fullmatch(r"[♪\s\-–—_]+", s):
        return True
    return False


def is_timestamp_line(s: str) -> bool:
    return bool(re.match(r"^\d{2}:\d{2}:\d{2}[,.]\d{3}\s-->\s\d{2}:\d{2}:\d{2}[,.]\d{3}", s.strip()))


def _words_bounds(words: list[dict]) -> tuple[float, float] | None:
    """Retorna (start,end) baseado em words válidas."""
    if not words:
        return None
    # filtra words vazias
    w2 = []
    for w in words:
        ww = (w.get("word") or "").strip()
        if not ww:
            continue
        try:
            ws = float(w.get("start", 0.0))
            we = float(w.get("end", ws))
        except Exception:
            continue
        if we <= 0 and ws <= 0:
            continue
        w2.append((ws, we))
    if not w2:
        return None
    return (min(s for s, _ in w2), max(e for _, e in w2))


def _word_get(w, key: str, default=None):
    """Compat: words podem ser dicts ou objetos."""
    if isinstance(w, dict):
        return w.get(key, default)
    return getattr(w, key, default)

def _words_text(words: list) -> str:
    # Mantém espaçamento do whisper (muitos words vêm com espaço inicial)
    parts = []
    for w in words:
        s = _word_get(w, "word", "")
        if s is None:
            s = ""
        parts.append(str(s))
    return ("".join(parts)).strip()

def _split_by_words(words: list, max_dur: float, gap_split: float) -> list[list]:
    """Divide lista de words em blocos com duração limitada e cortes em pausas."""
    blocks = []
    cur = []
    if not words:
        return blocks
    japanese = bool(_JA_CHAR_RE.search(_words_text(words)))
    # normaliza ordenação
    words_sorted = sorted(words, key=lambda w: float(_word_get(w, "start", 0.0) or 0.0))
    cur_start = float(_word_get(words_sorted[0], "start", 0.0) or 0.0)
    last_end = float(_word_get(words_sorted[0], "end", cur_start) or cur_start)
    for i, w in enumerate(words_sorted):
        wstart = float(_word_get(w, "start", 0.0) or 0.0)
        wend = float(_word_get(w, "end", wstart) or wstart)
        if not cur:
            cur = [w]
            cur_start = wstart
            last_end = wend
            continue

        # gap para o word atual (a partir do anterior)
        gap = max(0.0, wstart - last_end)

        # duração se adicionarmos esse word
        new_dur = max(0.0, wend - cur_start)

        # corta se estourar duração ou se houver uma pausa grande (desde que já tenha algo razoável)
        duration_cut = new_dur > max_dur
        if japanese and duration_cut and new_dur <= max(12.0, max_dur):
            # Japanese tokenizer entries can be single kanji/syllables. A hard
            # 4.5-second cut can split 不調 into 不 / 調 and change translation.
            # Treat duration as soft until punctuation, a pause or the hard cap.
            duration_cut = bool(re.search(r'[。！？!?、][」』”\"]?\s*$', _words_text(cur)))
        if duration_cut or (gap >= gap_split and (last_end - cur_start) >= 0.9):
            blocks.append(cur)
            cur = [w]
            cur_start = wstart
            last_end = wend
        else:
            cur.append(w)
            last_end = wend

    if cur:
        blocks.append(cur)
    return blocks

def _tighten_maxsync(segs: list[dict], audio_total: float | None = None) -> list[dict]:
    """Aperta start/end e evita 'legenda presa' (abertura/silêncio) com cortes por word timestamps."""
    if not MAXSYNC_ENABLE:
        return segs

    # ordena por tempo
    segs = sorted(segs, key=lambda s: float(s.get("start", 0.0)))

    # 1) primeiro: cria segmentos "preliminares" já apertados, e quebra os muito longos
    prelim: list[dict] = []
    for seg in segs:
        text = str(seg.get("text", "") or "").strip()
        if not text:
            continue

        start0 = float(seg.get("start", 0.0))
        end0 = float(seg.get("end", start0))

        words = seg.get("words")
        if isinstance(words, list) and words:
            wb = _words_bounds(words)
            if wb:
                wstart, wend = wb
                # se é longo demais, quebra usando gaps e duração máxima
                dur_words = max(0.0, float(wend) - float(wstart))
                if dur_words > MAXSYNC_MAX_DUR:
                    blocks = _split_by_words(words, max_dur=MAXSYNC_MAX_DUR, gap_split=MAXSYNC_GAP_SPLIT)
                    for b in blocks:
                        if not b:
                            continue
                        bs = float(_word_get(b[0], "start", 0.0) or 0.0)
                        be = float(_word_get(b[-1], "end", bs) or bs)
                        s = max(0.0, bs)
                        e = max(s, be - MAXSYNC_END_TRIM)
                        t = _words_text(b)
                        if not t:
                            continue
                        new_seg = dict(seg)
                        new_seg["start"] = s
                        new_seg["end"] = e
                        new_seg["text"] = t
                        new_seg["words"] = b
                        prelim.append(new_seg)
                    continue  # já expandiu em blocos

                # curto/normal: usa bounds das palavras
                start = max(0.0, wstart)
                trim = MAXSYNC_SHORT_END_TRIM if dur_words <= MAXSYNC_SHORT_WORD_DUR else MAXSYNC_END_TRIM
                end = max(start, wend - trim)
                seg["start"] = start
                seg["end"] = end
                prelim.append(seg)
                continue

        # sem words: fallback
        end = max(start0, end0 - MAXSYNC_FALLBACK_END_TRIM)
        seg["start"] = start0
        seg["end"] = end
        prelim.append(seg)

    if not prelim:
        return []

    # 2) segunda passada: clamp com próximo, cap por duração do áudio, e duração mínima
    prelim = sorted(prelim, key=lambda s: float(s.get("start", 0.0)))
    out: list[dict] = []
    n = len(prelim)

    for i, seg in enumerate(prelim):
        start = float(seg.get("start", 0.0))
        end = float(seg.get("end", start))

        # clamp antes do próximo segmento
        if i < n - 1:
            next_start = float(prelim[i + 1].get("start", end))
            end = min(end, max(start, next_start - MAXSYNC_CLAMP_GAP))

        # cap pelo fim do áudio
        if audio_total and audio_total > 0:
            end = min(end, float(audio_total))

        # nunca deixa legenda enorme sem words (proteção extra)
        if (not isinstance(seg.get("words"), list)) and (end - start) > MAXSYNC_MAX_DUR:
            end = start + MAXSYNC_MAX_DUR

        # mínimo pra evitar flash e garantir SRT válido
        if end < start + MAXSYNC_MIN_DUR:
            end = start + MAXSYNC_MIN_DUR

        # Minimum display time must never override the hard timing limits.
        if i < n - 1:
            end = min(end, float(prelim[i + 1].get("start", end)) - MAXSYNC_CLAMP_GAP)
        if audio_total is not None and audio_total >= 0:
            end = min(end, float(audio_total))

        if end <= start:
            continue

        seg["start"] = start
        seg["end"] = end
        out.append(seg)

    return out



# --- Merge de segmentos muito curtos (melhora contexto e reduz traduções truncadas) ---
MERGE_SHORT_ENABLE = True
MERGE_SHORT_MAX_CHARS = 8          # ex.: "dizem", "já", "sim", "hã?"
MERGE_SHORT_MAX_WORDS = 2
MERGE_SHORT_MAX_DUR = 0.75         # duração do segmento curto
MERGE_SHORT_MAX_GAP = 0.55         # gap para colar no anterior
MERGE_SHORT_TOTAL_MAX_DUR = 5.0    # evita juntar e virar "sentença gigante"


def _is_short_text_for_merge(t: str) -> bool:
    t0 = (t or "").strip()
    if not t0:
        return True
    # remove pontuação para medir "conteúdo"
    core = re.sub(r"[\s\-—–…\.\,\!\?\:\;\"\'\(\)\[\]\{\}]+", "", t0)
    words = [w for w in re.split(r"\s+", t0) if w]
    # se quase não tem letras/dígitos, é curto demais
    if len(core) <= MERGE_SHORT_MAX_CHARS:
        return True
    if len(words) <= MERGE_SHORT_MAX_WORDS and len(t0) <= (MERGE_SHORT_MAX_CHARS + 6):
        return True
    return False


def _merge_short_segments(segs: list[dict]) -> list[dict]:
    if (not MERGE_SHORT_ENABLE) or not segs:
        return segs

    out: list[dict] = []
    for seg in sorted(segs, key=lambda s: float(s.get("start", 0.0))):
        text = str(seg.get("text", "") or "").strip()
        start = float(seg.get("start", 0.0))
        end = float(seg.get("end", start))

        if not out:
            out.append(seg)
            continue

        prev = out[-1]
        p_text = str(prev.get("text", "") or "").strip()
        p_start = float(prev.get("start", 0.0))
        p_end = float(prev.get("end", p_start))

        gap = start - p_end
        dur = max(0.0, end - start)
        total_dur = max(0.0, end - p_start)

        # só cola quando:
        # - segmento atual é curto (ou praticamente vazio)
        # - gap pequeno
        # - não vira segmento gigante
        # - não "puxa" abertura inteira (protegido por MAX_DUR)
        if (
            text
            and _is_short_text_for_merge(text)
            and gap >= -0.05
            and gap <= MERGE_SHORT_MAX_GAP
            and dur <= MERGE_SHORT_MAX_DUR
            and total_dur <= MERGE_SHORT_TOTAL_MAX_DUR
        ):
            # junta o texto de forma natural
            joiner = " "
            if p_text.endswith(("-", "—", "–")):
                joiner = ""  # hifenização já indica continuação
            elif p_text.endswith(("…", "...")):
                joiner = " "  # mantém espaço após reticências
            elif p_text.endswith((",", ";", ":")):
                joiner = " "
            # evita duplicar espaços
            merged_text = (p_text + joiner + text).strip()

            prev["text"] = merged_text
            prev["end"] = max(p_end, end)

            # mescla words quando possível
            pw = prev.get("words")
            cw = seg.get("words")
            if isinstance(pw, list) and isinstance(cw, list) and pw and cw:
                prev["words"] = pw + cw
            elif isinstance(pw, list) and pw:
                prev["words"] = pw
            elif isinstance(cw, list) and cw:
                prev["words"] = cw

            continue

        out.append(seg)

    return out



# --- Merge adicional para "micro-linhas" (após reduzir agressividade) ---
# Objetivo: dar mais contexto pro tradutor e reduzir legendas do tipo "Ma", "OK", "Sim" isoladas.
# Regras conservadoras: só cola quando gap é pequeno e não envolve linhas com múltiplos falantes (\n) ou marcadores de fala "- ".
MICRO_MERGE_ENABLE = True
MICRO_MERGE_MAX_CORE = 4          # tamanho do "núcleo" (sem pontuação) considerado micro
MICRO_MERGE_MAX_DUR = 0.85        # duração máxima do segmento micro
MICRO_MERGE_MAX_GAP = 0.35        # gap máximo para colar no vizinho
MICRO_MERGE_TOTAL_MAX_DUR = 6.0   # não deixar o bloco crescer demais


def _core_len_text(t: str) -> int:
    t0 = (t or "").strip()
    if not t0:
        return 0
    core = re.sub(r"[\s\-—–…\.,!?;:'\"“”‘’\(\)\[\]\{\}]+", "", t0)
    return len(core)


def _is_micro_for_merge(t: str) -> bool:
    if not t:
        return True
    if "\n" in t:
        return False
    s = t.strip()
    if s.startswith("- "):
        return False
    return _core_len_text(s) <= MICRO_MERGE_MAX_CORE


def _merge_micro_segments(segs: list[dict]) -> list[dict]:
    if (not MICRO_MERGE_ENABLE) or not segs:
        return segs

    segs = sorted(segs, key=lambda s: float(s.get("start", 0.0)))
    out: list[dict] = []
    i = 0
    n = len(segs)

    while i < n:
        cur = segs[i]
        c_text = str(cur.get("text", "") or "").strip()
        c_start = float(cur.get("start", 0.0))
        c_end = float(cur.get("end", c_start))
        c_dur = max(0.0, c_end - c_start)

        # se não é micro, só adiciona
        if (not c_text) or (not _is_micro_for_merge(c_text)) or (c_dur > MICRO_MERGE_MAX_DUR):
            out.append(cur)
            i += 1
            continue

        merged = False

        # 1) tenta colar no anterior (preferência)
        if out:
            prev = out[-1]
            p_text = str(prev.get("text", "") or "").strip()
            p_start = float(prev.get("start", 0.0))
            p_end = float(prev.get("end", p_start))
            gap = c_start - p_end
            total = max(0.0, c_end - p_start)
            if (
                p_text
                and ("\n" not in p_text)
                and (not p_text.startswith("- "))
                and gap >= -0.05
                and gap <= MICRO_MERGE_MAX_GAP
                and total <= MICRO_MERGE_TOTAL_MAX_DUR
            ):
                prev["text"] = (p_text + " " + c_text).strip()
                prev["end"] = max(p_end, c_end)

                # merge words se existirem
                pw = prev.get("words")
                cw = cur.get("words")
                if isinstance(pw, list) and isinstance(cw, list) and pw and cw:
                    prev["words"] = pw + cw
                elif isinstance(pw, list) and pw:
                    prev["words"] = pw
                elif isinstance(cw, list) and cw:
                    prev["words"] = cw

                merged = True

        if merged:
            i += 1
            continue

        # 2) senão, tenta colar no próximo (prepend) se for bem colado
        if i < n - 1:
            nxt = segs[i + 1]
            n_text = str(nxt.get("text", "") or "").strip()
            n_start = float(nxt.get("start", 0.0))
            n_end = float(nxt.get("end", n_start))
            gap2 = n_start - c_end
            total2 = max(0.0, n_end - c_start)
            if (
                n_text
                and ("\n" not in n_text)
                and (not n_text.startswith("- "))
                and gap2 >= -0.05
                and gap2 <= MICRO_MERGE_MAX_GAP
                and total2 <= MICRO_MERGE_TOTAL_MAX_DUR
            ):
                nxt["text"] = (c_text + " " + n_text).strip()
                nxt["start"] = min(c_start, n_start)

                # merge words se existirem
                cw = cur.get("words")
                nw = nxt.get("words")
                if isinstance(cw, list) and isinstance(nw, list) and cw and nw:
                    nxt["words"] = cw + nw
                elif isinstance(nw, list) and nw:
                    nxt["words"] = nw
                elif isinstance(cw, list) and cw:
                    nxt["words"] = cw

                # pula o cur (já incorporado no próximo)
                i += 1
                continue

        # 3) se não deu pra colar, mantém como está
        out.append(cur)
        i += 1

    return out


def filter_segments(result: dict) -> list[dict]:
    segs = result.get("segments") or []
    audio_total = result.get("audio_total", None)
    try:
        audio_total = float(audio_total) if audio_total is not None else None
    except Exception:
        audio_total = None

    out = []
    for seg in segs:
        text = _normalize_transcript_text(seg.get("text", ""))
        text = _split_dual_speaker_inline(text)
        text = _trim_obvious_trailing_fragment(text)
        if not text:
            continue
        if _looks_common_localized_hallucination(text):
            continue
        if _looks_repetitive_char_junk(text):
            continue
        if _looks_stray_single_char_line(text):
            continue
        # remove linhas óbvias de música/símbolos
        if looks_like_music(text):
            continue

        start = float(seg.get("start", 0.0))
        end = float(seg.get("end", start))

        # mantém words se existirem (pra max sync)
        words = seg.get("words")
        if words is not None and not isinstance(words, list):
            words = None

        out.append({
            "start": start,
            "end": end,
            "text": text,
            "words": words,
            "avg_logprob": seg.get("avg_logprob", None),
            "no_speech_prob": seg.get("no_speech_prob", None),
            "avg_word_prob": seg.get("avg_word_prob", None),
        })

    # aperta tempos (modo máximo)
    out = _tighten_maxsync(out, audio_total=audio_total)
    out = _merge_short_segments(out)
    out = _merge_micro_segments(out)
    return out


def _fmt_ts(t: float) -> str:
    if t < 0:
        t = 0.0
    ms = int(round(t * 1000.0))
    h = ms // 3600000
    ms -= h * 3600000
    m = ms // 60000
    ms -= m * 60000
    s = ms // 1000
    ms -= s * 1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(srt_path: Path, segments: list[dict]) -> None:
    lines: list[str] = []
    idx = 1
    for seg in segments:
        start = _fmt_ts(float(seg.get("start", 0.0)))
        end = _fmt_ts(float(seg.get("end", 0.0)))
        text = str(seg.get("text", "") or "").strip()
        if not text:
            continue
        lines.append(str(idx))
        lines.append(f"{start} --> {end}")
        lines.append(text)
        lines.append("")
        idx += 1

    if not lines:
        raise ValueError("Nenhuma fala foi reconhecida após a filtragem; não foi gerado SRT.")
    atomic_write_text(srt_path, "\n".join(lines).strip() + "\n")


def _wav_duration_seconds(wav: Path) -> float:
    """Retorna duração do WAV em segundos.

    Preferência:
    1) ffprobe (se existir no mesmo local do ffmpeg portable ou no PATH)
    2) fallback via módulo wave (sem dependências externas)
    """
    # 1) tenta ffprobe
    ffprobe = shutil.which("ffprobe") or shutil.which("ffprobe.exe")
    if not ffprobe:
        ff = resolve_ffmpeg()
        if ff:
            cand = Path(ff).parent / ("ffprobe.exe" if os.name == "nt" else "ffprobe")
            if cand.exists():
                ffprobe = str(cand)

    if ffprobe:
        cmd = [
            ffprobe,
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(wav),
        ]
        try:
            p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
            if p.returncode == 0:
                s = (p.stdout or "").strip()
                if s:
                    return float(s)
        except Exception:
            pass

    # 2) fallback: lê header do WAV
    try:
        import wave
        with wave.open(str(wav), "rb") as wf:
            frames = wf.getnframes()
            rate = wf.getframerate()
            if rate and frames:
                return float(frames) / float(rate)
    except Exception:
        pass

    return 0.0


def _fmt_clock(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _progress_bar(pct: float, width: int = 24) -> str:
    pct = max(0.0, min(100.0, float(pct)))
    filled = int(round((pct / 100.0) * width))
    filled = max(0, min(width, filled))
    return "█" * filled + "░" * (width - filled)


def main():
    parser = argparse.ArgumentParser(description="SubForgeAI - Whisper -> SRT (offline)")
    parser.add_argument("inputs", nargs="+", help="Caminho(s) do vídeo/áudio (1 ou vários)")
    parser.add_argument("--outdir", default="outputs/whisper", help="Pasta de saída")
    parser.add_argument("--model", default="large-v3", help="Modelo Whisper (default: large-v3)")
    parser.add_argument(
        "--backend",
        default="faster",
        choices=["auto", "faster", "torch", "whispercpp"],
        help="Backend: faster (Faster-Whisper/CTranslate2), torch (openai-whisper) ou whispercpp (binário). "
             "auto tenta faster e cai para whispercpp/torch",
    )
    parser.add_argument("--device", default="cuda", choices=["auto", "cuda", "gpu", "cpu"], help="Device (auto/cuda/gpu/cpu).")
    parser.add_argument("--lang", default="", help="Idioma (ex: ja, en). Vazio/auto = auto")
    parser.add_argument("--language", default=None, help="(alias) Igual --lang")
    parser.add_argument("--series-project", default="", help="Anime cadastrado no Studio para vocabulário confirmado.")
    parser.add_argument("--audio-stream", default="auto", help="auto prioriza japonês em animes; ou índice global da faixa de áudio.")
    parser.add_argument("--task", default="transcribe", choices=["transcribe", "translate"],
                        help="transcribe=mesmo idioma, translate=traduz para inglês")

    parser.add_argument("--keep_wav", action="store_true", help="Não apagar o _audio_temp.wav")
    parser.add_argument("--save_txt", action="store_true", help="Salvar TXT além do SRT")

    parser.add_argument("--fp16", action="store_true")
    parser.add_argument("--no-fp16", dest="fp16", action="store_false")
    parser.set_defaults(fp16=True)

    # Optional: stems (Demucs voice separation). Default: disabled.
    parser.add_argument("--stems", dest="stems", action="store_true", help="Ativa separação de voz (Demucs) antes do Whisper.")
    parser.add_argument("--no-stems", dest="stems", action="store_false", help="Desativa separação de voz (Demucs).")
    parser.set_defaults(stems=None)

    args = parser.parse_args()

    # normalize language
    lang = (args.language if args.language is not None else args.lang) or ""
    lang = (lang or "").strip().lower()
    if lang in ("auto", "automatic"):
        lang = ""

    # normalize device
    dev_req = (args.device or "").strip().lower()
    if dev_req == "gpu":
        dev_req = "cuda"
    if dev_req not in ("auto", "cuda", "cpu"):
        dev_req = "auto"

    # stems (Demucs) toggle: CLI > env > default False
    stems_enabled = False
    try:
        if args.stems is not None:
            stems_enabled = bool(args.stems)
        else:
            v = os.environ.get("SUBFORGEAI_STEMS", "").strip().lower()
            if v in ("1", "true", "yes", "on"):
                stems_enabled = True
            elif v in ("0", "false", "no", "off"):
                stems_enabled = False
            else:
                stems_enabled = False
    except Exception:
        stems_enabled = False

    stems_prefer_device = os.environ.get("SUBFORGEAI_STEMS_DEVICE", "cuda").strip().lower()
    if stems_prefer_device not in ("cuda", "cpu"):
        stems_prefer_device = "cuda"

    if not have_ffmpeg():
        print("[ERRO] ffmpeg não encontrado no PATH.")
        return 5

    root = _find_project_root(Path(__file__).resolve().parent)
    APP_DIR = root

    backend = (args.backend or "").strip().lower()

    # whispercpp discovery (lazy)
    whisper_cli = None
    cpp_model = None
    if backend in ("auto", "whispercpp"):
        whisper_cli = _find_whispercpp_cli(root)
        if whisper_cli is not None:
            cpp_model = _whispercpp_model_path(root, args.model)
        if backend == "whispercpp":
            if whisper_cli is None:
                print("[ERRO] whispercpp selecionado, mas whisper-cli não foi encontrado (tools/whispercpp).")
                return 6
            if cpp_model is None:
                print("[ERRO] whispercpp selecionado, mas modelo .bin não foi encontrado em models/whispercpp.")
                return 6

    # Decide backend efetivo
    use_cpp = False
    use_torch = False
    use_faster = False

    if backend == "whispercpp":
        use_cpp = True
    elif backend == "torch":
        use_torch = True
    elif backend == "faster":
        use_faster = True
    else:
        # auto: tenta faster -> whispercpp -> torch
        try:
            import importlib
            importlib.import_module("faster_whisper")
            use_faster = True
        except Exception:
            if whisper_cli is not None and cpp_model is not None:
                use_cpp = True
            else:
                use_torch = True

    # Device efetivo (intenção; faster tem fallback CUDA->CPU)
    if dev_req == "auto":
        dev_eff = "cuda"
    else:
        dev_eff = dev_req

    model = None
    faster_device_used = None

    if use_torch:
        try:
            import whisper  # type: ignore
        except Exception as e:
            print(f"[ERRO] Backend torch precisa da lib whisper instalada: {e}")
            return 6

        eff_device = _pick_torch_device(dev_eff)
        print(f"[INFO] Backend efetivo: torch | device efetivo: {eff_device}")
        try:
            model = whisper.load_model(args.model, device=eff_device)
        except Exception as e:
            print(f"[ERRO] Falha ao carregar modelo Whisper (torch): {e}")
            return 6

    elif use_faster:
        try:
            _configure_hf_cache(root)
            from faster_whisper import WhisperModel  # type: ignore
        except Exception as e:
            print(f"[WARN] faster_whisper não está disponível ({e}). Tentando fallback para torch...")
            use_faster = False
            use_torch = True
            try:
                import whisper  # type: ignore
            except Exception as e2:
                print(f"[ERRO] whisper (torch) também não está disponível: {e2}")
                return 6

            eff_device = _pick_torch_device(dev_eff)
            print(f"[INFO] Backend efetivo: torch | device efetivo: {eff_device}")
            try:
                model = whisper.load_model(args.model, device=eff_device)
            except Exception as e3:
                print(f"[ERRO] Falha ao carregar modelo Whisper (torch): {e3}")
                return 6
        else:
            compute_type = "float16" if dev_eff == "cuda" else "int8"
            if dev_eff == "cuda":
                compute_type = "float16" if bool(args.fp16) else "float32"

            print(f"[INFO] Backend efetivo: faster | device preferido: {dev_eff} | compute_type={compute_type}")

            model_source = local_faster_model(args.model, APP_DIR)
            print(f"[INFO] Modelo Whisper: {args.model} | origem: {model_source}")
            def _create_faster(dev: str, ctype: str):
                return WhisperModel(model_source, device=dev, compute_type=ctype,cpu_threads=int(os.environ.get("SUBFORGEAI_CPU_THREADS","0")))

            try:
                model = _create_faster(dev_eff, compute_type)
                faster_device_used = dev_eff
            except Exception as e:
                if dev_eff == "cuda":
                    print(f"[WARN] CUDA indisponível/ falhou no Faster-Whisper ({e}). Fallback para CPU...")
                    try:
                        model = _create_faster("cpu", "int8")
                        faster_device_used = "cpu"
                    except Exception as e2:
                        print(f"[ERRO] Falha ao iniciar Faster-Whisper também em CPU: {e2}")
                        return 6
                else:
                    print(f"[ERRO] Falha ao iniciar Faster-Whisper: {e}")
                    return 6

    else:
        print(f"[INFO] Backend efetivo: whispercpp | cli: {whisper_cli} | model: {cpp_model}")
        use_cpp = True

    overall_ok = True
    out_files = []

    outdir = Path(args.outdir).expanduser()

    # Portável: relativo ao projeto (APP_DIR)

    if not outdir.is_absolute():

        outdir = (APP_DIR / outdir).resolve()

    else:

        outdir = outdir.resolve()

    try:

        outdir.mkdir(parents=True, exist_ok=True)

    except Exception as e:

        fb = (APP_DIR / 'outputs' / 'whisper').resolve()

        print(f"[WARN] Não consegui criar OUTDIR em {outdir}: {e}. Usando {fb}")

        outdir = fb

        outdir.mkdir(parents=True, exist_ok=True)

    for raw in args.inputs:
        inp = Path(raw).expanduser().resolve()
        if not inp.exists():
            print(f"[ERRO] Arquivo não encontrado: {inp}")
            overall_ok = False
            continue

        try:
            with ExitStack() as resources:
                tmp_audio_dir = resources.enter_context(temporary_workspace(outdir, keep=args.keep_wav))
                srt_path = resources.enter_context(reserve_output(outdir / f"{inp.stem}.srt"))
                txt_path = (resources.enter_context(reserve_output(outdir / f"{inp.stem}.txt"))
                            if args.save_txt else None)
                audio_wav = tmp_audio_dir / f"{inp.stem}_audio_temp.wav"
                t0 = time.time()
                ff = resolve_ffmpeg()
                probe = Path(ff).with_name('ffprobe.exe' if os.name=='nt' else 'ffprobe')
                selected_audio = inspect_audio(inp, probe, lang, args.audio_stream)
                selected_index = selected_audio['index']
                selected_language = language_code(selected_audio.get('tags',{}).get('language'))
                file_language = lang or selected_language
                from subtitle_quality import SeriesTerms
                series_context = SeriesTerms(inp,[],outdir/'_series_context',file_language or 'auto')
                speech_terms = {**series_context.provenance.get('speech_terms',{}),**load_speech_terms(inp,root)}
                if args.series_project:
                    from series_registry import SeriesRegistry
                    project_terms=SeriesRegistry(root).confirmed(args.series_project)
                    series_context.explicit.update(project_terms)
                    speech_terms.update({key:value for key,value in project_terms.items() if re.search(r'[\u3040-\u9fff]',key) or key==value})
                known_spellings = list(dict.fromkeys([k for k in speech_terms] +
                    [k for k,v in series_context.explicit.items() if k==v and len(k)<=40]))[:60]
                hotwords = ', '.join(known_spellings)
                print(f"[CONTEXT] {len(series_context.explicit)} termos confirmados da série; {len(known_spellings)} grafias para reconhecimento.")
                retry_audit = []
                print(f"[AUDIO] Stream {selected_index} | idioma: {selected_language or 'não informado'} | título: {selected_audio.get('tags',{}).get('title','')} | seleção: {args.audio_stream}")
                print(f"[INFO] Transcrição: modelo={args.model} | idioma={file_language or 'detectar'} | tarefa={args.task} | Demucs={'ativado' if stems_enabled else 'desativado'}")
                print("[STEP 1/2] Extraindo áudio com FFmpeg...")
                code = ffmpeg_extract_wav(inp, audio_wav, selected_index)
                if code != 0 or (not audio_wav.exists()) or audio_wav.stat().st_size == 0:
                    print("[ERRO] Falha ao extrair áudio (wav).")
                    overall_ok = False
                    continue

                wav_total = _wav_duration_seconds(audio_wav)
                if wav_total <= 0:
                    wav_total = 0.0

                # Optional: Demucs stems (voice separation) BEFORE transcription
                audio_for_whisper = audio_wav
                tmp_stems_dir = None
                hq_audio = None
                vocals_wav = None
                if stems_enabled:
                    try:
                        stems_python = find_stems_python(root)
                        if stems_python is None:
                            print("[WARN] Stems ativado, mas não encontrei Python do Demucs nem em stems_venv nem em runtime/python. Seguindo com áudio normal.")
                        else:
                            tmp_stems_dir = tmp_audio_dir / "stems"
                            tmp_stems_dir.mkdir(parents=True, exist_ok=True)

                            hq_audio = tmp_audio_dir / f"{inp.stem}_hq_demucs.wav"
                            print("[STEMS] Extraindo áudio HQ (44.1k/stereo) para Demucs...")
                            c_hq = ffmpeg_extract_hq_audio(inp, hq_audio, selected_index)
                            if c_hq != 0 or (not hq_audio.exists()) or hq_audio.stat().st_size == 0:
                                print("[WARN] Não consegui extrair áudio HQ para Demucs. Seguindo com áudio normal.")
                            else:
                                vocals_path, msg = run_demucs(
                                    stems_python,
                                    hq_audio,
                                    tmp_stems_dir,
                                    prefer_device=stems_prefer_device,
                                    project_root=root,
                                )
                                if vocals_path is None:
                                    print(f"[WARN] Stems falhou: {msg}. Seguindo com áudio normal.")
                                else:
                                    vocals_wav = tmp_audio_dir / f"{inp.stem}_vocals_16k.wav"
                                    c_v = ffmpeg_to_whisper_wav(vocals_path, vocals_wav)
                                    if c_v != 0 or (not vocals_wav.exists()) or vocals_wav.stat().st_size == 0:
                                        print("[WARN] Não consegui converter vocals para 16k/mono. Seguindo com áudio normal.")
                                    else:
                                        audio_for_whisper = vocals_wav
                                        print(f"[STEMS] OK: usando VOCALS para o Whisper ({msg})")
                    except Exception as e:
                        print(f"[WARN] Stems falhou: {e}. Seguindo com áudio normal.")


                # whispercpp
                if use_cpp:
                    print("[STEP 2/2] Rodando whispercpp...")
                    out_prefix = srt_path.with_suffix("")
                    force_cpu = (str(dev_eff).strip().lower() == "cpu")
                    ok, msg = _run_whispercpp(whisper_cli, cpp_model, audio_for_whisper, out_prefix, (file_language or "auto"), force_cpu=force_cpu)
                    print(msg)
                    if not ok:
                        overall_ok = False
                        continue

                    srt_path = Path(str(out_prefix) + ".srt")
                    write_context(srt_path,inp,series_context.explicit,speech_terms,series_project=args.series_project)

                    if args.save_txt:
                        try:
                            lines = srt_path.read_text(encoding="utf-8", errors="replace").splitlines()
                            txt_parts = []
                            for ln in lines:
                                s = ln.strip()
                                if not s:
                                    continue
                                if s.isdigit():
                                    continue
                                if "-->" in s:
                                    continue
                                txt_parts.append(s)
                            txt_path.write_text((" ".join(txt_parts).strip() + "\n"), encoding="utf-8", errors="replace")
                            print(f"[SAVE] TXT: {txt_path}")
                        except Exception as e:
                            print(f"[WARN] Não consegui gerar TXT do SRT: {e}")

                    try:
                        if tmp_stems_dir is not None:
                            shutil.rmtree(tmp_stems_dir, ignore_errors=True)
                            print("[CLEAN] _tmp_stems apagado.")
                    except Exception:
                        pass

                    dt = time.time() - t0
                    print(f"[OK] SRT: {srt_path} ({dt:.1f}s)")
                    print(f"[OUTFILE] {srt_path}")
                    print("[RESULT] " + json.dumps({"kind": "transcription", "input": str(inp), "output": str(srt_path)}, ensure_ascii=False), flush=True)
                    continue

                # Faster-Whisper
                if use_faster:
                    print("[STEP 2/2] Rodando Faster-Whisper...")
                    fw_lang = file_language
                    progress_state = {"last_pct": -1.0, "last_print": 0.0}
                    seg_list: list[dict] = []

                    fw_kwargs = _build_faster_kwargs(
                        language=fw_lang,
                        task=args.task,
                        word_timestamps=True,
                        no_speech_threshold=HALLU_NO_SPEECH,
                        log_prob_threshold=HALLU_LOGPROB,
                        compression_ratio_threshold=HALLU_COMPRESS,
                        condition_on_previous_text=False,
                        hallucination_silence_threshold=0.8,
                        temperature=0.0,
                        vad_filter=FW_VAD_FILTER,
                        vad_min_silence_ms=FW_VAD_MIN_SILENCE_MS,
                        vad_threshold=FW_VAD_THRESHOLD,
                        beam_size=5,
                        best_of=5,
                        patience=1.0,
                    )

                    if hotwords: fw_kwargs['hotwords'] = hotwords
                    try:
                        segments, info = _drop_unsupported_kwargs(
                            lambda **kw: model.transcribe(str(audio_for_whisper), **kw),
                            fw_kwargs,
                        )
                        seg_list = _transcribe_segments_to_list(
                            segments,
                            offset_sec=0.0,
                            wav_total=wav_total,
                            progress_state=progress_state,
                        )
                    except Exception as e:
                        if faster_device_used == "cuda":
                            print(f"[WARN] Falha durante transcrição em CUDA ({e}). Tentando fallback CPU...")
                            try:
                                from faster_whisper import WhisperModel  # type: ignore

                                model_cpu = WhisperModel(model_source, device="cpu", compute_type="int8",cpu_threads=int(os.environ.get("SUBFORGEAI_CPU_THREADS","0")))
                                segments, info = _drop_unsupported_kwargs(
                                    lambda **kw: model_cpu.transcribe(str(audio_for_whisper), **kw),
                                    fw_kwargs,
                                )
                                progress_state = {"last_pct": -1.0, "last_print": 0.0}
                                seg_list = _transcribe_segments_to_list(
                                    segments,
                                    offset_sec=0.0,
                                    wav_total=wav_total,
                                    progress_state=progress_state,
                                )
                                print("[INFO] Fallback CPU concluído com sucesso.")
                                model = model_cpu
                                faster_device_used = "cpu"
                            except Exception as e2:
                                print(f"[ERRO] Falha também no fallback CPU: {e2}")
                                overall_ok = False
                                continue
                        else:
                            print(f"[ERRO] Falha na transcrição (faster): {e}")
                            overall_ok = False
                            continue

                    detected_language = getattr(info, 'language', None)
                    fw_lang = fw_lang or detected_language
                    print(f"[INFO] Idioma efetivo: {fw_lang} | confiança: {getattr(info, 'language_probability', 0):.3f}; mantido nos reprocessamentos.")
                    # Re-decode bounded, original audio around discontinuous
                    # word timestamps. Never bridge a long silence by moving text.
                    align_windows = _merge_windows(timing_defects(seg_list),gap=.2)[:10]
                    for ai,(start,end) in enumerate(align_windows):
                        end=min(end,float(wav_total))
                        if end-start>12 or end-start<.5:continue
                        chunk=tmp_audio_dir/f'align_{ai}.wav'
                        if ffmpeg_cut_wav(Path(audio_for_whisper),chunk,start,end):continue
                        options=_build_faster_kwargs(language=fw_lang,task=args.task,vad_filter=False,beam_size=8)
                        if hotwords:options['hotwords']=hotwords
                        try:
                            candidates,_=_drop_unsupported_kwargs(lambda **kw:model.transcribe(str(chunk),**kw),options)
                            candidates=_transcribe_segments_to_list(candidates,offset_sec=start)
                            old=alignment_window_segments(seg_list,start,end)
                            accepted,reason=candidate_decision(old,candidates,_segment_quality_score,alignment=True)
                            retry_audit.append(dict(kind='alignment',start=start,end=end,accepted=accepted,reason=reason,
                                original=[s['text'] for s in old],candidate=[s['text'] for s in candidates]))
                            if accepted:seg_list=replace_aligned_window(seg_list,start,end,candidates)
                        except Exception as exc:
                            retry_audit.append(dict(kind='alignment',start=start,end=end,accepted=False,reason=str(exc)))
                        finally:_safe_unlink(chunk)
                    # --- Modo "Trecho difícil": preencher buracos grandes (fala 'comida') sem reprocessar tudo ---
                    if DIFFICULT_ENABLE and wav_total and wav_total > 0:
                        try:
                            gaps = _find_large_gaps_from_segments(seg_list, float(wav_total))
                            if gaps:
                                print(f"[DIFFICULT] {len(gaps)} gap(s) >= {DIFFICULT_GAP_SEC:.1f}s detectado(s). Reprocessando (limite {DIFFICULT_MAX_GAPS})...")
                            for gi, (gs, ge) in enumerate(gaps[:DIFFICULT_MAX_GAPS], start=1):
                                cut_s = max(0.0, float(gs) - DIFFICULT_PAD_SEC)
                                cut_e = min(float(wav_total), float(ge) + DIFFICULT_PAD_SEC)
                                if (cut_e - cut_s) < DIFFICULT_MIN_CHUNK_SEC:
                                    continue

                                chunk = tmp_audio_dir / f"{inp.stem}_gap{gi:02d}.wav"
                                rc = ffmpeg_cut_wav(Path(audio_for_whisper), chunk, cut_s, cut_e)
                                if rc != 0 or (not chunk.exists()) or chunk.stat().st_size == 0:
                                    continue

                                fw_gap_kwargs = _build_faster_kwargs(
                                    language=fw_lang,
                                    task=args.task,
                                    word_timestamps=True,
                                    no_speech_threshold=DIFFICULT_NO_SPEECH,
                                    log_prob_threshold=DIFFICULT_LOGPROB,
                                    compression_ratio_threshold=HALLU_COMPRESS,
                                    condition_on_previous_text=False,
                                    hallucination_silence_threshold=0.8,
                                    temperature=0.0,
                                    vad_filter=(not DIFFICULT_DISABLE_VAD),
                                    vad_min_silence_ms=FW_VAD_MIN_SILENCE_MS,
                                    vad_threshold=FW_VAD_THRESHOLD,
                                    beam_size=5,
                                    best_of=5,
                                    patience=1.0,
                                )

                                try:
                                    if hotwords: fw_gap_kwargs['hotwords']=hotwords
                                    segs2, _info2 = _drop_unsupported_kwargs(
                                        lambda **kw: model.transcribe(str(chunk), **kw),
                                        fw_gap_kwargs,
                                    )
                                    new_items = _transcribe_segments_to_list(segs2, offset_sec=cut_s, wav_total=0.0, progress_state=None)
                                except Exception as e_gap:
                                    print(f"[WARN] Trecho difícil {gi} falhou na transcrição: {e_gap}")
                                    _safe_unlink(chunk)
                                    continue

                                injected = 0
                                for new_seg in new_items:
                                    if not _accept_gap_candidate(new_seg):
                                        continue
                                    s2 = float(new_seg.get("start", 0.0))
                                    e2 = float(new_seg.get("end", s2))
                                    if e2 <= gs + 0.05 or s2 >= ge - 0.05:
                                        continue
                                    if not _seg_overlaps_existing(new_seg, seg_list):
                                        seg_list.append(new_seg)
                                        injected += 1

                                _safe_unlink(chunk)

                                if injected > 0:
                                    print(f"[DIFFICULT] gap {gi}: injetei {injected} segmento(s).")
                        except Exception as e_dm:
                            print(f"[WARN] Modo trecho difícil falhou (ignorado): {e_dm}")

                    # --- Retry pontual de baixa confiança/garbage ---
                    if LOWCONF_ENABLE and seg_list:
                        try:
                            retry_windows = _find_lowconf_windows(seg_list)
                            if retry_windows:
                                print(f"[LOWCONF] {len(retry_windows)} janela(s) suspeita(s) detectada(s). Reavaliando (limite {LOWCONF_MAX_WINDOWS})...")
                            for wi, (ws, we) in enumerate(retry_windows[:LOWCONF_MAX_WINDOWS], start=1):
                                chunk = tmp_audio_dir / f"{inp.stem}_lowconf{wi:02d}.wav"
                                rc = ffmpeg_cut_wav(Path(audio_for_whisper), chunk, ws, we)
                                if rc != 0 or (not chunk.exists()) or chunk.stat().st_size == 0:
                                    continue

                                retry_kwargs = _build_faster_kwargs(
                                    language=fw_lang,
                                    task=args.task,
                                    word_timestamps=True,
                                    no_speech_threshold=0.18,
                                    log_prob_threshold=-2.00,
                                    compression_ratio_threshold=HALLU_COMPRESS,
                                    condition_on_previous_text=False,
                                    hallucination_silence_threshold=0.8,
                                    temperature=0.0,
                                    vad_filter=False,
                                    beam_size=5,
                                    best_of=5,
                                    patience=1.1,
                                )

                                try:
                                    if hotwords:retry_kwargs['hotwords']=hotwords
                                    retry_segments, _retry_info = _drop_unsupported_kwargs(
                                        lambda **kw: model.transcribe(str(chunk), **kw),
                                        retry_kwargs,
                                    )
                                    new_segments = [
                                        s for s in _transcribe_segments_to_list(retry_segments, offset_sec=ws, wav_total=0.0, progress_state=None)
                                        if _interval_overlap(s.get("start", 0.0), s.get("end", 0.0), ws, we) > 0.05
                                    ]
                                except Exception as e_retry:
                                    print(f"[WARN] Retry lowconf {wi} falhou: {e_retry}")
                                    _safe_unlink(chunk)
                                    continue

                                old_segments = _window_segments(seg_list, ws, we)
                                accepted,reason=candidate_decision(old_segments,new_segments,_segment_quality_score)
                                retry_audit.append(dict(kind='low_confidence',start=ws,end=we,accepted=accepted,reason=reason,
                                    original=[s['text'] for s in old_segments],candidate=[s['text'] for s in new_segments]))
                                if accepted:
                                    seg_list = [
                                        s for s in seg_list
                                        if _interval_overlap(s.get("start", 0.0), s.get("end", 0.0), ws, we) <= 0.05
                                    ]
                                    seg_list.extend(new_segments)
                                    print(f"[LOWCONF] janela {wi}: substituí {len(old_segments)} -> {len(new_segments)} segmento(s).")

                                _safe_unlink(chunk)
                        except Exception as e_lc:
                            print(f"[WARN] Retry de baixa confiança falhou (ignorado): {e_lc}")

                    # --- Resgate de falas curtas / quase sem cobertura em janelas com voz real ---
                    if SHORT_RESCUE_ENABLE and seg_list and wav_total and wav_total > 0:
                        try:
                            rescue_windows = _find_short_rescue_windows(Path(audio_for_whisper), seg_list, float(wav_total))
                            if rescue_windows:
                                print(f"[SHORT] {len(rescue_windows)} janela(s) curtas/quase sem cobertura detectada(s). Reavaliando (limite {SHORT_RESCUE_MAX_WINDOWS})...")
                            for ri, (rs, re_) in enumerate(rescue_windows[:SHORT_RESCUE_MAX_WINDOWS], start=1):
                                chunk = tmp_audio_dir / f"{inp.stem}_short{ri:02d}.wav"
                                rc = ffmpeg_cut_wav(Path(audio_for_whisper), chunk, rs, re_)
                                if rc != 0 or (not chunk.exists()) or chunk.stat().st_size == 0:
                                    continue

                                short_kwargs = _build_faster_kwargs(
                                    language=fw_lang,
                                    task=args.task,
                                    word_timestamps=True,
                                    no_speech_threshold=0.12,
                                    log_prob_threshold=-2.15,
                                    compression_ratio_threshold=HALLU_COMPRESS,
                                    condition_on_previous_text=False,
                                    hallucination_silence_threshold=0.55,
                                    temperature=0.0,
                                    vad_filter=False,
                                    beam_size=6,
                                    best_of=6,
                                    patience=1.18,
                                )

                                try:
                                    short_segments, _short_info = _drop_unsupported_kwargs(
                                        lambda **kw: model.transcribe(str(chunk), **kw),
                                        short_kwargs,
                                    )
                                    new_segments_raw = [
                                        s for s in _transcribe_segments_to_list(short_segments, offset_sec=rs, wav_total=0.0, progress_state=None)
                                        if _interval_overlap(s.get("start", 0.0), s.get("end", 0.0), rs, re_) > 0.03
                                    ]
                                except Exception as e_short:
                                    print(f"[WARN] Resgate de fala curta {ri} falhou: {e_short}")
                                    _safe_unlink(chunk)
                                    continue

                                window = (rs, re_)
                                new_segments = _prepare_short_rescue_segments(new_segments_raw, window, float(wav_total))
                                old_segments = _window_segments(seg_list, rs, re_)

                                if old_segments:
                                    agreed,reason=candidate_decision(old_segments,new_segments,_segment_quality_score)
                                    retry_audit.append(dict(kind='short_speech',start=rs,end=re_,accepted=agreed,reason=reason,
                                        original=[s['text'] for s in old_segments],candidate=[s['text'] for s in new_segments]))
                                    if not agreed:
                                        _safe_unlink(chunk)
                                        continue
                                if old_segments and _should_replace_short_rescue_window(window, old_segments, new_segments):
                                    seg_list = [
                                        s for s in seg_list
                                        if _interval_overlap(s.get("start", 0.0), s.get("end", 0.0), rs, re_) <= 0.03
                                    ]
                                    seg_list.extend(new_segments)
                                    print(f"[SHORT] janela {ri}: substituí {len(old_segments)} -> {len(new_segments)} segmento(s).")
                                else:
                                    injected = 0
                                    for new_seg in new_segments:
                                        if _accept_gap_candidate(new_seg) and not _seg_overlaps_existing(new_seg, seg_list, min_overlap=SHORT_RESCUE_OVERLAP_SKIP_SEC):
                                            seg_list.append(new_seg)
                                            injected += 1

                                    if injected > 0:
                                        print(f"[SHORT] janela {ri}: injetei {injected} segmento(s).")

                                _safe_unlink(chunk)
                        except Exception as e_short_all:
                            print(f"[WARN] Resgate de falas curtas falhou (ignorado): {e_short_all}")

                    try:
                        segs = filter_segments({"segments": seg_list, "audio_total": wav_total})
                        write_srt(srt_path, segs)
                        uncertain=[entry for entry in retry_audit if not entry['accepted'] and (entry['kind']=='alignment' or entry['reason'] in
                                   ('recognition_disagreement','possible_omission','possible_invention','empty_candidate'))]
                        write_context(srt_path,inp,series_context.explicit,speech_terms,uncertain,series_project=args.series_project)
                        audit = {'source_file': str(inp), 'duration_seconds': wav_total,
                                 'device': faster_device_used, 'model': args.model, 'model_source': model_source,
                                 'audio_stream': selected_index, 'audio_tags': selected_audio.get('tags',{}),
                                 'language': fw_lang, 'detected_language': detected_language,
                                 'language_probability': getattr(info,'language_probability',None),
                                 'task': args.task, 'demucs_used': vocals_wav is not None and audio_for_whisper==vocals_wav,
                                 'retry_audit': retry_audit, 'confirmed_series_terms':len(series_context.explicit),
                                 'review_findings': transcription_findings(segs, fw_lang), 'segments': segs}
                        atomic_write_text(Path(str(srt_path)+'.transcription.json'), json.dumps(audit,ensure_ascii=False,indent=2))
                        print(f"[QUALITY] {len(audit['review_findings'])} bloco(s) de transcrição sinalizados para revisão. Auditoria: {srt_path}.transcription.json")
                    except Exception as e:
                        print(f"[ERRO] Falha ao escrever SRT (faster): {e}")
                        overall_ok = False
                        continue

                    if (not srt_path.exists()) or srt_path.stat().st_size == 0:
                        print("[ERRO] O SRT não foi gerado corretamente (0 KB).")
                        overall_ok = False
                        continue

                    if args.save_txt:
                        try:
                            txt_parts = [clean_text(s.get("text", "")) for s in segs]
                            txt_path.write_text((" ".join([p for p in txt_parts if p]).strip() + "\n"), encoding="utf-8", errors="replace")
                            print(f"[SAVE] TXT: {txt_path}")
                        except Exception:
                            pass

                    try:
                        if tmp_stems_dir is not None:
                            shutil.rmtree(tmp_stems_dir, ignore_errors=True)
                            print("[CLEAN] _tmp_stems apagado.")
                    except Exception:
                        pass

                    dt = time.time() - t0
                    print(f"[OK] SRT gerado: {srt_path}")
                    out_files.append(str(srt_path))
                    print(f"[OUTFILE] {srt_path}")
                    print("[RESULT] " + json.dumps({"kind": "transcription", "input": str(inp), "output": str(srt_path)}, ensure_ascii=False), flush=True)
                    print(f"[OK] Tempo: {dt:.1f}s")
                    continue

                # torch backend
                print("[STEP 2/2] Rodando Whisper (torch)...")
                kwargs = {
                    "task": args.task,
                    "fp16": bool(args.fp16),
                    "verbose": False,
                    "temperature": 0.0,
                    "no_speech_threshold": HALLU_NO_SPEECH,
                    "logprob_threshold": HALLU_LOGPROB,
                    "compression_ratio_threshold": HALLU_COMPRESS,
                    "condition_on_previous_text": False,
                    "hallucination_silence_threshold": 0.8,
                }
                if file_language:
                    kwargs["language"] = file_language

                try:
                    result = model.transcribe(str(audio_for_whisper), **kwargs)
                except Exception as e:
                    print(f"[ERRO] Falha na transcrição: {e}")
                    overall_ok = False
                    continue

                if args.save_txt:
                    try:
                        txt_path.write_text((result.get("text") or "").strip() + "\n", encoding="utf-8", errors="replace")
                        print(f"[SAVE] TXT: {txt_path}")
                    except Exception:
                        pass

                try:
                    segs = filter_segments({**(result or {}), "audio_total": wav_total})
                    write_srt(srt_path, segs)
                    write_context(srt_path,inp,series_context.explicit,speech_terms,series_project=args.series_project)
                except Exception as e:
                    print(f"[ERRO] Falha ao escrever SRT: {e}")
                    overall_ok = False
                    continue

                if (not srt_path.exists()) or srt_path.stat().st_size == 0:
                    print("[ERRO] O SRT não foi gerado corretamente (0 KB).")
                    overall_ok = False
                    continue

                try:
                    if tmp_stems_dir is not None:
                        shutil.rmtree(tmp_stems_dir, ignore_errors=True)
                        print("[CLEAN] _tmp_stems apagado.")
                except Exception:
                    pass

                dt = time.time() - t0
                print(f"[OK] SRT gerado: {srt_path}")
                out_files.append(str(srt_path))
                print(f"[OUTFILE] {srt_path}")
                print("[RESULT] " + json.dumps({"kind": "transcription", "input": str(inp), "output": str(srt_path)}, ensure_ascii=False), flush=True)
                print(f"[OK] Tempo: {dt:.1f}s")
        except Exception as exc:
            overall_ok = False
            print(f"[ERRO] Falhou em {inp.name}: {exc}")

    return 0 if overall_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
