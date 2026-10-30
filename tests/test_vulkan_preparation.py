"""Missing Vulkan dependencies must be repaired before GPU inference."""
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from studio_ui import vulkan_support as V


class VulkanPreparationTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.cancel = threading.Event()

    def test_missing_runtime_is_prepared_then_probed(self):
        with patch.object(V, 'installed', side_effect=[False, True]), patch.object(V, 'prepare') as prepare, patch.object(V, 'probe') as probe:
            cli, model = V.ensure_ready(self.root, 'small', Mock(), self.cancel)
        self.assertEqual(prepare.call_args.args[:2], (self.root, 'small'))
        probe.assert_called_once_with(self.root)
        self.assertEqual(cli, self.root/'tools/whispercpp/whisper-cli.exe')
        self.assertEqual(model, V.model_path(self.root, 'small'))

    def test_existing_installation_does_not_download(self):
        with patch.object(V, 'installed', return_value=True), patch.object(V, 'prepare') as prepare, patch.object(V, 'probe') as probe:
            V.ensure_ready(self.root, 'large-v3', Mock(), self.cancel)
        prepare.assert_not_called()
        probe.assert_called_once()

    def test_incomplete_repair_cannot_reach_gpu_probe(self):
        with patch.object(V, 'installed', return_value=False), patch.object(V, 'prepare'), patch.object(V, 'probe') as probe:
            with self.assertRaisesRegex(V.GPURequiredError, 'incompleta'):
                V.ensure_ready(self.root, 'small', Mock(), self.cancel)
        probe.assert_not_called()

    def test_download_failure_does_not_start_inference(self):
        with patch.object(V, 'installed', return_value=False), patch.object(V, 'prepare', side_effect=RuntimeError('offline')), patch.object(V, 'probe') as probe:
            with self.assertRaisesRegex(RuntimeError, 'offline'):
                V.ensure_ready(self.root, 'small', Mock(), self.cancel)
        probe.assert_not_called()

    def test_software_gpu_is_still_rejected(self):
        with patch.object(V, 'installed', return_value=True), patch.object(V, 'probe', side_effect=V.GPURequiredError('Nenhuma GPU')):
            with self.assertRaisesRegex(V.GPURequiredError, 'Nenhuma GPU'):
                V.ensure_ready(self.root, 'small', Mock(), self.cancel)


if __name__ == '__main__':
    unittest.main()
