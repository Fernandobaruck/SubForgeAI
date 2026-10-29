"""Render first-use preparation in all supported language/theme combinations."""
import os
import sys
import json
import tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['QT_QUICK_BACKEND'] = 'software'
from PySide6.QtCore import QObject, QUrl, QMetaObject, Qt, qInstallMessageHandler
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from studio_ui.backend import Backend


class Runtime:
    def kill_all_active_procs(self): pass
    def _stop_managed_ollama_server(self, **kwargs): pass


def main():
    app = QApplication([]); QQuickStyle.setStyle('Basic')
    for name in ('segoeui.ttf', 'segoeuib.ttf', 'bahnschrift.ttf'):
        QFontDatabase.addApplicationFont('C:/Windows/Fonts/' + name)
    messages = []; qInstallMessageHandler(lambda kind, context, text: messages.append(text))
    out = ROOT/'reviews/first_run'; out.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=ROOT/'tests') as folder:
        backend = Backend(Path(folder), Runtime(), monitor_enabled=False)
        engine = QQmlApplicationEngine(); engine.rootContext().setContextProperty('Backend', backend)
        engine.addImportPath(str(ROOT/'studio_ui/qml')); engine.load(QUrl.fromLocalFile(str(ROOT/'studio_ui/qml/Main.qml')))
        assert engine.rootObjects(), messages
        window = engine.rootObjects()[0]
        dialog = window.findChild(QObject, 'setupDialog'); assert dialog is not None
        for language in ('pt-BR', 'en', 'es'):
            for theme in ('dark', 'light'):
                backend.updateSetting('ui_language', language); backend.updateSetting('ui_theme', theme)
                QMetaObject.invokeMethod(dialog, 'open', Qt.DirectConnection); QTest.qWait(150)
                assert dialog.property('visible')
                assert dialog.property('title') == backend.translate('Preparar para começar')
                assert window.grabWindow().save(str(out/f'{language}_{theme}.png'))
                QMetaObject.invokeMethod(dialog, 'close', Qt.DirectConnection)
        errors = [m for m in messages if 'Error' in m or 'failed' in m or 'Binding loop' in m]
        assert not errors, errors
        backend.timer.stop(); backend.review.fansub.timer.stop(); window.close()
        print(json.dumps(dict(preparation_dialog_combinations=6, qml_errors=errors)))


if __name__ == '__main__': main()
