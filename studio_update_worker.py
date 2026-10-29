"""Independent updater: copied to .updates before Studio exits; never edits runtime/models."""
from pathlib import Path
import argparse,json,os,subprocess,time,sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from update_core import app_lease,recover,job_path,apply,rollback,save_json,live_pid

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',required=True);parser.add_argument('--job',required=True);parser.add_argument('--wait-pids',default='');parser.add_argument('--rollback',action='store_true');parser.add_argument('--no-relaunch',action='store_true');args=parser.parse_args()
    root=Path(args.root).resolve();job=job_path(root,args.job);pids=[int(p) for p in args.wait_pids.split(',') if p];deadline=time.monotonic()+90;flags=getattr(subprocess,'CREATE_NO_WINDOW',0)
    while any(live_pid(p) for p in pids):
        if time.monotonic()>deadline:raise RuntimeError('O Studio ainda está aberto. A instalação não foi iniciada.')
        time.sleep(.2)
    try:
        with app_lease(root,True):
            recover(root,True);lock=root/'.updates/install.lock'
            with lock.open('x',encoding='utf-8') as stream:json.dump({'pid':os.getpid()},stream)
            try:
                def health():
                    env=os.environ.copy();env.update(QT_QPA_PLATFORM='offscreen',QT_QUICK_BACKEND='software')
                    command=[str(root/'SubForgeAI Studio.exe'),'--smoke-test','--update-health']
                    launcher_log=root/'logs/studio/launcher.log';offset=launcher_log.stat().st_size if launcher_log.exists() else 0
                    with (job/'health.log').open('ab') as output:
                        code=subprocess.run(command,cwd=root,env=env,stdout=output,stderr=output,creationflags=flags,timeout=60).returncode
                    expected=json.loads((job/'manifest.json').read_text('utf-8'))['manifest']['version'];records=[]
                    with launcher_log.open('rb') as stream:stream.seek(offset);lines=stream.read().decode('utf-8',errors='replace').splitlines()
                    for line in lines:
                        if line.startswith('{'):
                            try:records.append(json.loads(line))
                            except ValueError:pass
                    return code==0 and bool(records) and records[-1].get('app_version')==expected and not records[-1].get('qml_errors')
                if args.rollback:rollback(root,job)
                else:apply(root,job,health)
                save_json(root/'.updates/last_result.json',dict(ok=True,rollback=args.rollback,job=job.name))
            finally:lock.unlink(missing_ok=True)
    except Exception as exc:
        save_json(root/'.updates/last_result.json',dict(ok=False,error=str(exc),job=job.name))
    if not args.no_relaunch:subprocess.Popen([str(root/'SubForgeAI Studio.exe')],cwd=root,creationflags=flags)

if __name__=='__main__':
    try:main()
    except Exception:
        import traceback
        Path(__file__).with_name('worker_error.log').write_text(traceback.format_exc(),encoding='utf-8')
        sys.exit(1)
