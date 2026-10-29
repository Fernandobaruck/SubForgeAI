"""GPU-only safety: deny CPU/mixed inference before prompts reach a model."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
from studio_ui import gpu_policy as G
from studio_ui.vulkan_support import VulkanWhisper, model_path, extract_runtime, probe

class GPUOnlyTests(unittest.TestCase):
    def setUp(self):
        mocked=patch.object(G,"cuda_available",return_value=True);mocked.start();self.addCleanup(mocked.stop)

    def resident(self,vram=100):
        return {'models':[{'name':'translategemma:12b','size':100,'size_vram':vram,'context_length':4096}]}

    def test_cpu_and_missing_cuda_cannot_start_inference(self):
        with patch.object(G,'cuda_available',return_value=False):
            for device in ('cpu','cuda'):
                with self.assertRaises(G.GPURequiredError):G.inference_device(device)
            self.assertEqual(G.inference_device('auto'),'vulkan')
        with patch.object(G,'cuda_available',return_value=True):
            self.assertEqual(G.inference_device('auto'),'cuda')
            self.assertEqual(G.inference_device('vulkan'),'vulkan')

    def test_partial_cpu_load_is_rejected_and_unloaded_without_prompt(self):
        with patch.object(G,'request_json',side_effect=[self.resident(50),{},self.resident(50),{}]) as request:
            with self.assertRaisesRegex(G.GPURequiredError,'parcialmente'):
                G.ensure_ollama_gpu('http://127.0.0.1:11434','translategemma:12b')
        posts=[call.args[2] for call in request.call_args_list if len(call.args)>2]
        self.assertEqual(len(posts),2)
        self.assertTrue(all(body['prompt']=='' for body in posts))
        self.assertEqual(posts[0]['options']['num_gpu'],999)
        self.assertEqual(posts[-1]['keep_alive'],0)

    def test_no_hardware_gpu_does_not_even_load_the_model_on_cpu(self):
        with patch.object(G,'cuda_available',return_value=False),patch.object(G,'vulkan_devices',return_value=[]),patch.object(G,'request_json',return_value={'models':[]}) as request:
            with self.assertRaisesRegex(G.GPURequiredError,'Nenhuma GPU'):
                G.ensure_ollama_gpu('http://127.0.0.1:11434','translategemma:12b')
        self.assertEqual(request.call_count,1)
        self.assertEqual(request.call_args.args[1],'/api/ps')

    def test_fully_resident_model_does_not_reload(self):
        with patch.object(G,'request_json',return_value=self.resident()) as request:
            G.ensure_ollama_gpu('http://127.0.0.1:11434','translategemma:12b')
        self.assertEqual(request.call_count,1)

    def test_invalid_residency_or_wrong_model_cannot_pass(self):
        for value in ({'models':[]},self.resident(0),self.resident(True),{'models':[{'name':'other','size':1,'size_vram':1}]}):
            with self.assertRaises(G.GPURequiredError):G.verify_residency(value,'translategemma:12b')

    def test_changed_context_is_preloaded_without_generating_text(self):
        previous=self.resident();previous['models'][0]['context_length']=8192
        with patch.object(G,'request_json',side_effect=[previous,{},self.resident()]) as request:
            G.ensure_ollama_gpu('http://127.0.0.1:11434','translategemma:12b')
        body=request.call_args_list[1].args[2]
        self.assertEqual(body['prompt'],'')
        self.assertEqual(body['options']['num_ctx'],4096)

    def test_cancel_interrupts_gpu_preload(self):
        import time, http.client
        cancel=threading.Event();shutdown=threading.Event()
        with patch('studio_ui.gpu_policy.http.client.HTTPConnection') as cls:
            connection=cls.return_value
            connection.sock.shutdown.side_effect=lambda how:shutdown.set()
            def loading():
                if not shutdown.wait(3):raise AssertionError('Cancellation did not interrupt model load')
                raise http.client.RemoteDisconnected('cancelled')
            connection.getresponse.side_effect=loading
            timer=threading.Timer(.15,cancel.set);timer.start();started=time.monotonic()
            try:
                with self.assertRaisesRegex(G.GPURequiredError,'interrompida'):
                    G.request_json('http://127.0.0.1:11434','/api/generate',{'prompt':''},cancel)
            finally:timer.join()
            self.assertLess(time.monotonic()-started,1.5)

    def test_vulkan_owned_server_hides_cuda_and_rocm(self):
        env=G.ollama_environment(True)
        self.assertEqual(env['OLLAMA_VULKAN'],'1')
        for key in ('CUDA_VISIBLE_DEVICES','HIP_VISIBLE_DEVICES','ROCR_VISIBLE_DEVICES'):
            self.assertEqual(env[key],'-1')
        self.assertNotIn('CUDA_VISIBLE_DEVICES',G.ollama_environment(False))

    def test_translation_gpu_denial_never_submits_user_text(self):
        import ollama_script as O
        with patch.object(G,'ensure_ollama_gpu',side_effect=G.GPURequiredError('CPU bloqueada')),patch.object(O,'_ollama_stream') as stream:
            with self.assertRaises(G.GPURequiredError):O._ollama_call('translategemma:12b',[{'role':'user','content':'private'}])
        stream.assert_not_called()

    def test_glossary_gpu_denial_never_submits_user_text(self):
        from studio_ui.glossary_ai import suggest
        with patch.object(G,'ensure_ollama_gpu',side_effect=G.GPURequiredError('CPU bloqueada')),patch('studio_ui.glossary_ai.http.client.HTTPConnection') as connection:
            with self.assertRaises(G.GPURequiredError):suggest('http://127.0.0.1:11434','private','en',threading.Event())
        connection.assert_not_called()

    def test_vulkan_must_confirm_actual_backend_before_audio(self):
        for log in ('','whisper_backend_init_gpu: no GPU found','whisper_backend_init_gpu: using CUDA0 backend',
                    'whisper_backend_init_gpu: using Vulkan0 backend\nfailed to allocate'):
            with self.assertRaises(G.GPURequiredError):VulkanWhisper.validate_log(log)
        VulkanWhisper.validate_log('whisper_backend_init_gpu: using Vulkan0 backend')

    def test_vulkan_cpu_model_weights_are_rejected(self):
        with self.assertRaises(G.GPURequiredError):
            VulkanWhisper.validate_log('whisper_backend_init_gpu: using Vulkan0 backend\nwhisper_model_load: CPU total size = 100 MB')

    def test_software_vulkan_device_does_not_count_as_gpu(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);folder=root/'tools/whispercpp';folder.mkdir(parents=True)
            (folder/'whisper-cli.exe').touch();(folder/'ggml-vulkan.dll').touch()
            with patch('studio_ui.vulkan_support.subprocess.run',return_value=Mock(stdout='ggml_vulkan: 0 = llvmpipe (LLVM)')):
                with self.assertRaises(G.GPURequiredError):probe(root)
            with patch('studio_ui.vulkan_support.subprocess.run',return_value=Mock(stdout='ggml_vulkan: 0 = Intel Arc A770 | fp16: 1')):
                self.assertIn('Intel Arc',probe(root)['name'])

    def test_no_arbitrary_model_substitution(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);folder=root/'models/whispercpp';folder.mkdir(parents=True)
            (folder/'ggml-large-v3.bin').touch()
            self.assertFalse(model_path(root,'large-v3-turbo').exists())

    def test_unverified_runtime_archive_is_never_extracted(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);archive=root/'bad.zip';archive.write_bytes(b'bad')
            with self.assertRaises(ValueError):extract_runtime(archive,root)
            self.assertFalse((root/'tools').exists())

    def test_demucs_never_attempts_cpu(self):
        import whisper_script as W
        with tempfile.TemporaryDirectory() as directory,patch.object(G,'cuda_available',return_value=False),patch.object(W.subprocess,'run') as run:
            result,_=W.run_demucs(Path('python'),Path('audio'),Path(directory)/'stems',project_root=Path(directory))
        self.assertIsNone(result);run.assert_not_called()

    def test_faster_neural_cpu_vad_is_disabled(self):
        import whisper_script as W
        self.assertFalse(W._build_faster_kwargs(language='ja',task='transcribe',vad_filter=True)['vad_filter'])

if __name__=='__main__':unittest.main()
