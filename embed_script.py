# -*- coding: utf-8 -*-
"""
SubForgeAI - Embed Softsub (mux) via FFmpeg
- Adds subtitle track without re-encoding (fast)
- Default output: MKV (most compatible with SRT softsubs)
- Also supports hardcode (burn-in) via FFmpeg (re-encode video)
"""
from __future__ import annotations

import shutil
import subprocess
import json
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pipeline_io import reserve_output, staged_output


def have_ffmpeg(ffmpeg_path: Optional[str] = None) -> Optional[str]:
    # 1) caminho explícito
    if ffmpeg_path:
        p = Path(ffmpeg_path)
        if p.exists() and p.is_file():
            return str(p)

    # 2) FFmpeg portátil ao lado do app (dist)
    # Inclui a pasta-pai: o .exe pode rodar numa subpasta (ex.: SubForgeAI_v2/)
    # enquanto tools/ e runtime/ continuam na raiz da distribuição.
    try:
        base = Path(__file__).resolve().parent
        roots = [base, base.parent]
        candidates = [
            (r / "tools" / "ffmpeg" / "ffmpeg.exe")
            for r in roots
        ] + [
            (r / "runtime" / "ffmpeg" / "ffmpeg.exe")
            for r in roots
        ] + [
            base / "ffmpeg.exe",
            base.parent / "ffmpeg.exe",
        ]
        for c in candidates:
            if c.exists() and c.is_file():
                return str(c)
    except Exception:
        pass

    # 3) PATH do sistema
    return shutil.which("ffmpeg")


def mux_softsub(
    video_path: str,
    subtitle_path: str,
    out_dir: str,
    *,
    ffmpeg_path: Optional[str] = None,
    language: str = "por",
    subtitle_title: str = "Português (Brasil)",
    force_mkv: bool = True,
    process_runner=None,
) -> str:
    ffmpeg = have_ffmpeg(ffmpeg_path)
    if not ffmpeg:
        raise RuntimeError("FFmpeg não encontrado no PATH (ou ffmpeg_path inválido).")

    v = Path(video_path).resolve()
    s = Path(subtitle_path).resolve()
    if not v.exists():
        raise FileNotFoundError(f"Vídeo não encontrado: {v}")
    if not s.exists():
        raise FileNotFoundError(f"Legenda não encontrada: {s}")

    outp = Path(out_dir).resolve()
    outp.mkdir(parents=True, exist_ok=True)

    out_ext = ".mkv" if force_mkv else v.suffix.lower()
    runner = process_runner or subprocess.run
    probe_path = Path(ffmpeg).with_name("ffprobe.exe" if Path(ffmpeg).suffix.lower() == ".exe" else "ffprobe")
    ffprobe = str(probe_path) if probe_path.is_file() else shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError("FFprobe não encontrado; não foi possível identificar a nova faixa de legenda.")
    p = runner([ffprobe, "-v", "error", "-select_streams", "s", "-show_entries", "stream=index", "-of", "json", str(v)],
               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout or "ffprobe falhou").strip())
    new_index = len(json.loads(p.stdout).get("streams", []))
    # Preserve existing subtitle codecs/styles; target only the appended track.
    sub_codec = "mov_text" if out_ext == ".mp4" else "copy"
    with reserve_output(outp / f"{v.stem}_com_legenda{out_ext}") as out_file:
        with staged_output(out_file) as temporary:
            cmd = [
                ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                "-i", str(v), "-i", str(s), "-map", "0", "-map", "1:0", "-c", "copy",
                f"-c:s:{new_index}", sub_codec,
                f"-metadata:s:s:{new_index}", f"language={language}",
                f"-metadata:s:s:{new_index}", f"title={subtitle_title}", str(temporary),
            ]
            p = runner(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
            if p.returncode != 0:
                raise RuntimeError((p.stderr or p.stdout or "ffmpeg falhou").strip())
        return str(out_file)


def burn_subtitles(
    video_path: str,
    subtitle_path: str,
    out_dir: str,
    *,
    ffmpeg_path: Optional[str] = None,
    crf: int = 18,
    preset: str = "medium",
) -> str:
    """Hardcode (burn-in) da legenda no vídeo via FFmpeg (re-encode do vídeo, áudio copy)."""
    ffmpeg = have_ffmpeg(ffmpeg_path)
    if not ffmpeg:
        raise RuntimeError("FFmpeg não encontrado no PATH (ou ffmpeg_path inválido).")

    v = Path(video_path).resolve()
    s = Path(subtitle_path).resolve()
    if not v.exists():
        raise FileNotFoundError(f"Vídeo não encontrado: {v}")
    if not s.exists():
        raise FileNotFoundError(f"Legenda não encontrada: {s}")

    outp = Path(out_dir).resolve()
    outp.mkdir(parents=True, exist_ok=True)

    out_file = outp / f"{v.stem}_hardcoded.mp4"

    # Filtro subtitles no Windows precisa escapar ':' do drive (C\:)
    sub = str(s).replace("\\", "/")
    sub = sub.replace(":", "\\:")
    sub = sub.replace("'", "\\'")
    vf = f"subtitles='{sub}'"

    cmd = [
        ffmpeg, "-y",
        "-i", str(v),
        "-vf", vf,
        "-c:v", "libx264",
        "-preset", str(preset),
        "-crf", str(int(crf)),
        "-c:a", "copy",
        str(out_file),
    ]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout or "ffmpeg falhou").strip())
    return str(out_file)
