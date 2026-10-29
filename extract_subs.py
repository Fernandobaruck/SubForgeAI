# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from shutil import which

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pipeline_io import reserve_output, staged_output

VIDEO_EXTS = {".mkv", ".mp4", ".avi", ".mov", ".webm", ".m4v", ".mpg", ".mpeg", ".ts", ".m2ts"}
SUB_EXTS = {".srt", ".ass", ".ssa", ".vtt", ".sub", ".sup", ".idx", ".mks"}

BITMAP_CODECS = {"hdmv_pgs_subtitle", "dvd_subtitle", "dvb_subtitle"}
TEXT_CODEC_TO_EXT = {
    "subrip": "srt",
    "ass": "ass",
    "ssa": "ssa",
    "webvtt": "vtt",
    "mov_text": "srt",
}

def _print(s: str) -> None:
    print(s, flush=True)

def _result(source: Path, output: Path) -> None:
    _print("[RESULT] " + json.dumps({"kind":"extraction","input":str(source.resolve()),"output":str(output.resolve())},ensure_ascii=False))


def _sanitize(name: str) -> str:
    # Windows-safe filename
    name = name.strip().replace("\n", " ").replace("\r", " ")
    name = re.sub(r'[<>:"/\\|?*\x00-\x1F]', "_", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:180] if len(name) > 180 else name

def _find_tool(names: list[str], base: Path) -> str | None:
    cand: list[Path] = []
    # comuns no projeto/dist
    for n in names:
        cand += [
            base / n,
            base / f"{n}.exe",
            base / "_internal" / n,
            base / "_internal" / f"{n}.exe",
            base.parent / n,
            base.parent / f"{n}.exe",
        ]

    # ffmpeg portátil (relativo ao app)
    extra_dirs = [
        base / "tools" / "ffmpeg",
        base / "runtime" / "ffmpeg",
        base.parent / "tools" / "ffmpeg",
        base.parent / "runtime" / "ffmpeg",
    ]
    for d in extra_dirs:
        for n in names:
            cand += [d / n, d / f"{n}.exe"]
    for p in cand:
        if p.exists():
            return str(p)
    for n in names:
        w = which(n) or which(f"{n}.exe")
        if w:
            return w
    return None

def _run(cmd: list[str], cwd: Path | None = None) -> tuple[int, str]:
    try:
        p = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return p.returncode, p.stdout
    except FileNotFoundError:
        return 127, f"Arquivo não encontrado ao executar: {cmd[0]}"
    except Exception as e:
        return 1, f"Falha ao executar comando: {e}"

def _ffprobe_streams(ffprobe: str, inp: Path) -> list[dict]:
    cmd = [
        ffprobe,
        "-hide_banner",
        "-v", "error",
        "-select_streams", "s",
        "-show_entries", "stream=index,codec_name:stream_tags=language,title",
        "-of", "json",
        str(inp),
    ]
    rc, out = _run(cmd)
    if rc != 0:
        _print("[ERRO] ffprobe falhou ao listar streams de legenda.")
        _print(out.strip())
        return []
    try:
        j = json.loads(out)
        return j.get("streams", []) or []
    except (ValueError, TypeError):
        _print("[ERRO] FFprobe retornou uma resposta inválida.")
        return []


def _run_to_output(cmd: list[str], preferred: Path) -> tuple[int, str, Path]:
    try:
        with reserve_output(preferred) as final:
            with staged_output(final) as temporary:
                rc, output = _run([*cmd[:-1], str(temporary)])
                if rc != 0:
                    raise RuntimeError(output or f"FFmpeg retornou exit={rc}")
            return 0, output, final
    except Exception as exc:
        return 1, str(exc), preferred

def _guess_ext(codec: str | None) -> str:
    if not codec:
        return "srt"
    return TEXT_CODEC_TO_EXT.get(codec, "srt")

def _codec_is_bitmap(codec: str | None) -> bool:
    return bool(codec) and (codec in BITMAP_CODECS)

