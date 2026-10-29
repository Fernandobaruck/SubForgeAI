"""Diagnostico do Ollama portatil — SubForgeAI.

Uso:
    F:\\SubForgeAI\\runtime\\python\\python.exe F:\\SubForgeAI\\verificar_ollama.py              (so diagnostica)
    F:\\SubForgeAI\\runtime\\python\\python.exe F:\\SubForgeAI\\verificar_ollama.py --start      (sobe o servidor)
    F:\\SubForgeAI\\runtime\\python\\python.exe F:\\SubForgeAI\\verificar_ollama.py --start --test (testa traducao)

Cobre os dois bloqueios conhecidos deste ambiente:
  - %USERPROFILE%\\.ollama sem permissao de escrita
  - ollama_models somente leitura (o servidor precisa gravar manifests-v2)
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent
REQUIRED = "translategemma:12b"
BASE = "http://127.0.0.1:11434"


def _writable(p: Path) -> bool:
    try:
        probe = p / ".sf_probe"
        probe.write_text("x", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def find_cli() -> str | None:
    for sub in ("", "bin", "app", "Ollama", "ollama", r"Ollama\bin", r"ollama\bin"):
        c = ROOT / sub / "ollama.exe" if sub else ROOT / "ollama.exe"
        try:
            if c.is_file():
                return str(c)
        except OSError:
            pass
    w = shutil.which("ollama")
    if w:
        return w
    lad = os.environ.get("LOCALAPPDATA") or ""
    c = Path(lad) / "Programs" / "Ollama" / "ollama.exe"
    return str(c) if c.is_file() else None


def pick_models_dir() -> Path:
    for name in ("ollama_models_v2", "ollama_models"):
        c = ROOT / name
        if c.is_dir() and _writable(c):
            return c
    for name in ("ollama_models_v2", "ollama_models"):
        c = ROOT / name
        if c.is_dir():
            return c
    return ROOT / "ollama_models"


def probe(base: str = BASE) -> tuple[bool, list[str], str]:
    try:
        with urlopen(base.rstrip("/") + "/api/tags", timeout=5) as r:
            data = json.loads(r.read().decode("utf-8", "replace") or "{}")
        return True, [((i.get("name") or i.get("model") or "").strip()) for i in (data.get("models") or [])], ""
    except Exception as e:
        return False, [], f"{type(e).__name__}: {e}"


def main() -> int:
    do_start = "--start" in sys.argv
    do_test = "--test" in sys.argv

    print("=" * 64)
    print(" DIAGNOSTICO DO OLLAMA — SubForgeAI")
    print("=" * 64)

    print("\n[1] Executavel")
    cli = find_cli()
    if not cli:
        print("    NAO ENCONTRADO")
        return 1
    print("    encontrado:", cli)
    print("    tamanho   : {0:.1f} MB".format(Path(cli).stat().st_size / 1048576))

    print("\n[2] Pasta de modelos")
    models = pick_models_dir()
    print("    escolhida:", models)
    for name in ("ollama_models", "ollama_models_v2"):
        c = ROOT / name
        if c.is_dir():
            mark = "GRAVAVEL" if _writable(c) else "SOMENTE LEITURA"
            print(f"      {name:18} {mark}")
    if models.is_dir():
        total = sum(f.stat().st_size for f in models.rglob("*") if f.is_file())
        print("    tamanho   : {0:.2f} GB".format(total / 1024**3))
        man = models / "manifests"
        if man.is_dir():
            for m in sorted(man.rglob("*")):
                if m.is_file():
                    ps = m.relative_to(man).parts
                    if len(ps) >= 4:
                        print("      modelo:", f"{ps[-2]}:{ps[-1]}")

    print("\n[3] Perfil do usuario")
    up = Path(os.environ.get("USERPROFILE") or Path.home())
    if _writable(up):
        print("    gravavel :", up)
        env_extra = {}
    else:
        alt = ROOT / ".ollama_home"
        alt.mkdir(parents=True, exist_ok=True)
        print("    SEM ESCRITA:", up)
        print("    -> redirecionando para:", alt)
        env_extra = {"USERPROFILE": str(alt), "HOME": str(alt)}

    print("\n[4] Servidor", BASE)
    ok, names, err = probe()
    if not ok and do_start:
        print("    offline — iniciando `ollama serve`...")
        env = os.environ.copy()
        env["OLLAMA_MODELS"] = str(models)
        env.update(env_extra)
        subprocess.Popen(
            [cli, "serve"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        for i in range(30):
            time.sleep(1)
            ok, names, err = probe()
            if ok:
                print(f"    ONLINE apos {i + 1}s")
                break
    if ok:
        print("    ONLINE — modelos:", len(names))
        for n in sorted(names):
            print("      -", n)
    else:
        print("    OFFLINE —", err)
        print("    rode com --start para levantar o servidor")

    print("\n[5] Modelo exigido")
    print("    modelo:", REQUIRED)
    if ok:
        hit = any(n == REQUIRED or n.startswith(REQUIRED) for n in names)
        print("    disponivel:", hit)
        if not hit:
            return 2
    else:
        print("    nao verificado (servidor offline)")

    if do_test and ok:
        print("\n[6] Teste de traducao")
        tmp = Path(os.environ.get("TEMP", ".")) / "sf_ollama_test"
        tmp.mkdir(parents=True, exist_ok=True)
        src = tmp / "t.srt"
        src.write_text(
            "1\n00:00:01,000 --> 00:00:02,000\nHello, world!\n\n"
            "2\n00:00:03,000 --> 00:00:04,000\nGood morning.\n",
            encoding="utf-8",
        )
        script = ROOT / "ollama_script.py"
        python = ROOT / "runtime" / "python" / "python.exe"
        r = subprocess.run(
            [str(python), "-B", str(script), str(src), "--outdir", str(tmp),
             "--model", REQUIRED, "--review", "auto", "--force"],
            capture_output=True, text=True, errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        print("    exit:", r.returncode)
        outs = [p for p in tmp.glob("*.srt") if p.name != "t.srt"]
        for o in sorted(outs, key=lambda x: x.stat().st_mtime)[-1:]:
            print(f"    --- {o.name} ---")
            print("\n".join("      " + l for l in o.read_text(encoding="utf-8").splitlines()))
        if r.returncode != 0:
            print("    --- stderr ---")
            print("\n".join("      " + l for l in (r.stderr or "").splitlines()[-15:]))
            return 3

    print("\n" + "=" * 64)
    print(" PRONTO PARA TRADUZIR" if ok else " INSTALADO — servidor parado (use --start)")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
