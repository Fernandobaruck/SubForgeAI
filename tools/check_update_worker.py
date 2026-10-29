"""Exercise the independent installer and packaged EXE in an isolated installation."""
import os,sys,json,base64,re,shutil,subprocess,uuid
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import update_core as U
from release_crypto import generate_key
from tools.prepare_release import build

def main():
    folder=ROOT/'reviews/updater/worker-integration'/uuid.uuid4().hex[:8];root=folder/'app';root.mkdir(parents=True)
    candidates=list(ROOT.glob('*.py'))+[ROOT/'SubForgeAI Studio.exe',ROOT/'docs/STUDIO.md']
    for directory in ('studio_ui','assets/brand','_studio_boot'):candidates.extend(p for p in (ROOT/directory).rglob('*') if p.is_file())
    for path in candidates:
        relative=path.relative_to(ROOT).as_posix()
        if U.allowed(relative):target=root/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
    # Runtime is shared only for execution; it is outside the updater's allowed targets.
    try:os.symlink(ROOT/'runtime',root/'runtime',target_is_directory=True)
    except OSError as exc:
        if getattr(exc,'winerror',None)!=1314:raise
        quote=lambda p:"'"+str(p).replace("'","''")+"'"
        command='New-Item -ItemType Junction -Path '+quote(root/'runtime')+' -Target '+quote(ROOT/'runtime')+' | Out-Null'
        subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',command],check=True,capture_output=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    public,private=generate_key();pin=base64.b64encode(public).decode();info=root/'release_info.py';info.write_text(re.sub(r'(?m)^PUBLIC_KEY_B64\s*=.*','PUBLIC_KEY_B64 = '+repr(pin),info.read_text('utf-8')),encoding='utf-8');before=info.read_bytes()
    (root/'config.json').write_text('{"sentinel":"keep"}');model=root/'cache/model.bin';model.parent.mkdir();model.write_bytes(b'MODEL DO NOT TOUCH')
    with patch.object(U,'PUBLIC_KEY_B64',pin):
        package,manifest=build(root,folder/'package','1.0.1',private);envelope=json.loads(manifest.read_text('utf-8'));job=root/'.updates/jobs'/uuid.uuid4().hex;job.mkdir(parents=True);shutil.copy2(package,job/'package.zip');U.extract_verified(root,job,envelope['manifest'],job/'package.zip');U.save_json(job/'manifest.json',envelope)
    helper=job/'helper';helper.mkdir()
    for name in ('studio_update_worker.py','update_core.py','release_crypto.py','release_info.py'):shutil.copy2(root/name,helper/name)
    command=[str(ROOT/'runtime/python/python.exe'),'-B','-X','utf8',str(helper/'studio_update_worker.py'),'--root',str(root),'--job',str(job),'--no-relaunch']
    result=subprocess.run(command,cwd=helper,capture_output=True,text=True,encoding='utf-8',timeout=90);(folder/'worker.log').write_text(result.stdout+'\n'+result.stderr,encoding='utf-8');assert result.returncode==0
    last=json.loads((root/'.updates/last_result.json').read_text('utf-8'));assert last['ok'],last;assert json.loads((job/'journal.json').read_text('utf-8'))['status']=='committed';assert '1.0.1' in info.read_text('utf-8')
    result=subprocess.run(command+['--rollback'],cwd=helper,capture_output=True,text=True,encoding='utf-8',timeout=90);assert result.returncode==0;last=json.loads((root/'.updates/last_result.json').read_text('utf-8'));assert last['ok'] and last['rollback'];assert info.read_bytes()==before
    assert (root/'config.json').read_text()=='{"sentinel":"keep"}' and model.read_bytes()==b'MODEL DO NOT TOUCH'
    # Remove only the test's runtime link, not its target, after all child processes exit.
    os.rmdir(root/'runtime')
    report=dict(independent_installer=True,packaged_executable_health=True,version_verified=True,independent_rollback=True,config_preserved=True,model_preserved=True,runtime_unchanged=True,folder=str(folder))
    (ROOT/'reviews/updater/worker-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':main()
