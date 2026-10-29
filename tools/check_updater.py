"""Real signed install/health/rollback in an isolated copy plus update-page UI."""
import os,sys,json,uuid,shutil,subprocess,base64,argparse,time
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
os.environ['QT_QPA_PLATFORM']='offscreen';os.environ['QT_QUICK_BACKEND']='software'
import update_core as U
from release_crypto import generate_key
from tools.prepare_release import build
from PySide6.QtCore import QObject,QUrl,QCoreApplication,QEvent,qInstallMessageHandler
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase,QFont
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from studio_ui.backend import Backend
from test_priority_one import FakeRuntime
from tools.check_priority_one_ui import click

def wait(review,app):
    deadline=time.monotonic()+90
    while review.busy and time.monotonic()<deadline:app.processEvents();QTest.qWait(10)
    app.processEvents();assert not review.busy, "Update file verification did not finish within 90 seconds"

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--online',action='store_true');args=parser.parse_args()
    out=ROOT/'reviews/updater';folder=out/'integration'/uuid.uuid4().hex[:8];root=folder/'app';root.mkdir(parents=True)
    candidates=list(ROOT.glob('*.py'))+[ROOT/'docs/STUDIO.md']
    for directory in ('studio_ui','assets/brand'):candidates.extend(p for p in (ROOT/directory).rglob('*') if p.is_file())
    for path in candidates:
        rel=path.relative_to(ROOT).as_posix()
        if U.allowed(rel):target=root/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
    public,private=generate_key();pin=base64.b64encode(public).decode();source=root/'release_info.py';text=source.read_text('utf-8');import re
    source.write_text(re.sub(r'(?m)^PUBLIC_KEY_B64\s*=.*','PUBLIC_KEY_B64 = '+repr(pin),text),encoding='utf-8')
    original=source.read_bytes();(root/'config.json').write_text('{"custom":777}');personal=root/'outputs/pt-br/personal.srt';personal.parent.mkdir(parents=True);personal.write_bytes(b'PERSONAL');models=root/'cache/model.bin';models.parent.mkdir(parents=True);models.write_bytes(b'MODEL')
    with patch.object(U,'PUBLIC_KEY_B64',pin):
        package,manifest=build(root,folder/'package','1.0.1',private);envelope=json.loads(manifest.read_text('utf-8'));job=root/'.updates/jobs'/uuid.uuid4().hex;job.mkdir(parents=True);shutil.copy2(package,job/'package.zip');U.extract_verified(root,job,envelope['manifest'],job/'package.zip');U.save_json(job/'manifest.json',envelope)
        def health():
            process=subprocess.run([str(ROOT/'runtime/python/python.exe'),'-B','-X','utf8',str(root/'studio_launcher.py'),'--smoke-test','--update-health'],cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=40)
            (folder/'health.log').write_text(process.stdout+'\n'+process.stderr,encoding='utf-8');return process.returncode==0 and '"pages_loaded": 9' in process.stdout
        U.apply(root,job,health);assert "1.0.1" in source.read_text('utf-8');U.rollback(root,job);assert source.read_bytes()==original
        try:U.apply(root,job,lambda:False)
        except ValueError:pass
        else:raise AssertionError('health failure must roll back')
        assert source.read_bytes()==original and personal.read_bytes()==b'PERSONAL' and models.read_bytes()==b'MODEL'
        app=QApplication([])
        for name in ('segoeui.ttf','segoeuib.ttf','bahnschrift.ttf','consola.ttf','YuGothR.ttc'):QFontDatabase.addApplicationFont(str(Path('C:/Windows/Fonts')/name))
        app.setFont(QFont('Segoe UI',10));QQuickStyle.setStyle('Basic');messages=[];qInstallMessageHandler(lambda kind,context,msg:messages.append(msg))
        backend=Backend(root,FakeRuntime(),monitor_enabled=False);updater=backend.updater;review=backend.review
        engine=QQmlApplicationEngine();engine.rootContext().setContextProperty('Backend',backend);engine.load(QUrl.fromLocalFile(str(ROOT/'studio_ui/qml/Main.qml')));assert engine.rootObjects();window=engine.rootObjects()[0];window.setProperty('page',8);QTest.qWait(150)
        with patch('studio_ui.update_controller.latest_release',return_value=None):click(window,'checkUpdates');wait(review,app)
        assert 'Ainda não há' in updater.status and not updater.canDownload
        release=dict(version='1.0.1',notes='Atualização de teste\n<script>texto sem execução</script>',page=updater.releasePage,zip_url='https://github.com/'+U.REPOSITORY+'/releases/download/v1.0.1/SubForgeAI-update-1.0.1.zip',envelope=envelope)
        with patch('studio_ui.update_controller.latest_release',return_value=release):click(window,'checkUpdates');wait(review,app)
        assert updater.canDownload
        def fetch(url,limit,cancel=None,destination=None,progress=None):Path(destination).write_bytes(package.read_bytes());progress(len(package.read_bytes()),limit)
        with patch.object(U,'fetch',side_effect=fetch):click(window,'downloadUpdate');wait(review,app)
        assert updater.ready and updater.progress==1
        with patch.object(updater,'_launch') as launch,patch.object(backend,'requestClose') as close:
            click(window,'installUpdate');QTest.qWait(50);assert window.findChild(QObject,'updateInstallConfirmation').property('visible');launch.assert_not_called();click(window,'confirmAppUpdate');launch.assert_called_once();close.assert_called_once()
        combinations=[]
        for language in ('pt-BR','en','es'):
            backend.updateSetting('ui_language',language)
            for theme in ('dark','light'):
                backend.updateSetting('ui_theme',theme);QTest.qWait(150);combinations.append((language,theme));window.grabWindow().save(str(out/f'{language}_{theme}.png'))
        window.setWidth(1060);window.setHeight(700);QTest.qWait(100);window.grabWindow().save(str(out/'minimum.png'))
        assert json.loads((root/'config.json').read_text('utf-8'))['custom']==777
        backend.shutdown();review.join();engine.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete)
        errors=[m for m in messages if any(word in m for word in ('ReferenceError','TypeError','Unable to assign','Binding loop','Cannot assign','is not a type'))];assert not errors,errors
    online='not_requested'
    if args.online:online='no_release' if U.latest_release() is None else 'release_found'
    result=dict(signature_verified=True,isolated_install=True,actual_qt_health=True,manual_rollback=True,failed_health_rollback=True,personal_data_preserved=True,models_preserved=True,download_ui=True,install_confirmation=True,combinations=len(combinations),qml_errors=errors,online=online,folder=str(folder))
    (out/'integration-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
