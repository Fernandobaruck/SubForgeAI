"""Exercise the optional visual preset and ASS export in six UI combinations."""
from pathlib import Path
import os,sys,tempfile,time,json
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ['QT_QPA_PLATFORM']='offscreen';os.environ['QT_QUICK_BACKEND']='software'
from PySide6.QtCore import QObject,QUrl,QMetaObject,Qt,qInstallMessageHandler
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from studio_ui.backend import Backend

class Runtime:
    def kill_all_active_procs(self):pass
    def _stop_managed_ollama_server(self,**kwargs):pass

def main():
    app=QApplication([]);QQuickStyle.setStyle('Basic')
    for name in ('segoeui.ttf','segoeuib.ttf','bahnschrift.ttf','arial.ttf','arialbd.ttf','trebuc.ttf','trebucbd.ttf'):
        QFontDatabase.addApplicationFont('C:/Windows/Fonts/'+name)
    messages=[];qInstallMessageHandler(lambda kind,ctx,message:messages.append(message))
    out=ROOT/'reviews/reference_style';out.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=ROOT/'tests') as name:
        root=Path(name);source=root/'sample.srt';original='1\n00:00:01,000 --> 00:00:04,000\nUma fala de exemplo.\n';source.write_text(original,encoding='utf-8')
        backend=Backend(root,Runtime(),monitor_enabled=False)
        engine=QQmlApplicationEngine();engine.rootContext().setContextProperty('Backend',backend);engine.addImportPath(str(ROOT/'studio_ui/qml'));engine.load(QUrl.fromLocalFile(str(ROOT/'studio_ui/qml/Main.qml')))
        assert engine.rootObjects(),messages
        window=engine.rootObjects()[0];window.setProperty('page',6);QTest.qWait(100)
        dialog=window.findChild(QObject,'fansubDialog');assert dialog is not None
        shortcut=window.findChild(QObject,'openSubtitleStyle');assert shortcut is not None and shortcut.property('visible')
        QMetaObject.invokeMethod(shortcut,'clicked',Qt.DirectConnection);QTest.qWait(80)
        assert dialog.property('visible') and dialog.property('section')==1 and not backend.review.loaded
        QMetaObject.invokeMethod(dialog,'close',Qt.DirectConnection)
        backend.review.openDocument(str(source))
        while backend.busy:app.processEvents();time.sleep(.01)
        QMetaObject.invokeMethod(shortcut,'clicked',Qt.DirectConnection)
        for language in ('pt-BR','en','es'):
            for theme in ('dark','light'):
                backend.updateSetting('ui_language',language);backend.updateSetting('ui_theme',theme);QTest.qWait(80)
                button=dialog.findChild(QObject,'exportReferenceStyle');assert button is not None
                QMetaObject.invokeMethod(button,'clicked',Qt.DirectConnection);QTest.qWait(50)
                assert backend.review.fansub.preset['bold'] and backend.review.fansub.preset['font']=='Trebuchet MS'
                assert dialog.findChild(QObject,'exportBold').property('checked')
                assert backend.review.fansub.fontAvailable
                assert window.grabWindow().save(str(out/f'ui-{language}-{theme}.png'))
                QMetaObject.invokeMethod(dialog.findChild(QObject,'exportDefaultStyle'),'clicked',Qt.DirectConnection)
                assert not backend.review.fansub.preset['bold'] and backend.review.fansub.preset['size']==48
        QMetaObject.invokeMethod(dialog.findChild(QObject,'exportReferenceStyle'),'clicked',Qt.DirectConnection)
        QMetaObject.invokeMethod(dialog.findChild(QObject,'fansubExport'),'clicked',Qt.DirectConnection)
        deadline=time.monotonic()+10
        while backend.busy and time.monotonic()<deadline:app.processEvents();time.sleep(.01)
        app.processEvents();assert not backend.busy
        exports=list((root/'outputs/studio/exports').glob('*.ass'));assert len(exports)==1
        assert 'Style: Dialogue,Trebuchet MS,66,' in exports[0].read_text(encoding='utf-8-sig')
        assert json.loads(Path(str(exports[0])+'.export.json').read_text(encoding='utf-8'))['preset']['bold'] is True
        assert source.read_text(encoding='utf-8')==original
        errors=[m for m in messages if 'Error' in m or 'Binding loop' in m or 'Cannot assign' in m]
        assert not errors,errors
        backend.timer.stop();backend.review.fansub.timer.stop();window.close()
        print(json.dumps(dict(combinations=6,reference_button=True,default_button=True,bold_preserved_on_export=True,original_unchanged=True,qml_errors=errors)))

if __name__=='__main__':main()
