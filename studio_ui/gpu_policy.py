"""Mandatory GPU inference. CPU orchestration and audio preprocessing remain allowed."""
import json
import http.client
import socket
import threading
from functools import lru_cache
from urllib.parse import urlsplit

class GPURequiredError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def cuda_available():
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


@lru_cache(maxsize=1)
def vulkan_devices():
    """Enumerate real adapters via the Vulkan loader, without loading any model."""
    import ctypes as C
    import os
    class InstanceInfo(C.Structure):
        _fields_ = [('sType',C.c_uint32),('pNext',C.c_void_p),('flags',C.c_uint32),
            ('application',C.c_void_p),('layerCount',C.c_uint32),('layers',C.c_void_p),
            ('extensionCount',C.c_uint32),('extensions',C.c_void_p)]
    class MemoryType(C.Structure):
        _fields_ = [('flags',C.c_uint32),('heap',C.c_uint32)]
    class MemoryHeap(C.Structure):
        _fields_ = [('size',C.c_uint64),('flags',C.c_uint32)]
    class MemoryInfo(C.Structure):
        _fields_ = [('typeCount',C.c_uint32),('types',MemoryType*32),
                    ('heapCount',C.c_uint32),('heaps',MemoryHeap*16)]
    instance=C.c_void_p()
    try:
        vk=C.WinDLL('vulkan-1.dll') if os.name=='nt' else C.CDLL('libvulkan.so.1')
        vk.vkCreateInstance.argtypes=[C.POINTER(InstanceInfo),C.c_void_p,C.POINTER(C.c_void_p)]
        vk.vkCreateInstance.restype=C.c_int32
        vk.vkDestroyInstance.argtypes=[C.c_void_p,C.c_void_p];vk.vkDestroyInstance.restype=None
        vk.vkEnumeratePhysicalDevices.argtypes=[C.c_void_p,C.POINTER(C.c_uint32),C.POINTER(C.c_void_p)]
        vk.vkEnumeratePhysicalDevices.restype=C.c_int32
        vk.vkGetPhysicalDeviceProperties.argtypes=[C.c_void_p,C.c_void_p]
        vk.vkGetPhysicalDeviceProperties.restype=None
        vk.vkGetPhysicalDeviceMemoryProperties.argtypes=[C.c_void_p,C.POINTER(MemoryInfo)]
        vk.vkGetPhysicalDeviceMemoryProperties.restype=None
        info=InstanceInfo();info.sType=1
        if vk.vkCreateInstance(C.byref(info),None,C.byref(instance))!=0:return []
        count=C.c_uint32()
        if vk.vkEnumeratePhysicalDevices(instance,C.byref(count),None)!=0 or not 0<count.value<=64:return []
        devices=(C.c_void_p*count.value)()
        if vk.vkEnumeratePhysicalDevices(instance,C.byref(count),devices)!=0:return []
        result=[]
        for handle in devices:
            # VkPhysicalDeviceProperties starts with five uint32 fields and a 256-byte deviceName.
            properties=C.create_string_buffer(4096)
            vk.vkGetPhysicalDeviceProperties(handle,properties)
            kind=C.c_uint32.from_buffer(properties,16).value
            if kind not in (1,2):continue  # Integrated/discrete only; excludes software CPU renderers.
            name=properties.raw[20:276].split(b'\0',1)[0].decode('utf-8',errors='replace')
            memory=MemoryInfo();vk.vkGetPhysicalDeviceMemoryProperties(handle,C.byref(memory))
            local=sum(heap.size for heap in memory.heaps[:min(memory.heapCount,16)] if heap.flags&1)
            result.append(dict(name=name,vram=round(local/1024**3,1),shared=kind==1))
        return result
    except (OSError,AttributeError):return []
    finally:
        if instance.value:vk.vkDestroyInstance(instance,None)


def inference_device(requested='auto'):
    if requested == 'cpu':
        raise GPURequiredError('GPU obrigatória: inferência em CPU foi desativada.')
    if requested == 'vulkan': return 'vulkan'
    if cuda_available(): return 'cuda'
    if requested == 'cuda':
        raise GPURequiredError('CUDA indisponível. Selecione Automático ou Vulkan; a CPU não será utilizada para IA.')
    return 'vulkan'


