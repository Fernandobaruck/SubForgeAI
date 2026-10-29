"""Exercise glossary preview, contributions, AI and history in every UI locale/theme."""
from pathlib import Path
import os,sys,json,tempfile
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ['QT_QPA_PLATFORM']='offscreen';os.environ['QT_QUICK_BACKEND']='software'
from PySide6.QtCore import QObject,QUrl,QMetaObject,Qt,qInstallMessageHandler
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from studio_ui.backend import Backend
from studio_ui.online_glossary import preview,fingerprint

class Runtime:
    def kill_all_active_procs(self):pass
    def _stop_managed_ollama_server(self,**kwargs):pass

def main():
    app=QApplication([]);QQuickStyle.setStyle('Basic')
    for name in ('segoeui.ttf','segoeuib.ttf','bahnschrift.ttf'):QFontDatabase.addApplicationFont('C:/Windows/Fonts/'+name)
    messages=[];qInstallMessageHandler(lambda kind,context,message:messages.append(message))
    out=ROOT/'reviews/online_glossary';out.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=ROOT/'tests') as name:
        backend=Backend(Path(name),Runtime(),monitor_enabled=False);backend.review.createProject('Anime de demonstração')
        backend.review.saveTerm('Tower','Torre aprovada',True);backend.review.saveTerm('Name','Nome',False)
        online=backend.review.online
        online._catalog=[dict(id='sample',title='Glossário de demonstração',description='Prévia sintética de termos novos, repetidos e conflitantes.',revision='1',source_language='en',target_language='pt-BR',sha256='0'*64)]
        online._entry=online._catalog[0];online._rows=preview(backend.review.terms,[dict(source='Tower',target='Torre diferente'),dict(source='Name',target='Nome'),dict(source='Guild',target='Guilda')])
        online._expected=fingerprint(backend.review.terms);online.selectNew();online.selectShare('Tower',True)
        engine=QQmlApplicationEngine();engine.rootContext().setContextProperty('Backend',backend);engine.addImportPath(str(ROOT/'studio_ui/qml'))
        engine.load(QUrl.fromLocalFile(str(ROOT/'studio_ui/qml/Main.qml')));assert engine.rootObjects(),messages
        window=engine.rootObjects()[0];window.setProperty('page',7);QTest.qWait(100)
        dialog=window.findChild(QObject,'onlineGlossaryDialog');assert dialog is not None
        combinations=0
        for language in ('pt-BR','en','es'):
            for theme in ('dark','light'):
                backend.updateSetting('ui_language',language);backend.updateSetting('ui_theme',theme)
                for section in range(4):
                    dialog.setProperty('section',section);QMetaObject.invokeMethod(dialog,'open',Qt.DirectConnection);QTest.qWait(100)
                    assert dialog.property('visible');assert window.grabWindow().save(str(out/f'{language}_{theme}_{section}.png'));combinations+=1
                QMetaObject.invokeMethod(dialog,'close',Qt.DirectConnection)
        online.importSelected();assert any(row['source']=='Guild' and not row['confirmed'] for row in backend.review.terms)
        assert backend.review.registry.confirmed(backend.review.selectedProject)=={'Tower':'Torre aprovada'}
        errors=[m for m in messages if 'Error' in m or 'failed' in m or 'Binding loop' in m or 'Cannot assign' in m]
        assert not errors,errors
        backend.timer.stop();backend.review.fansub.timer.stop();window.close()
        print(json.dumps(dict(dialog_combinations=combinations,conflict_preserved=True,import_is_unconfirmed=True,qml_errors=errors)))

if __name__=='__main__':main()
