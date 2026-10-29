"""Real local Vulkan translation smoke test, isolated owned Ollama server."""
import sys,socket,json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from studio_ui.runtime import Runtime
from studio_ui import process_runtime as P
from studio_ui.gpu_policy import ensure_ollama_gpu,request_json
import ollama_script as O
with socket.socket() as sock:
    sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
host='127.0.0.1:'+str(port)
processes=SimpleNamespace(OLLAMA_BASE_URL='http://'+host,OLLAMA_MODELS_DIR=ROOT/'ollama_models_v2',
    _find_ollama_cli=lambda:str(ROOT/'ollama.exe'),_pick_managed_ollama_host=lambda:host,
    _subprocess_hide_window_kwargs=P._subprocess_hide_window_kwargs,_kill_process_tree=P._kill_process_tree)
runtime=Runtime(processes,ROOT)
try:
    with patch('studio_ui.gpu_policy.cuda_available',return_value=False):
        assert runtime._ensure_ollama_ready(log_fn=print,required_model='translategemma:12b')
    row=ensure_ollama_gpu(processes.OLLAMA_BASE_URL,'translategemma:12b')
    text=O._ollama_call('translategemma:12b',[{'role':'user','content':'Translate English to Brazilian Portuguese. Produce only the translation.\n\nHello, my friend.'}])
    report=dict(backend='vulkan',size=row['size'],size_vram=row['size_vram'],translation=text)
    folder=ROOT/'reviews/gpu-policy';folder.mkdir(parents=True,exist_ok=True)
    (folder/'translation-vulkan.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False),flush=True)
finally:
    runtime._stop_managed_ollama_server(log_fn=print)
