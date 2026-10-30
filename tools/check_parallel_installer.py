"""Real native downloads: concurrency, prefix resume, HTTP retries and ignored Range."""
from pathlib import Path
import hashlib,json,re,subprocess,tempfile,threading,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
ROOT=Path(__file__).resolve().parents[1]
DATA=bytes(range(256))*16384
lock=threading.Lock();active=0;peak=0;calls={};ranges=[]
class Handler(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'
    def log_message(self,*args):pass
    def do_GET(self):
        global active,peak
        with lock:
            active+=1;peak=max(peak,active);calls[self.path]=calls.get(self.path,0)+1;attempt=calls[self.path]
        try:
            self.close_connection=True
            if self.path=='/retry' and attempt==1:
                self.send_response(503);self.send_header('Connection','close');self.send_header('Content-Length','0');self.end_headers();return
            offset=0
            if self.headers.get('Range') and self.path!='/ignored':
                offset=int(re.fullmatch(r'bytes=(\d+)-',self.headers['Range'])[1])
                ranges.append(offset)
            self.send_response(206 if offset else 200)
            self.send_header('Connection','close')
            self.send_header('Content-Length',str(len(DATA)-offset))
            if offset:self.send_header('Content-Range',f'bytes {offset}-{len(DATA)-1}/{len(DATA)}')
            self.end_headers()
            for start in range(offset,len(DATA),65536):
                self.wfile.write(DATA[start:start+65536]);self.wfile.flush();time.sleep(.004)
        finally:
            with lock:active-=1
server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
try:
    with tempfile.TemporaryDirectory(dir=ROOT/'reviews') as name:
        folder=Path(name);routes=['one','two','three','four','ignored','retry']
        files=[folder/(route+'.bin') for route in routes]
        files[0].write_bytes(DATA[:12345]);files[4].write_bytes(DATA[:54321])
        urls=['http://127.0.0.1:'+str(server.server_port)+'/'+route for route in routes]
        quote=lambda value:"'"+str(value).replace("'","''")+"'"
        script="Add-Type -Path "+quote(ROOT/'tools/installer/DownloadEngine.cs')+"\n"
        script+="$job=[SubForgeDownloadSession]::Start([string[]]@("+','.join(map(quote,urls))+"),[string[]]@("+','.join(map(quote,files))+"),[long[]]@("+','.join([str(len(DATA))]*len(files))+"),4)\ntry { $job.Wait() } finally { $job.Dispose() }\n"
        target=folder/'test.ps1';target.write_text("$ErrorActionPreference='Stop'\n"+script,encoding='utf-8-sig')
        result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(target)],capture_output=True,text=True,timeout=45,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        assert result.returncode==0,(result.stdout,result.stderr)
        for path in files:assert hashlib.sha256(path.read_bytes()).digest()==hashlib.sha256(DATA).digest(),path
        assert 2<=peak<=4,peak
        assert 12345 in ranges and calls['/retry']==2
        print(json.dumps(dict(parallel_connections_peak=peak,all_parts_verified=True,legacy_prefix_resumed=True,ignored_range_restarts=True,transient_error_retried=True)))
finally:
    server.shutdown();server.server_close();thread.join()
