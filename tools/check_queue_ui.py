"""Offscreen component check: full season, completed history and stable scroll."""
from pathlib import Path
import json
import os
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ['QT_QPA_PLATFORM']='offscreen'
from PySide6.QtCore import QObject,QUrl,QCoreApplication,QEvent
from PySide6.QtWidgets import QApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from studio_ui.backend import Backend


class Runtime:
    def _stop_managed_ollama_server(self,**kwargs):pass
    def kill_all_active_procs(self):pass


def main():
    app=QApplication([]);QQuickStyle.setStyle('Basic')
    with tempfile.TemporaryDirectory(prefix='queue-ui-',dir=ROOT/'tests') as folder:
        base=Path(folder);(base/'config.json').write_text('{}')
        backend=Backend(base,Runtime(),monitor_enabled=False)
        paths=[]
        for number in range(26):
            path=base/f'episode{number:02}.srt';path.touch();paths.append(str(path))
        backend.addFiles(paths[:2])
        for item in backend._items:item['state']='Concluído'
        backend.addFiles(paths[2:])
        engine=QQmlApplicationEngine();engine.rootContext().setContextProperty('Backend',backend)
        engine.load(QUrl.fromLocalFile(str(ROOT/'studio_ui/qml/Main.qml')))
        assert engine.rootObjects(),'QML failed to load'
        window=engine.rootObjects()[0];window.setProperty('page',1);QTest.qWait(250)
        view=window.findChild(QObject,'episodeQueueList')
        assert view is not None
        assert view.property('count')==26
        assert view.property('contentHeight')>view.property('height')
        view.setProperty('contentY',600.0);QTest.qWait(50)
        before=float(view.property('contentY'))
        backend._items[2].update(state='Executando',progress=.3)
        backend.changed.emit();QTest.qWait(100)
        after=float(view.property('contentY'))
        assert abs(before-after)<1,(before,after)
        assert backend.completed==2 and backend.queueModel.rowCount()==26
        result=dict(visible_items=26,completed_preserved=2,pending_added=24,scroll_before=before,scroll_after=after,scroll_preserved=True)
        backend.shutdown();engine.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete)
    (ROOT/'docs/validation/queue_ui.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result))


if __name__=='__main__':main()
