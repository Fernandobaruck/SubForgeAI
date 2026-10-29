"""First-use regressions: incomplete installs, model state and data exclusion."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from studio_ui import setup_support as first_run
from tools.build_portable import files


class FirstRunTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_empty_install_lists_missing_components_and_models(self):
        state = first_run.inspect(self.root)
        self.assertIn('runtime/python/python.exe', state['missing'])
        self.assertIn('studio_ui/qml/qmldir', state['missing'])
        self.assertFalse(state['translation'])
        self.assertFalse(any(state['whisper'].values()))

    def test_manifest_without_all_blobs_is_not_ready(self):
        path = self.root / 'ollama_models_v2/manifests/registry.ollama.ai/library/translategemma/12b'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({'config': {'digest': 'sha256:aaa'}, 'layers': [{'digest': 'sha256:bbb'}]}))
        self.assertFalse(first_run.inspect(self.root)['translation'])
        blob = self.root / 'ollama_models_v2/blobs'; blob.mkdir()
        (blob / 'sha256-aaa').touch()
        self.assertFalse(first_run.inspect(self.root)['translation'])
        (blob / 'sha256-bbb').touch()
        self.assertTrue(first_run.inspect(self.root)['translation'])

    def test_partial_whisper_is_not_ready(self):
        snapshot = self.root / 'cache/hub/models--Systran--faster-whisper-large-v3/snapshots' / ('a'*40)
        snapshot.mkdir(parents=True)
        (snapshot/'model.bin').touch(); (snapshot/'config.json').touch()
        self.assertFalse(first_run.inspect(self.root)['whisper']['large-v3'])
        (snapshot/'tokenizer.json').touch()
        self.assertTrue(first_run.inspect(self.root)['whisper']['large-v3'])

    def test_unknown_model_is_rejected_without_writes(self):
        with self.assertRaises(ValueError):
            first_run.download(self.root, '../anything', lambda *a: None, threading.Event())
        self.assertEqual(list(self.root.iterdir()), [])

    def test_cancel_before_start_does_not_contact_network(self):
        cancel = threading.Event(); cancel.set()
        with self.assertRaisesRegex(RuntimeError, 'interrompido'):
            first_run.download(self.root, 'translation', lambda *a: None, cancel)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_low_disk_space_fails_before_downloading(self):
        with patch('studio_ui.setup_support.shutil.disk_usage', return_value=type('Space', (), {'free': 0})()):
            with self.assertRaisesRegex(ValueError, 'Espaço'):
                first_run.download(self.root, 'translation', lambda *a: None, threading.Event())

    def test_distribution_excludes_user_data_models_and_static_libraries(self):
        keep = ['studio_ui/setup_support.py', 'studio_ui/qml/qmldir', 'runtime/python/python.exe', 'runtime/python/Lib/site-packages/torch/lib/torch.dll']
        excluded = ['config.json', 'glossary.json', 'outputs/private.srt', 'cache/hub/model.bin', 'ollama_models_v2/blobs/weights', 'runtime/python/Lib/site-packages/torch/lib/dnnl.lib', 'runtime/python/__pycache__/secret.pyc', 'lib/private.lnk']
        for name in keep+excluded:
            p = self.root/name; p.parent.mkdir(parents=True, exist_ok=True); p.touch()
        selected = {relative for _, relative in files(self.root)}
        self.assertTrue(set(keep) <= selected)
        self.assertTrue(set(excluded).isdisjoint(selected))


if __name__ == '__main__': unittest.main()
