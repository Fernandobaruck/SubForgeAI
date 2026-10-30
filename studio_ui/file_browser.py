"""Portable last-folder history; native file dialogs remain owned by the platform."""
import json
from pathlib import Path
from PySide6.QtCore import QStandardPaths
from pipeline_io import atomic_write_text


class FileLocations:
    def __init__(self, root):
        self.path=Path(root)/'outputs/studio/file_browser.json'
        try:
            data=json.loads(self.path.read_text(encoding='utf-8'))
            self.locations={k:v for k,v in data.items() if isinstance(k,str) and isinstance(v,str)} if isinstance(data,dict) else {}
        except (OSError,ValueError):self.locations={}

    def start(self, purpose, fallback=None):
        for candidate in (self.locations.get(purpose),fallback,
                QStandardPaths.writableLocation(QStandardPaths.MoviesLocation),
                QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation),str(Path.home())):
            if candidate and Path(candidate).is_dir():return str(Path(candidate).resolve())
        return str(Path.home())

    def remember(self, purpose, selected, folder=False):
        if not selected:return
        directory=Path(selected) if folder else Path(selected).parent
        if not directory.is_dir():return
        self.locations[purpose]=str(directory.resolve())
        try:atomic_write_text(self.path,json.dumps(self.locations,ensure_ascii=False,indent=2))
        except OSError:pass  # A read-only portable folder must not prevent file selection.