def _extract_from_video(ffmpeg: str, ffprobe: str, inp: Path, outdir: Path, to_fmt: str, stream_sel: str) -> int:
    streams = _ffprobe_streams(ffprobe, inp)
    if not streams:
        _print("[WARN] Nenhuma faixa de legenda detectada (ou ffprobe falhou).")
        return 2

    # filtra streams se usuário escolheu índice(s) específico(s)
    chosen: list[dict] = []
    sel = (stream_sel or "all").strip()
    if sel.lower() == "all":
        chosen = streams
    else:
        # aceita: "2" ou "2,3,5" (ffprobe stream index)
        wanted: set[int] = set()
        try:
            parts = [p.strip() for p in sel.split(",") if p.strip()]
            for p in parts:
                wanted.add(int(p))
            chosen = [s for s in streams if int(s.get("index", -1)) in wanted]
        except Exception:
            _print(f"[ERRO] --stream inválido: {stream_sel} (use 'all' ou índices separados por vírgula, ex: 2,3)")
            return 2

    if not chosen:
        _print("[ERRO] Nenhuma faixa corresponde à seleção solicitada.")
        return 2
    if sel.lower() != "all" and wanted != {int(s["index"]) for s in chosen}:
        _print("[ERRO] Uma ou mais faixas solicitadas não existem.")
        return 2

    stem = _sanitize(inp.stem)
    work = outdir / stem
    work.mkdir(parents=True, exist_ok=True)
    _print(f"[OUTDIR] {work}")

    ok = 0
    failed = 0
    for s in chosen:
        idx = int(s.get("index", -1))
        codec = (s.get("codec_name") or "")
        tags = s.get("tags") or {}
        lang = (tags.get("language") or "und").strip()
        title = (tags.get("title") or "").strip()
        label = _sanitize(f"s{idx}__{lang}" + (f"__{title}" if title else ""))

        # decide formato/codec de saída
        out_ext = ""
        codec_args: list[str] = []

        if to_fmt == "copy":
            if _codec_is_bitmap(codec):
                # PGS/DVB/DVD -> geralmente vira .sup/.sub (não é texto)
                out_ext = "sup" if codec == "hdmv_pgs_subtitle" else "sub"
                codec_args = ["-c:s", "copy"]
                _print(f"[INFO] Stream {idx} é bitmap ({codec}). Vai sair como {out_ext} (não dá pra traduzir por IA direto).")
            elif codec in ("ass", "ssa", "subrip", "webvtt"):
                out_ext = _guess_ext(codec)
                codec_args = ["-c:s", "copy"]
            else:
                # codecs textuais menos comuns (ex: mov_text) — melhor converter
                out_ext = "srt"
                codec_args = ["-c:s", "srt"]
        else:
            # conversão para formato alvo
            if _codec_is_bitmap(codec) and to_fmt in ("srt", "ass", "vtt"):
                _print(f"[WARN] Pulando stream {idx} ({codec}): é bitmap e não converte bem pra texto.")
                failed += 1
                continue
            out_ext = to_fmt
            if to_fmt == "srt":
                codec_args = ["-c:s", "srt"]
            elif to_fmt == "ass":
                codec_args = ["-c:s", "ass"]
            elif to_fmt == "vtt":
                codec_args = ["-c:s", "webvtt"]
            else:
                # fallback
                codec_args = []

        out_file = work / f"{stem}__{label}.{out_ext}"
        cmd = [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel", "error",
            "-i", str(inp),
            "-map", f"0:{idx}",
            *codec_args,
            str(out_file),
        ]
        _print(f"[EXTRACT] {inp.name} | stream={idx} codec={codec or 'unk'} lang={lang or 'und'} -> {out_file.name}")
        rc, out, actual_file = _run_to_output(cmd, out_file)
        if rc != 0:
            failed += 1
            _print(f"[WARN] Falha ao extrair stream {idx} (exit={rc}).")
            if out.strip():
                _print(out.strip())
        else:
            ok += 1
            _print(f"[OK] Salvo: {actual_file}")
            _result(inp,actual_file)

    if ok == 0:
        _print("[WARN] Nenhuma legenda foi extraída.")
        return 3
    if failed:
        _print(f"[ERRO] Extração parcial: {ok} faixa(s) salva(s), {failed} não concluída(s). Os arquivos salvos foram preservados.")
        return 4
    _print(f"[OK] Extraídas {ok} faixa(s) de legenda.")
    return 0

