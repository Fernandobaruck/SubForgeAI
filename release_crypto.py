"""Windows CNG RSA/SHA-256 signatures; private keys protected with user DPAPI."""
import ctypes,struct,hashlib,os
from ctypes import wintypes

def _api():
    if os.name!='nt':raise OSError('Assinaturas do atualizador exigem Windows.')
    api=ctypes.WinDLL('bcrypt');ptr=ctypes.c_void_p;u=ctypes.c_ulong
    definitions={'BCryptOpenAlgorithmProvider':([ctypes.POINTER(ptr),wintypes.LPCWSTR,wintypes.LPCWSTR,u]),'BCryptGenerateKeyPair':([ptr,ctypes.POINTER(ptr),u,u]),'BCryptFinalizeKeyPair':([ptr,u]),'BCryptExportKey':([ptr,ptr,wintypes.LPCWSTR,ptr,u,ctypes.POINTER(u),u]),'BCryptImportKeyPair':([ptr,ptr,wintypes.LPCWSTR,ctypes.POINTER(ptr),ptr,u,u]),'BCryptSignHash':([ptr,ptr,ptr,u,ptr,u,ctypes.POINTER(u),u]),'BCryptVerifySignature':([ptr,ptr,ptr,u,ptr,u,u]),'BCryptDestroyKey':([ptr]),'BCryptCloseAlgorithmProvider':([ptr,u])}
    for name,args in definitions.items():function=getattr(api,name);function.argtypes=args;function.restype=ctypes.c_long
    return api

def _ok(status):
    if status<0:raise OSError('Falha criptográfica do Windows: '+hex(status&0xffffffff))

def _provider(api):
    handle=ctypes.c_void_p();_ok(api.BCryptOpenAlgorithmProvider(ctypes.byref(handle),'RSA',None,0));return handle

def _export(api,key,kind):
    length=ctypes.c_ulong();_ok(api.BCryptExportKey(key,None,kind,None,0,ctypes.byref(length),0));buffer=ctypes.create_string_buffer(length.value);_ok(api.BCryptExportKey(key,None,kind,buffer,length.value,ctypes.byref(length),0));return buffer.raw[:length.value]

def generate_key():
    api=_api();provider=_provider(api);key=ctypes.c_void_p()
    try:
        _ok(api.BCryptGenerateKeyPair(provider,ctypes.byref(key),3072,0));_ok(api.BCryptFinalizeKeyPair(key,0));return _export(api,key,'RSAPUBLICBLOB'),_export(api,key,'RSAFULLPRIVATEBLOB')
    finally:
        if key:api.BCryptDestroyKey(key)
        api.BCryptCloseAlgorithmProvider(provider,0)

def _crypt(blob,data,signature=None,private=False):
    api=_api();provider=_provider(api);key=ctypes.c_void_p();buffer=ctypes.create_string_buffer(blob)
    class Padding(ctypes.Structure):_fields_=[('algorithm',wintypes.LPCWSTR)]
    padding=Padding('SHA256');hashed=ctypes.create_string_buffer(hashlib.sha256(data).digest())
    try:
        _ok(api.BCryptImportKeyPair(provider,None,'RSAFULLPRIVATEBLOB' if private else 'RSAPUBLICBLOB',ctypes.byref(key),buffer,len(blob),0))
        if not private:
            if not isinstance(signature,bytes) or len(signature)!=384:return False
            sig=ctypes.create_string_buffer(signature);return api.BCryptVerifySignature(key,ctypes.byref(padding),hashed,32,sig,len(signature),2)==0
        length=ctypes.c_ulong();_ok(api.BCryptSignHash(key,ctypes.byref(padding),hashed,32,None,0,ctypes.byref(length),2));out=ctypes.create_string_buffer(length.value);_ok(api.BCryptSignHash(key,ctypes.byref(padding),hashed,32,out,length.value,ctypes.byref(length),2));return out.raw[:length.value]
    finally:
        if key:api.BCryptDestroyKey(key)
        api.BCryptCloseAlgorithmProvider(provider,0)

def sign(private,data):return _crypt(private,data,private=True)
def verify(public,data,signature):return _crypt(public,data,signature)

def protect(data,unprotect=False):
    if os.name!='nt':raise OSError('DPAPI exige Windows.')
    class Blob(ctypes.Structure):_fields_=[('length',wintypes.DWORD),('data',ctypes.c_void_p)]
    buffer=ctypes.create_string_buffer(data);source=Blob(len(data),ctypes.cast(buffer,ctypes.c_void_p));target=Blob();api=ctypes.WinDLL('crypt32',use_last_error=True)
    if unprotect:
        function=api.CryptUnprotectData;function.argtypes=[ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)];ok=function(ctypes.byref(source),None,None,None,None,1,ctypes.byref(target))
    else:
        function=api.CryptProtectData;function.argtypes=[ctypes.POINTER(Blob),wintypes.LPCWSTR,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)];ok=function(ctypes.byref(source),'SubForgeAI release signing',None,None,None,1,ctypes.byref(target))
    if not ok:raise ctypes.WinError(ctypes.get_last_error())
    try:return ctypes.string_at(target.data,target.length)
    finally:
        free=ctypes.WinDLL('kernel32').LocalFree;free.argtypes=[ctypes.c_void_p];free.restype=ctypes.c_void_p;free(target.data)