def ollama_environment(vulkan):
    env = {'OLLAMA_VULKAN': '1', 'OLLAMA_MAX_LOADED_MODELS': '1', 'OLLAMA_NUM_PARALLEL': '1'}
    if vulkan:
        env.update(CUDA_VISIBLE_DEVICES='-1', HIP_VISIBLE_DEVICES='-1', ROCR_VISIBLE_DEVICES='-1')
    return env


def request_json(base, path, body=None, cancel=None, timeout=180):
    parsed = urlsplit(base)
    if parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost', '::1'):
        raise GPURequiredError('A política de GPU exige um servidor Ollama local verificável.')
    if cancel is not None and cancel.is_set(): raise GPURequiredError('Consulta interrompida.')
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=10)
    finished = threading.Event(); watcher = None
    try:
        connection.connect(); client = connection.sock; client.settimeout(timeout)
        if cancel is not None:
            def watch():
                while not finished.wait(.1):
                    if cancel.is_set():
                        try: client.shutdown(socket.SHUT_RDWR)
                        except OSError: pass
                        return
            watcher = threading.Thread(target=watch, daemon=True); watcher.start()
        data = None if body is None else json.dumps(body).encode()
        connection.request('GET' if body is None else 'POST', path, data,
                           {'Content-Type': 'application/json'})
        response = connection.getresponse()
        raw = response.read(2 * 1024 * 1024 + 1)
        if response.status != 200 or len(raw) > 2 * 1024 * 1024:
            raise GPURequiredError('Ollama não confirmou o carregamento na GPU. Confira o registro e a VRAM livre.')
        result = json.loads(raw)
        if not isinstance(result, dict): raise GPURequiredError('Resposta inválida ao verificar a GPU do Ollama.')
        if result.get('error'): raise GPURequiredError(str(result['error']))
        return result
    except (OSError, ValueError, http.client.HTTPException) as exc:
        if cancel is not None and cancel.is_set(): raise GPURequiredError('Consulta interrompida.') from exc
        raise GPURequiredError('Não foi possível verificar a GPU do Ollama: ' + str(exc)) from exc
    finally:
        finished.set(); connection.close()
        if watcher: watcher.join(timeout=1)


def verify_residency(data, model):
    if not isinstance(data, dict) or not isinstance(data.get('models'), list):
        raise GPURequiredError('Ollama não forneceu um inventário de GPU válido.')
    row = next((r for r in data['models'] if isinstance(r,dict) and (r.get('name') or r.get('model')) == model), None)
    if row is None: raise GPURequiredError('O modelo não está carregado na GPU.')
    size, vram = row.get('size'), row.get('size_vram')
    if type(size) is not int or type(vram) is not int or size <= 0 or vram < size:
        raise GPURequiredError('GPU obrigatória: o Ollama carregou o modelo total ou parcialmente na CPU. Libere VRAM ou selecione um TranslateGemma menor em Preparar para começar.')
    return row


_ANNOUNCED = set()


def announce(row, base, model):
    key=(base,model)
    if key not in _ANNOUNCED:
        print('[GPU] Ollama: '+model+' integralmente na GPU ('+str(round(row['size_vram']/1024**3,2))+' GiB).',flush=True)
        _ANNOUNCED.add(key)
    return row


def ensure_ollama_gpu(base, model, cancel=None):
    # Empty prompt loads weights without generating tokens on a CPU fallback.
    data = request_json(base, '/api/ps', cancel=cancel, timeout=10)
    try:
        row = verify_residency(data, model)
        if row.get('context_length') == 4096: return announce(row, base, model)
    except GPURequiredError: pass
    if not cuda_available() and not vulkan_devices():
        raise GPURequiredError('Nenhuma GPU CUDA/Vulkan de hardware foi detectada. A IA em CPU está bloqueada; confira os drivers.')
    request_json(base, '/api/generate', {'model': model, 'prompt': '', 'stream': False,
        'keep_alive': '2m', 'options': {'num_gpu': 999, 'num_ctx': 4096}}, cancel)
    try:
        return announce(verify_residency(request_json(base, '/api/ps', cancel=cancel, timeout=10), model), base, model)
    except GPURequiredError:
        # Release a rejected CPU/mixed load; never submit a translation prompt.
        request_json(base, '/api/generate', {'model': model, 'prompt': '', 'stream': False, 'keep_alive': 0}, cancel)
        raise
