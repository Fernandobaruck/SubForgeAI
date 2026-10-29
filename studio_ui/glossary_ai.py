"""Cancellable local Ollama requests, including slow cold model startup."""
import http.client
import json
import socket
import threading
from urllib.parse import urlsplit
from .online_glossary import text


def suggest(base, source, language, cancel):
    parsed=urlsplit(base)
    if parsed.scheme not in ('http','https') or parsed.hostname not in ('localhost','127.0.0.1','::1') or parsed.username or parsed.password:
        raise ValueError('A sugestão de termos exige um Ollama local.')
    prompt=f'You are a professional {"English (en)" if language=="en" else "Japanese (ja)"} to Brazilian Portuguese (pt-BR) translator. Translate only the following term. Preserve proper names. Produce only the translation, without explanations.\n\n{source}'
    body=json.dumps({'model':'translategemma:12b','messages':[{'role':'user','content':prompt}],'stream':True,'options':{'temperature':0,'num_predict':256}}).encode()
    cls=http.client.HTTPSConnection if parsed.scheme=='https' else http.client.HTTPConnection
    connection=cls(parsed.hostname,parsed.port,timeout=10)
    finished=threading.Event();watcher=None;response=None
    try:
        if cancel.is_set():raise ValueError('Consulta interrompida.')
        connection.connect();client=connection.sock;client.settimeout(180)
        def watch():
            while not finished.wait(.1):
                if cancel.is_set():
                    try:client.shutdown(socket.SHUT_RDWR)
                    except OSError:pass
                    return
        watcher=threading.Thread(target=watch,name='glossary-ai-cancel',daemon=True);watcher.start()
        connection.request('POST',parsed.path.rstrip('/')+'/api/chat',body=body,headers={'Content-Type':'application/json'})
        response=connection.getresponse()
        if response.status!=200:raise ValueError('Ollama: HTTP '+str(response.status))
        output='';complete=False
        for line in response:
            if cancel.is_set():raise ValueError('Consulta interrompida.')
            if not line.strip():continue
            data=json.loads(line)
            if data.get('error'):raise ValueError(str(data['error'])[:1000])
            output+=data.get('message',{}).get('content','')
            complete=complete or data.get('done') is True
            if len(output)>1000:raise ValueError('Resposta da IA maior que o permitido.')
        if cancel.is_set():raise ValueError('Consulta interrompida.')
        if not complete:raise ValueError('A IA não concluiu a sugestão. Tente novamente.')
        return text(output.strip().strip('"'))
    except (OSError,http.client.HTTPException):
        if cancel.is_set():raise ValueError('Consulta interrompida.') from None
        raise
    finally:
        finished.set()
        if response is not None:response.close()
        connection.close()
        if watcher is not None:watcher.join(1)
