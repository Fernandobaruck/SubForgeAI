"""Exercise the native window and real worker using ephemeral signed fixtures."""
import base64,json,os,shutil,subprocess,sys,tempfile,threading,time,zipfile
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.build_visual_installer import build
from release_crypto import generate_key,sign
from update_core import canonical,file_sha

def wait_for(predicate,timeout=40):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        value=predicate()
        if value:return value
        time.sleep(.1)
    raise AssertionError('Timed out waiting for installer state')

def read_json(path):
    try:return json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError,ValueError):return {}

def main():
    output=ROOT/'reviews/visual-installer';output.mkdir(parents=True,exist_ok=True)
    public,private=generate_key();key=base64.b64encode(public).decode();version='0.0.0'
    with tempfile.TemporaryDirectory(prefix='visual-integration-',dir=output) as temporary:
        base=Path(temporary);assert base.resolve().is_relative_to(output.resolve())
        source=base/'source';source.mkdir();installed=base/'Nova pasta ç';profile=base/'profile';profile.mkdir()
        archive=source/'payload.zip'
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_STORED) as z:
            z.writestr('SubForgeAI Studio.exe',b'test fixture - never execute')
            z.writestr('studio_ui/qml/qmldir','module Studio\n')
            z.writestr('fixture.bin',bytes(range(256))*65536)
        data=archive.read_bytes();parts=[]
        for i,start in enumerate(range(0,len(data),8*1024**2),1):
            p=source/f'SubForgeAI-portable-{version}.part{i:02}.bin';p.write_bytes(data[start:start+8*1024**2]);parts.append(dict(name=p.name,size=p.stat().st_size,sha256=file_sha(p)))
        payload=dict(schema='subforge-portable-1',version=version,repository='Fernandobaruck/SubForgeAI',zip_size=len(data),zip_sha256=file_sha(archive),raw_size=17*1024**2,parts=parts)
        encoded=canonical(payload);envelope=dict(payload_b64=base64.b64encode(encoded).decode(),signature=base64.b64encode(sign(private,encoded)).decode())
        (source/f'SubForgeAI-portable-{version}.manifest.json').write_text(json.dumps(envelope),encoding='utf-8')
        exe=build(ROOT,base/'gui',version,public_key=key,download_bytes=len(data),installed_bytes=payload['raw_size'])
        result_file=base/'gui-result.json'
        args=[str(exe),'--fixture-source',str(source),'--fixture-destination',str(installed),'--test-result',str(result_file),'--screenshot',str(output/'installed.png')]
        env=dict(os.environ,LOCALAPPDATA=str(profile))
        result=subprocess.run(args,env=env,timeout=45,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        state=read_json(result_file)
        if result.returncode:
            details=Path(state.get('log',''))
            raise AssertionError(str(state)+'\n'+(details.read_text(encoding='utf-8-sig',errors='replace') if details.is_file() else ''))
        state=read_json(result_file);assert state['phase']=='complete',state
        assert (installed/'fixture.bin').read_bytes()==bytes(range(256))*65536
        sentinel=installed/'keep.txt';sentinel.write_text('keep');result_file.unlink()
        result=subprocess.run(args,env=env,timeout=20,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0));assert result.returncode!=0
        assert sentinel.read_text()=='keep' and read_json(result_file)['phase']=='error'

        requests=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                name=self.path.rsplit('/',1)[-1];path=source/name
                if not path.is_file():self.send_error(404);return
                content=path.read_bytes();header=self.headers.get('Range');offset=int(header.split('=')[1].split('-')[0]) if header else 0
                requests.append((name,offset))
                self.send_response(206 if offset else 200);self.send_header('Content-Length',str(len(content)-offset))
                if offset:self.send_header('Content-Range',f'bytes {offset}-{len(content)-1}/{len(content)}')
                self.end_headers()
                try:
                    for pos in range(offset,len(content),16384):
                        self.wfile.write(content[pos:pos+16384]);self.wfile.flush()
                        if name.endswith('.bin'):time.sleep(.01)
                except (BrokenPipeError,ConnectionResetError,OSError):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True;thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        worker=(ROOT/'tools/installer/Instalar.ps1').read_text(encoding='utf-8').replace('__VERSION__',version).replace('__REPOSITORY__','Fernandobaruck/SubForgeAI').replace('__PUBLIC_KEY__',key)
        worker=worker.replace('"https://github.com/$repository/releases/download/v$version/"',f'"http://127.0.0.1:{server.server_port}/"')
        script=base/'Instalar.ps1';script.write_bytes(b'\xef\xbb\xbf'+worker.encode('utf-8'));shutil.copyfile(ROOT/'tools/installer/DownloadEngine.cs',base/'DownloadEngine.cs')
        progress=base/'progress.json';control=base/'control.json'
        def action(value):
            tmp=control.with_suffix('.new');tmp.write_text(json.dumps(dict(action=value)),encoding='utf-8');os.replace(tmp,control)
        def start(destination):
            progress.unlink(missing_ok=True);action('resume')
            log=(base/(destination.name+'.log')).open('wb')
            process=subprocess.Popen(['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(script),'-DestinationPath',str(destination),'-ProgressPath',str(progress),'-ControlPath',str(control),'-Connections','2','-NoLaunch'],env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            return process,log
        running=[];logs=[]
        try:
            destination=base/'download-and-resume';process,log=start(destination);running.append(process);logs.append(log)
            wait_for(lambda:read_json(progress).get('stage')=='download' and read_json(progress).get('completed',0)>512*1024)
            action('pause');wait_for(lambda:read_json(progress).get('stage')=='paused')
            cache=profile/'SubForgeAI-install'/version
            sizes={p.name:p.stat().st_size for p in cache.glob('*.bin')};time.sleep(.5)
            assert sizes=={p.name:p.stat().st_size for p in cache.glob('*.bin')},'Downloads continued while paused'
            action('resume');code=process.wait(timeout=45);log.close();assert code==0,(base/(destination.name+'.log')).read_text(errors='replace')
            assert (destination/'fixture.bin').is_file();assert any(offset>0 for name,offset in requests if name.endswith('.bin'))
            assert read_json(progress)['stage']=='complete'
            destination=base/'cancelled';process,log=start(destination);running.append(process);logs.append(log)
            wait_for(lambda:read_json(progress).get('stage')=='download' and read_json(progress).get('completed',0)>512*1024)
            action('cancel');code=process.wait(timeout=20);log.close();assert code==2,code
            assert read_json(progress)['stage']=='cancelled' and not destination.exists()
            assert any(p.stat().st_size>0 for p in cache.glob('*.bin'))
        finally:
            for p in running:
                if p.poll() is None:p.kill();p.wait(timeout=10)
            for stream in logs:stream.close()
            server.shutdown();server.server_close()
        result=dict(graphical_executable_install=True,unicode_and_space_paths=True,existing_destination_preserved=True,real_http_pause=True,paused_bytes_stable=True,resume_uses_http_range=True,cancel_preserves_partial_downloads=True,complete_progress_reported=True)
        (output/'functional-check.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))

if __name__=='__main__':main()
