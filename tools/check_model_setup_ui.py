"""Offline UI verification: model guide, selection persistence and scrolling."""
import os, sys, tempfile, json, time
from unittest.mock import patch
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
os.environ['QT_QPA_PLATFORM']='offscreen';os.environ['QT_QUICK_BACKEND']='software'
from PySide6.QtCore import QObject,QUrl,QMetaObject,Qt,qInstallMessageHandler
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from studio_ui.backend import Backend
from test_priority_one import FakeRuntime
app=QApplication([]);QQuickStyle.setStyle('Basic')
for name in ('segoeui.ttf','segoeuib.ttf','bahnschrift.ttf'):
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/'+name)
messages=[];qInstallMessageHandler(lambda kind,context,message:messages.append(message))
with tempfile.TemporaryDirectory(dir=ROOT/'tests') as folder:
    root=Path(folder);(root/'config.json').write_text('{"custom":"preserve"}')
    backend=Backend(root,FakeRuntime(),monitor_enabled=False)
    engine=QQmlApplicationEngine();engine.rootContext().setContextProperty('Backend',backend)
    engine.addImportPath(str(ROOT/'studio_ui/qml'));engine.load(QUrl.fromLocalFile(str(ROOT/'studio_ui/qml/Main.qml')))
    assert engine.rootObjects(),messages
    window=engine.rootObjects()[0];dialog=window.findChild(QObject,'setupDialog');assert dialog
    QMetaObject.invokeMethod(dialog,'open',Qt.DirectConnection);QTest.qWait(200)
    assert dialog.property('visible')
    assert len(backend.setup.translationModels)==3
    assert len(backend.setup.whisperModels)==6
    for entry in backend.setup.whisperModels:
        assert entry['vram'] and entry['gpus'] and entry['recommended_gb']>0
        backend.setup.selectWhisper(entry['code'])
        assert backend.settings['whisper_model']==entry['code']
        assert json.loads((root/'config.json').read_text())['whisper_model']==entry['code']
    backend.setup.selectWhisper('large-v3-turbo')
    for model in ('translategemma:4b','translategemma:27b','translategemma:12b'):
        backend.setup.selectTranslation(model);QTest.qWait(50)
        assert backend.settings['ollama_model']==model
        assert json.loads((root/'config.json').read_text())['ollama_model']==model
        assert json.loads((root/'config.json').read_text())['custom']=='preserve'
    source=root/'example.srt';source.write_text('1\n00:00:01,000 --> 00:00:04,000\nHello.\n',encoding='utf-8')
    for model in ('translategemma:4b','translategemma:27b'):
        backend.setup.selectTranslation(model)
        with patch.object(backend.runtime,'_ensure_ollama_ready',return_value=True) as ready:
            backend.addFiles([str(source)]);backend.start('translate')
            deadline=time.monotonic()+10
            while backend.busy and time.monotonic()<deadline:
                app.processEvents();time.sleep(.01)
            app.processEvents();assert not backend.busy
            assert ready.call_args.kwargs['required_model']==model
            command=backend.runtime.commands[-1]
            assert command[command.index('--model')+1]==model
            backend._items=[];backend.changed.emit()
    backend.setup.selectTranslation('translategemma:12b')
    for size in ((1060,700),(1280,840)):
        window.resize(*size);QTest.qWait(60)
        assert dialog.property('height')<=window.height()-40
    errors=[m for m in messages if any(t in m for t in ('Error','Binding loop','Cannot assign','Unable to assign'))]
    assert not errors,errors
    out=ROOT/'reviews/model-setup';out.mkdir(parents=True,exist_ok=True)
    window.grabWindow().save(str(out/'setup.png'))
    scroll=window.findChild(QObject,'modelGuideScroll');flick=scroll.property('contentItem')
    flick.setProperty('contentY',min(850,max(0,flick.property('contentHeight')-flick.property('height'))));QTest.qWait(100)
    assert window.grabWindow().save(str(out/'whisper-models.png'))
    backend.shutdown();window.close()
    print(json.dumps(dict(model_selection=True,settings_preserved=True,scrolling_dialog=True,qml_errors=errors)))
