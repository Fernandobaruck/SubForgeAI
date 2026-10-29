"""Validate the installed Studio launcher, resources and six QML pages."""
from pathlib import Path
import json
import subprocess
import sys

ROOT = Path(sys.argv[1]).resolve() if len(sys.argv)>1 else Path(__file__).resolve().parents[1]
required = ['SubForgeAI Studio.exe', '_studio_boot/python311.dll',
            'runtime/python/pythonw.exe', 'studio_launcher.py', 'studio_bootstrap.py',
            'studio_ui/process_runtime.py', 'studio_ui/runtime.py', 'studio_ui/backend.py',
            'studio_ui/pipeline.py', 'studio_ui/queue_model.py', 'studio_ui/qml/Main.qml',
            'assets/brand/subforge-studio.ico', 'whisper_script.py', 'ollama_script.py',
            'extract_subs.py', 'embed_script.py', 'whisper_audio.py', 'tools/ffmpeg/ffmpeg.exe',
            'speech_context.py', 'speech_refinement.py', 'pgs_ocr.py',
            'series_registry.py', 'review_workspace.py', 'source_selection.py', 'season_tools.py', 'fansub_tools.py', 'maintenance_tools.py', 'update_core.py', 'release_crypto.py', 'release_info.py', 'studio_update_worker.py', 'studio_ui/update_controller.py', 'studio_ui/qml/UpdatesPage.qml', 'studio_ui/maintenance_controller.py', 'studio_ui/qml/MaintenanceDialog.qml', 'studio_ui/fansub_controller.py', 'studio_ui/qml/FansubDialog.qml',
            'studio_ui/season_controller.py', 'studio_ui/qml/SeasonDialog.qml',
            'studio_ui/review_controller.py', 'studio_ui/qml/ReviewPage.qml',
            'studio_ui/qml/GlossaryPage.qml', 'studio_ui/qml/SourceDialog.qml',
            'studio_ui/presentation.py', 'studio_ui/locales/en.json', 'studio_ui/locales/es.json',
            'studio_ui/qml/Tr.qml', 'studio_ui/qml/qmldir',
            'runtime/python/Lib/site-packages/PySide6/translations/qtbase_es.qm',
            'runtime/python/Lib/site-packages/PySide6/translations/qtbase_pt_BR.qm',
            'tools/ffmpeg/ffprobe.exe']
for name in required:
    assert (ROOT/name).is_file(), 'Missing resource: '+name
for path in (ROOT/'studio_ui').glob('*.py'):
    compile(path.read_text(encoding='utf-8-sig'), str(path), 'exec')
log = ROOT/'logs/studio/launcher.log'
offset = log.stat().st_size if log.exists() else 0
process = subprocess.run([str(ROOT/'SubForgeAI Studio.exe'), '--smoke-test'],cwd=ROOT, timeout=25)
assert process.returncode == 0, 'Studio launch failed'
with log.open('rb') as stream:
    stream.seek(offset)
    lines = stream.read().decode('utf-8',errors='replace').splitlines()
records = [json.loads(line) for line in lines if line.startswith('{') and 'qml_loaded' in line]
assert records and records[-1]['qml_loaded'] and records[-1]['pages_loaded']==9
assert records[-1]['tkinter_loaded'] is False
print(json.dumps(dict(resources_present=True, executable_exit=0, pages_loaded=9, tkinter_loaded=False)))
