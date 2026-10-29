"""Verify the simple workflow: toggle, translate, or style an existing result."""
from pathlib import Path
import os,sys,json,tempfile,time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
os.environ['QT_QPA_PLATFORM']='offscreen';os.environ['QT_QUICK_BACKEND']='software'
from PySide6.QtCore import QObject,QUrl,QPointF,QMetaObject,Qt,qInstallMessageHandler
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from studio_ui.backend import Backend
from test_priority_one import FakeRuntime

def wait(backend,app):
    deadline=time.monotonic()+15
    while backend.busy and time.monotonic()<deadline:app.processEvents();time.sleep(.01)
    app.processEvents();assert not backend.busy

def main():
    app=QApplication([]);QQuickStyle.setStyle('Basic')
    for name in ('segoeui.ttf','segoeuib.ttf','bahnschrift.ttf'):QFontDatabase.addApplicationFont('C:/Windows/Fonts/'+name)
    messages=[];qInstallMessageHandler(lambda kind,context,message:messages.append(message))
    with tempfile.TemporaryDirectory(dir=ROOT/'tests') as folder:
        root=Path(folder);(root/'config.json').write_text('{"custom":"preserve"}')
        source=root/'sample.srt';original='1\n00:00:01,000 --> 00:00:04,000\nExample dialogue.\n';source.write_text(original,encoding='utf-8')
        backend=Backend(root,FakeRuntime(),monitor_enabled=False)
        engine=QQmlApplicationEngine();engine.rootContext().setContextProperty('Backend',backend);engine.addImportPath(str(ROOT/'studio_ui/qml'));engine.load(QUrl.fromLocalFile(str(ROOT/'studio_ui/qml/Main.qml')))
        assert engine.rootObjects(),messages
        window=engine.rootObjects()[0];QTest.qWait(150)
        switch=window.findChild(QObject,'automaticSubtitleStyle');assert switch is not None
        point=switch.mapToScene(QPointF(switch.width()/2,switch.height()/2)).toPoint()
        QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,point);QTest.qWait(60)
        assert backend.settings['subtitle_style']=='reference'
        config=json.loads((root/'config.json').read_text(encoding='utf-8'));assert config['subtitle_style']=='reference' and config['custom']=='preserve'
        for page in (1,2):
            window.setProperty('page',page);QTest.qWait(80);assert window.findChild(QObject,'automaticSubtitleStyle').property('checked')
        backend.addFiles([str(source)]);backend.start('translate');wait(backend,app)
        results=backend._items[0]['results'];assert any(path.endswith('.visual.ass') for path in results),results
        plain=next(path for path in results if path.endswith('.srt'))
        window.setProperty('page',3);QTest.qWait(80);backend.inspectResult(plain);QTest.qWait(50)
        button=window.findChild(QObject,'styleExistingResult');assert button is not None and button.property('enabled')
        QMetaObject.invokeMethod(button,'clicked',Qt.DirectConnection);wait(backend,app)
        assert backend.previewPath.endswith('.ass') and Path(backend.previewPath).is_file()
        assert source.read_text(encoding='utf-8')==original
        errors=[m for m in messages if 'Error' in m or 'Binding loop' in m or 'Cannot assign' in m];assert not errors,errors
        out=ROOT/'reviews/reference_style';window.grabWindow().save(str(out/'simple-results.png'))
        window.setProperty('page',1);QTest.qWait(60);window.grabWindow().save(str(out/'simple-queue.png'))
        backend.timer.stop();backend.review.fansub.timer.stop();window.close()
        print(json.dumps(dict(toggle_persists=True,all_entry_points=True,automatic_translation_output=True,one_click_existing_result=True,original_preserved=True,qml_errors=errors)))

if __name__=='__main__':main()