def _convert_subtitle(ffmpeg: str, inp: Path, outdir: Path, to_fmt: str) -> int:
    outdir.mkdir(parents=True, exist_ok=True)
    stem = _sanitize(inp.stem)
    if to_fmt == "copy":
        # só copia
        with reserve_output(outdir / inp.name) as dst:
            with staged_output(dst) as temporary:
                shutil.copy2(inp, temporary)
        _print(f"[OK] Copiado: {dst}")
        _result(inp,dst)
        return 0

    ext = to_fmt
    out_file = outdir / f"{stem}.{ext}"
    codec_args: list[str] = []
    if to_fmt == "srt":
        codec_args = ["-c:s", "srt"]
    elif to_fmt == "ass":
        codec_args = ["-c:s", "ass"]
    elif to_fmt == "vtt":
        codec_args = ["-c:s", "webvtt"]

    cmd = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel", "error",
        "-i", str(inp),
        *codec_args,
        str(out_file),
    ]
    _print(f"[CONVERT] {inp.name} -> {out_file.name}")
    rc, out, out_file = _run_to_output(cmd, out_file)
    if rc != 0:
        _print(f"[ERRO] Falha ao converter (exit={rc}).")
        if out.strip():
            _print(out.strip())
        return rc
    _print(f"[OK] Convertido: {out_file}")
    _result(inp,out_file)
    return 0

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Extrai legendas embutidas do vídeo (ou converte arquivo de legenda) via FFmpeg.")
    ap.add_argument("inputs", nargs="+", help="Vídeo(s) ou legenda(s).")
    ap.add_argument("--outdir", default=str(Path("outputs") / "subs_extradas"), help="Pasta base de saída.")
    ap.add_argument("--to", default="copy", choices=["copy", "ass", "srt", "vtt"], help="Formato de saída (copy mantém quando possível).")
    ap.add_argument("--stream", default="all", help="Índice(s) da stream de legenda (ffprobe stream index). Use 'all' ou lista: 2,3,5")
    ap.add_argument("--ocr", action="store_true", help="OCR offline de arquivos .sup para SRT; consulte o relatório .ocr.json.")
    ap.add_argument("--list", action="store_true", help="Apenas lista as streams de legenda do vídeo.")
    args = ap.parse_args(argv)

    base = Path(__file__).resolve().parent
    ffmpeg = _find_tool(["ffmpeg"], base)
    ffprobe = _find_tool(["ffprobe"], base) or _find_tool(["ffmpeg"], base)  # ffprobe às vezes vem junto; fallback não ideal
    if not ffmpeg:
        _print("[ERRO] ffmpeg não encontrado. Coloque no PATH ou ao lado do app.")
        return 127
    if not ffprobe or Path(ffprobe).name.lower().startswith("ffmpeg"):
        # tenta encontrar ffprobe de novo; se não, ainda dá pra extrair em alguns casos mas perde lista
        ffprobe = _find_tool(["ffprobe"], base)

    outdir = Path(args.outdir).expanduser()
    outdir.mkdir(parents=True, exist_ok=True)

    rc_final = 0
    for raw in args.inputs:
        inp = Path(raw).expanduser()
        if not inp.exists():
            _print(f"[WARN] Arquivo não existe: {inp}")
            rc_final = rc_final or 2
            continue

        ext = inp.suffix.lower()
        is_video = ext in VIDEO_EXTS or ext not in SUB_EXTS  # se for desconhecido, tenta como vídeo primeiro
        if is_video:
            if args.ocr:
                _print("[ERRO] Extraia primeiro a faixa PGS como .sup (--to copy); depois use --ocr --to srt.")
                rc_final = rc_final or 2
                continue
            if args.list:
                if not ffprobe:
                    _print("[ERRO] ffprobe não encontrado. Não dá pra listar streams.")
                    rc_final = rc_final or 127
                else:
                    streams = _ffprobe_streams(ffprobe, inp)
                    _print(f"[LIST] {inp.name} — {len(streams)} stream(s) de legenda:")
                    for s in streams:
                        idx = s.get("index")
                        codec = s.get("codec_name")
                        tags = s.get("tags") or {}
                        lang = tags.get("language", "und")
                        title = tags.get("title", "")
                        _print(f"  - index={idx} codec={codec} lang={lang} title={title}")
            else:
                if not ffprobe:
                    _print("[ERRO] ffprobe não encontrado. Não dá pra extrair com nomes corretos.")
                    _print("       Instale um FFmpeg completo (com ffprobe) ou coloque ffprobe.exe no PATH.")
                    rc_final = rc_final or 127
                else:
                    rc = _extract_from_video(ffmpeg, ffprobe, inp, outdir, args.to, args.stream)
                    rc_final = rc_final or rc
        elif args.ocr:
            if ext != ".sup" or args.to != "srt":
                _print("[ERRO] --ocr exige um arquivo .sup e --to srt.")
                rc_final = rc_final or 2
                continue
            try:
                from pgs_ocr import convert
                output = convert(inp,outdir)
                _print(f"[OK] OCR salvo: {output} — revise o relatório .ocr.json")
                _result(inp,output)
            except Exception as exc:
                _print(f"[ERRO] OCR: {exc}")
                rc_final = rc_final or 1
        else:
            # arquivo de legenda: converter/copy
            rc = _convert_subtitle(ffmpeg, inp, outdir, args.to)
            rc_final = rc_final or rc

    return int(rc_final)

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
