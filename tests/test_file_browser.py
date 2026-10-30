"""Native picker configuration, portable folder history and multi-file selection."""
import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import QCoreApplication
from studio_ui.backend import Backend
from studio_ui.file_browser import FileLocations

class Runtime:
    def _stop_managed_ollama_server(self,**kwargs):pass
    def kill_all_active_procs(self):pass

class FileBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QCoreApplication.instance() or QCoreApplication([])
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent);self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.media=self.root/'media';self.media.mkdir()
    def test_last_folder_persists_and_missing_folder_uses_fallback(self):
        locations=FileLocations(self.root);source=self.media/'episode.srt';source.touch()
        locations.remember('input',source)
        self.assertEqual(FileLocations(self.root).start('input'),str(self.media))
        locations.locations['input']=str(self.root/'removed')
        self.assertEqual(locations.start('input',self.media),str(self.media))
        before=locations.path.read_bytes();locations.remember('input','');self.assertEqual(locations.path.read_bytes(),before)
    def test_native_multi_select_filters_and_cancel_preserve_queue(self):
        backend=Backend(self.root,Runtime(),monitor_enabled=False);self.addCleanup(backend.shutdown)
        paths=[self.media/'episode.srt',self.media/'episode02.mkv']
        for p in paths:p.touch()
        with patch('studio_ui.backend.QFileDialog.getOpenFileNames',return_value=([str(p) for p in paths],'')) as dialog:
            backend.chooseFiles()
        from PySide6.QtWidgets import QFileDialog
        self.assertFalse(dialog.call_args.kwargs['options'] & QFileDialog.Option.DontUseNativeDialog)
        self.assertTrue(dialog.call_args.kwargs['options'] & QFileDialog.Option.HideNameFilterDetails)
        self.assertIn('*.srt',dialog.call_args.args[3]);self.assertIn('*.mkv',dialog.call_args.args[3])
        self.assertEqual(len(dialog.call_args.args[3].split(';;')),5)
        self.assertEqual(len(backend._items),2)
        with patch('studio_ui.backend.QFileDialog.getOpenFileNames',return_value=([],'')) as dialog:
            backend.chooseFiles()
        self.assertEqual(dialog.call_args.args[2],str(self.media));self.assertEqual(len(backend._items),2)

if __name__=='__main__':unittest.main()
