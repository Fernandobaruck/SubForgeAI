"""Small portable executable: start Qt with the project's existing Python.

Qt is installed once in runtime/python, alongside the worker dependencies.
No second copy of Qt, Python, Whisper or the models is embedded in this launcher.
"""
from pathlib import Path
import ctypes
import json
import os
import subprocess
import sys


def startup_text(root, key):
    messages={
        'pt-BR':{'missing_runtime':'Mantenha runtime/python e studio_launcher.py junto deste executável.',
                 'start_failed':'Não foi possível iniciar o Studio: {error}',
                 'qt_failed':'Falha ao abrir o Studio. Detalhes em logs/studio/startup_error.log.'},
        'en':{'missing_runtime':'Keep runtime/python and studio_launcher.py next to this executable.',
              'start_failed':'Could not start Studio: {error}',
              'qt_failed':'Could not open Studio. Details: logs/studio/startup_error.log.'},
        'es':{'missing_runtime':'Mantén runtime/python y studio_launcher.py junto a este ejecutable.',
              'start_failed':'No se pudo iniciar Studio: {error}',
              'qt_failed':'No se pudo abrir Studio. Detalles: logs/studio/startup_error.log.'}}
    try:
        config=json.loads((Path(root)/'config.json').read_text(encoding='utf-8-sig'))
        locale=config.get('ui_language','pt-BR') if isinstance(config,dict) else 'pt-BR'
        if locale not in ('pt-BR','en','es'):locale='pt-BR'
    except (OSError,ValueError):locale='pt-BR'
    return messages[locale][key]


def main():
    root = Path(sys.executable if getattr(sys, 'frozen', False) else __file__).resolve().parent
    python = root / 'runtime/python/pythonw.exe'
    script = root / 'studio_launcher.py'
    try:
        if not python.is_file() or not script.is_file():
            raise FileNotFoundError(startup_text(root,'missing_runtime'))
        env = os.environ.copy()
        env.pop('PYTHONPATH', None)
        env.pop('PYTHONHOME', None)
        env['PYTHONUTF8'] = '1'
        env['PYTHONIOENCODING'] = 'utf-8'
        # A frozen launcher's DLL search directory is inherited by children.
        # Restore Windows defaults before starting the external Python runtime.
        if os.name == 'nt': ctypes.windll.kernel32.SetDllDirectoryW(None)
        log = root / 'logs/studio/launcher.log'
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open('a', encoding='utf-8') as output:
            output.write('Starting SubForgeAI Studio\n'); output.flush()
            child = subprocess.Popen([str(python), '-B', '-X', 'utf8', str(script), *sys.argv[1:]],
                                     cwd=str(root), env=env, stdout=output, stderr=output,
                                     creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            code = child.wait()
            output.write(f'Studio exit={code}\n')
            return code
    except Exception as exc:
        ctypes.windll.user32.MessageBoxW(0, startup_text(root,'start_failed').format(error=str(exc)), 'SubForgeAI Studio', 0x10)
        return 1


if __name__ == '__main__': sys.exit(main())
