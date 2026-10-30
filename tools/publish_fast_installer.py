"""Add a small compatible bootstrap asset; never replace existing release parts."""
import argparse,hashlib,json,subprocess,sys,urllib.request,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from release_info import REPOSITORY
from update_core import version_tuple


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--version',required=True);parser.add_argument('--source-commit',required=True);args=parser.parse_args();version_tuple(args.version)
    path=ROOT/'dist/releases'/('v'+args.version)/('SubForgeAI-Instalar-rapido-'+args.version+'.zip')
    with zipfile.ZipFile(path) as archive:
        assert {'Instalar.cmd','Instalar.ps1','DownloadEngine.cs','Instalar-1-conexao.cmd','LEIA-ME.txt'}==set(archive.namelist())
        assert '__VERSION__' not in archive.read('Instalar.ps1').decode('utf-8-sig')
    result=subprocess.run(['git','-c','credential.interactive=never','credential','fill'],input='protocol=https\nhost=github.com\nusername='+REPOSITORY.split('/')[0]+'\n\n',text=True,capture_output=True,timeout=30)
    credentials=dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line)
    if result.returncode or not credentials.get('password'):raise RuntimeError('GitHub authentication unavailable')
    def request(url,method='GET',body=None,content_type='application/json'):
        headers={'Authorization':'Bearer '+credentials['password'],'User-Agent':'SubForgeAI-publisher','Accept':'application/vnd.github+json','Content-Type':content_type}
        with urllib.request.urlopen(urllib.request.Request(url,data=body,method=method,headers=headers),timeout=90) as response:return json.load(response)
    api='https://api.github.com/repos/'+REPOSITORY
    release=request(api+'/releases/tags/v'+args.version)
    if release['draft']:raise RuntimeError('Expected an existing public release')
    before={a['name']:(a['id'],a.get('digest')) for a in release['assets']}
    digest='sha256:'+hashlib.sha256(path.read_bytes()).hexdigest()
    asset=next((a for a in release['assets'] if a['name']==path.name),None)
    if asset is None:
        asset=request('https://uploads.github.com/repos/'+REPOSITORY+'/releases/'+str(release['id'])+'/assets?name='+path.name,'POST',path.read_bytes(),'application/zip')
    if asset.get('digest')!=digest:raise RuntimeError('Existing remote installer differs; no assets were replaced')
    marker='## Instalador rápido para a mesma versão'
    body=release.get('body') or ''
    addition='\n\n'+marker+'\n\n[Baixar instalador rápido]('+asset['browser_download_url']+'). Feche o CMD antigo, extraia todo o ZIP e abra Instalar.cmd. O download usa motor nativo, até quatro partes simultâneas, retomada e repetição de falhas. O cache da mesma versão e do mesmo usuário é aproveitado automaticamente; não apague arquivos já baixados nem execute dois instaladores ao mesmo tempo. Instalar-1-conexao.cmd é a alternativa para redes que não funcionam bem com paralelismo. Velocidade depende da rota e da conexão.\n\n[Código do instalador rápido](https://github.com/'+REPOSITORY+'/tree/'+args.source_commit+'/tools/installer). Os arquivos .bin, assinaturas e o aplicativo 1.0.4 permanecem os mesmos.\n'
    if marker not in body:request(api+'/releases/'+str(release['id']),'PATCH',json.dumps({'body':body+addition}).encode())
    after=request(api+'/releases/'+str(release['id']))
    mapped={a['name']:(a['id'],a.get('digest')) for a in after['assets']}
    assert all(mapped.get(name)==value for name,value in before.items())
    print(json.dumps(dict(url=asset['browser_download_url'],sha256=digest,old_assets_preserved=True,assets=len(mapped))))


if __name__=='__main__':main()
