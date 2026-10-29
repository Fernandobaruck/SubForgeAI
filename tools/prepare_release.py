"""Build an app-only signed release. Never includes runtime, models or user data."""
import argparse,base64,json,os,sys,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from update_core import allowed,canonical,file_sha,validate_envelope,version_tuple
from release_crypto import sign,protect
from release_info import REPOSITORY,RUNTIME_ID

def build(root,out,version,private):
    version_tuple(version);root=Path(root).resolve();out=Path(out);out.mkdir(parents=True,exist_ok=True);package=out/('SubForgeAI-update-'+version+'.zip');records=[]
    candidates=list(root.glob('*.py'))+[root/'SubForgeAI Studio.exe',root/'docs/STUDIO.md']
    for folder in ('studio_ui','assets/brand','_studio_boot'):
        candidates.extend(p for p in (root/folder).rglob('*') if p.is_file())
    seen=set()
    with zipfile.ZipFile(package,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for path in sorted(candidates):
            relative=path.relative_to(root).as_posix()
            if not path.is_file() or not allowed(relative) or relative in seen:continue
            if path.is_symlink() or not path.resolve().is_relative_to(root):raise ValueError('Release source contains a link outside the application')
            data=path.read_bytes()
            if relative=='release_info.py':
                import re
                data=re.sub(r'(?m)^VERSION\s*=\s*[\'"][^\'"]+[\'"]','VERSION = '+repr(version),data.decode('utf-8')).encode('utf-8')
            from update_core import sha
            archive.writestr(relative,data);records.append(dict(path=relative,size=len(data),sha256=sha(data)));seen.add(relative)
    payload=dict(schema=1,version=version,repository=REPOSITORY,runtime=RUNTIME_ID,zip_size=package.stat().st_size,zip_sha256=file_sha(package),files=records)
    envelope=dict(manifest=payload,signature=base64.b64encode(sign(private,canonical(payload))).decode());validate_envelope(envelope)
    manifest=out/('SubForgeAI-update-'+version+'.manifest.json');manifest.write_text(json.dumps(envelope,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return package,manifest

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--version',required=True);args=parser.parse_args();key=Path(os.environ['LOCALAPPDATA'])/'SubForgeAI-release-signing/release-key.dpapi'
    if not key.is_file():raise ValueError('Chave de publicação ausente neste perfil do Windows.')
    private=protect(key.read_bytes(),True);out=ROOT/'dist/releases'/('v'+args.version);package,manifest=build(ROOT,out,args.version,private)
    (out/'RELEASE-NOTES.md').write_text(f'''# SubForgeAI Studio v{args.version}

Atualização do aplicativo portátil: interface, scripts, recursos de revisão, fansub, gerenciamento e atualizador assinado.

Este é um pacote de atualização para uma instalação existente. Modelos, runtime Python/Qt, configurações, glossários, legendas e histórico não fazem parte do download.

Inclui revisão lado a lado, glossários por anime, retradução selecionada, histórico e backup; ferramentas de legibilidade, busca e sincronização; exportação ASS com prévia e padrões salvos; organização e estimativas da fila; controle de recursos, inventário de modelos e limpeza assistida.

A aba Atualizações consulta o canal oficial e valida os pacotes antes de instalar. A instalação pede confirmação, reinicia o Studio e conserva uma cópia da versão anterior para recuperação.

Use uma instalação portátil existente do SubForgeAI Studio com seu runtime Python/Qt. Os modelos já instalados continuam nas pastas atuais.
''',encoding='utf-8')
    print(json.dumps(dict(package=str(package),manifest=str(manifest),bytes=package.stat().st_size,version=args.version),ensure_ascii=False))

if __name__=='__main__':main()
