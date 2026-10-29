"""SubForgeAI Studio Qt Quick entry point."""
from pathlib import Path
import os
import sys


def main():
    root = Path(sys.executable if getattr(sys, 'frozen', False) else __file__).resolve().parent
    if not getattr(sys, 'frozen', False): sys.path.insert(0, str(root))
    from update_core import recover,app_lease
    health='--update-health' in sys.argv and '--smoke-test' in sys.argv
    if not health:
        if recover(root):
            import subprocess
            subprocess.Popen([sys.executable,'-B','-X','utf8',str(root/'studio_launcher.py'),*sys.argv[1:]],cwd=root,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            return 0
        lease=app_lease(root);lease.__enter__()
    else:lease=None
    from PySide6.QtCore import QUrl, QTimer, QCoreApplication, QEvent, qInstallMessageHandler
    from PySide6.QtGui import QIcon
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuickControls2 import QQuickStyle
    from PySide6.QtWidgets import QApplication
    from studio_ui import process_runtime
    from studio_ui.runtime import Runtime
    from studio_ui.backend import Backend
    app = QApplication(sys.argv)
    app.setApplicationName('SubForgeAI Studio')
    app.setOrganizationName('SubForgeAI')
    app.setWindowIcon(QIcon(str(root / 'assets/brand/subforge-studio.ico')))
    qt_log = root / 'logs/studio/qt.log'
    qt_log.parent.mkdir(parents=True, exist_ok=True)
    qt_log.write_text('', encoding='utf-8')
    qml_errors=[]
    def qt_message(kind, context, message):
        if any(term in message for term in ('ReferenceError','TypeError','Unable to assign','Cannot assign','Binding loop')):qml_errors.append(message)
        try:
            with qt_log.open('a', encoding='utf-8') as f: f.write(message + '\n')
        except OSError: pass
        if '--smoke-test' in sys.argv: print(message, file=sys.stderr, flush=True)
    qInstallMessageHandler(qt_message)
    QQuickStyle.setStyle('Basic')
    backend = Backend(root, Runtime(process_runtime, root), monitor_enabled='--smoke-test' not in sys.argv)
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty('Backend', backend)
    resource_root = Path(getattr(sys, '_MEIPASS', root))
    engine.load(QUrl.fromLocalFile(str(resource_root / 'studio_ui/qml/Main.qml')))
    if not engine.rootObjects():
        backend.shutdown()
        raise RuntimeError('Não foi possível carregar Main.qml; consulte logs/studio/qt.log.')
    (root / 'logs/studio/startup_error.log').unlink(missing_ok=True)
    backend.closeReady.connect(app.quit)
    app.aboutToQuit.connect(backend.shutdown)
    if '--smoke-test' in sys.argv:
        page_count = len(engine.rootObjects()[0].property('pages').toVariant())
        smoke_pages = iter(range(1, page_count))
        def smoke():
            page = next(smoke_pages, None)
            if page is not None:
                engine.rootObjects()[0].setProperty('page', page)
                QTimer.singleShot(200, smoke)
                return
            import json
            print(json.dumps({'qml_loaded': True, 'window_title': engine.rootObjects()[0].title(),
                              'pages_loaded': page_count,'app_version':backend.updater.installed,'qml_errors':qml_errors, 'tkinter_loaded': 'tkinter' in sys.modules, 'whisper_model': backend.settings['whisper_model']}), flush=True)
            app.quit()
        QTimer.singleShot(1000, smoke)
    result = app.exec()
    # Destroy QML bindings while their Python context object is still alive.
    engine.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    if lease:lease.__exit__(None,None,None)
    return 1 if '--smoke-test' in sys.argv and qml_errors else result


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:
        import traceback
        root = Path(sys.executable if getattr(sys, 'frozen', False) else __file__).resolve().parent
        log = root / 'logs/studio/startup_error.log'
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(traceback.format_exc(), encoding='utf-8')
        if '--smoke-test' in sys.argv: raise
        import ctypes
        from studio_bootstrap import startup_text
        ctypes.windll.user32.MessageBoxW(0, startup_text(root,'qt_failed'), 'SubForgeAI Studio', 0x10)
        sys.exit(1)
