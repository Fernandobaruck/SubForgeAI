"""Exercise every language/theme/page combination and capture real QML renders."""
import json,os,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ['QT_QPA_PLATFORM']='offscreen';os.environ['QT_QUICK_BACKEND']='software'
from PySide6.QtCore import QObject,QUrl,QCoreApplication,QEvent,qInstallMessageHandler,QMetaObject,Q_ARG,Qt
from PySide6.QtWidgets import QApplication,QFileDialog,QDialogButtonBox
from PySide6.QtGui import QFontDatabase,QFont
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from studio_ui.backend import Backend
from studio_ui.presentation import COLORS

class Runtime:
    def _stop_managed_ollama_server(self,**kwargs):pass
    def kill_all_active_procs(self):pass


def main():
    app=QApplication([])
    # The offscreen Windows platform does not enumerate system fonts.
    for name in ('segoeui.ttf','segoeuib.ttf','bahnschrift.ttf','consola.ttf','YuGothR.ttc'):
        font=Path('C:/Windows/Fonts')/name
        if font.is_file():QFontDatabase.addApplicationFont(str(font))
    app.setFont(QFont('Segoe UI',10))
    QQuickStyle.setStyle('Basic');messages=[]
    qInstallMessageHandler(lambda kind,context,message:messages.append(message))
    out=ROOT/'reviews/ui_preferences';out.mkdir(exist_ok=True);checks=[]
    with tempfile.TemporaryDirectory(prefix='presentation-',dir=ROOT/'tests') as name:
        base=Path(name);(base/'config.json').write_text('{"custom":42,"whisper_language":"ja","whisper_model":"large-v3"}')
        backend=Backend(base,Runtime(),monitor_enabled=False)
        assert backend.uiTheme=='dark' and backend.uiLanguage=='pt-BR'
        paths=[]
        for i in range(26):
            path=base/f'episode{i+1:02}.srt';path.write_text('1\n00:00:01,000 --> 00:00:03,000\nLegenda de exemplo.\n',encoding='utf-8');paths.append(str(path))
        backend.addFiles(paths)
        backend._items[0].update(state='Concluído',stage='Concluído')
        backend._items[1].update(state='Erro',stage='Falhou',error='O Whisper não confirmou a saída desta execução.')
        backend._metrics={'cpu_pct':24,'ram_pct':37,'gpu_pct':52,'vram_pct':71}
        backend._set_hardware({'text':'NVIDIA GeForce RTX 5070 · 12 GB VRAM · 32 GB RAM'})
        backend.inspectResult(paths[0]);backend.changed.emit()
        engine=QQmlApplicationEngine();engine.rootContext().setContextProperty('Backend',backend)
        engine.load(QUrl.fromLocalFile(str(ROOT/'studio_ui/qml/Main.qml')))
        assert engine.rootObjects(),'QML failed to load';window=engine.rootObjects()[0]
        for language in ('pt-BR','en','es'):
            for theme in ('dark','light'):
                backend.updateSetting('ui_language',language);backend.updateSetting('ui_theme',theme);QTest.qWait(180)
                pages=window.property('pages').toVariant()
                assert pages[0]==backend.translate('Início'),pages
                assert window.property('color').name()==COLORS[theme]['bg']
                for page in range(len(pages)):
                    window.setProperty('page',page);QTest.qWait(200)
                    if page==4:
                        language_box=window.findChild(QObject,'interfaceLanguage');theme_box=window.findChild(QObject,'interfaceTheme')
                        assert language_box is not None and theme_box is not None
                        assert language_box.property('currentIndex')==('pt-BR','en','es').index(language)
                        assert theme_box.property('currentIndex')==('dark','light').index(theme)
                    if page in (0,4) and (language=='pt-BR' or language=='en'):
                        assert window.grabWindow().save(str(out/f'{language}_{theme}_{page}.png'))
                    checks.append(dict(language=language,theme=theme,page=page,loaded=True))
                dialog=QFileDialog();dialog.setOption(QFileDialog.Option.DontUseNativeDialog);dialog.setFileMode(QFileDialog.FileMode.ExistingFile)
                buttons=dialog.findChild(QDialogButtonBox)
                assert buttons is not None
                labels=[button.text() for button in buttons.buttons()]
                if language=='en':assert any('Open' in value for value in labels),labels
                else:assert any('Abrir' in value for value in labels),labels
                dialog.deleteLater()
        # Exercise the same activated handlers used by the visible selectors.
        window.setProperty('page',4);QTest.qWait(150)
        language_box=window.findChild(QObject,'interfaceLanguage')
        language_box.setProperty('currentIndex',1)
        assert QMetaObject.invokeMethod(language_box,'activated',Qt.DirectConnection,Q_ARG(int,1))
        QTest.qWait(80);assert backend.uiLanguage=='en'
        theme_box=window.findChild(QObject,'interfaceTheme')
        theme_box.setProperty('currentIndex',1)
        assert QMetaObject.invokeMethod(theme_box,'activated',Qt.DirectConnection,Q_ARG(int,1))
        QTest.qWait(80);assert backend.uiTheme=='light'
        # A language-only change must retain the light selection.
        backend.updateSetting('ui_language','es');QTest.qWait(80)
        assert theme_box.property('currentIndex')==1
        assert QMetaObject.invokeMethod(window.findChild(QObject,'quickThemeToggle'),'clicked',Qt.DirectConnection)
        QTest.qWait(80);assert backend.uiTheme=='dark'
        # Switching display options must preserve operation identity and queue scroll.
        window.setProperty('page',1);window.setProperty('operationCode','translate');QTest.qWait(200)
        view=window.findChild(QObject,'episodeQueueList');view.setProperty('contentY',600.0);QTest.qWait(30)
        before=float(view.property('contentY'));backend._busy=True
        for language in ('en','es','pt-BR'):
            backend.updateSetting('ui_language',language);QTest.qWait(100)
            assert window.property('operationCode')=='translate'
            selector=window.findChild(QObject,'operationSelector');assert selector.property('currentIndex')==2
            assert abs(float(view.property('contentY'))-before)<1
            assert backend.queueModel.rowCount()==26
            assert backend._items[0]['state']=='Concluído'
            assert backend.items[0]['stateLabel']==backend.translate('Concluído')
        backend._busy=False;backend.updateSetting('ui_theme','dark')
        saved=json.loads((base/'config.json').read_text(encoding='utf-8'));assert saved['custom']==42
        assert saved['whisper_language']=='ja' and saved['whisper_model']=='large-v3'
        # Minimum supported window size and both layouts must load without errors.
        window.setWidth(1060);window.setHeight(700);window.setProperty('page',4)
        for theme in ('light','dark'):
            backend.updateSetting('ui_theme',theme);QTest.qWait(200)
            assert window.grabWindow().save(str(out/f'minimum_{theme}.png'))
        backend.shutdown();engine.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete)
    errors=[message for message in messages if any(word in message for word in ('ReferenceError','TypeError','Unable to assign','Binding loop','is not a type','Cannot assign'))]
    result=dict(combinations=checks,pages_checked=len(checks),queue_preserved=True,operation_preserved=True,preferences_saved=True,qt_dialogs_localized=True,selector_actions_verified=True,qml_errors=errors,qt_messages=messages)
    (out/'ui-check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    assert not errors,errors
    print(json.dumps({key:result[key] for key in result if key not in ('combinations','qt_messages')}))

if __name__=='__main__':main()
