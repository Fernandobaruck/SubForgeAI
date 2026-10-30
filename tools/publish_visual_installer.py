"""Add the graphical bootstrapper to an existing release; preserve old assets."""
import argparse,hashlib,json,re,subprocess,sys,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from release_info import REPOSITORY,VERSION
from update_core import version_tuple

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--version',default=VERSION);parser.add_argument('--source-commit',required=True);args=parser.parse_args();version_tuple(args.version)
    if not re.fullmatch('[a-f0-9]{40}',args.source_commit):raise ValueError('Invalid source commit')
    path=ROOT/'dist/releases'/('v'+args.version)/('SubForgeAI-Instalar-visual-'+args.version+'.exe')
    data=path.read_bytes()
    if data[:2]!=b'MZ' or len(data)>2*1024**2:raise ValueError('Unexpected graphical bootstrapper')
    digest='sha256:'+hashlib.sha256(data).hexdigest()
    login=subprocess.run(['git','-c','credential.interactive=never','credential','fill'],input='protocol=https\nhost=github.com\nusername='+REPOSITORY.split('/')[0]+'\n\n',capture_output=True,text=True,timeout=30)
    credentials=dict(line.split('=',1) for line in login.stdout.splitlines() if '=' in line)
    if login.returncode or not credentials.get('password'):raise RuntimeError('GitHub authentication unavailable')
    def request(url,method='GET',body=None,content_type='application/json'):
        headers={'Authorization':'Bearer '+credentials['password'],'User-Agent':'SubForgeAI-installer-publisher','Accept':'application/vnd.github+json','Content-Type':content_type,'X-GitHub-Api-Version':'2022-11-28'}
        with urllib.request.urlopen(urllib.request.Request(url,data=body,method=method,headers=headers),timeout=90) as response:return json.load(response)
    api='https://api.github.com/repos/'+REPOSITORY
    release=request(api+'/releases/tags/v'+args.version)
    if release['draft'] or release['prerelease']:raise RuntimeError('Expected an existing stable release')
    before={x['name']:(x['id'],x.get('digest'),x['size']) for x in release['assets']}
    asset=next((x for x in release['assets'] if x['name']==path.name),None)
    if asset is None:asset=request('https://uploads.github.com/repos/'+REPOSITORY+'/releases/'+str(release['id'])+'/assets?name='+path.name,'POST',data,'application/vnd.microsoft.portable-executable')
    if asset.get('digest')!=digest:raise RuntimeError('Existing installer has different content; nothing was replaced')
    marker='## Instalador gráfico para a mesma versão'
    notes=release.get('body') or ''
    addition='\n\n'+marker+'\n\n[Baixar instalador gráfico]('+asset['browser_download_url']+'). Abra o executável, escolha a pasta e clique em Instalar. Não precisa extrair ZIP nem abrir CMD. Inclui tema escuro e lilás, português/inglês/espanhol, progresso e velocidade, pausa e retomada, opção de uma conexão e verificação de assinatura e integridade. Os modelos são escolhidos depois, dentro do Studio.\n\nEste instalador prepara o mesmo SubForgeAI Studio '+args.version+' já publicado, usando os mesmos arquivos BIN e o mesmo manifesto assinado. Nenhum pacote do aplicativo foi substituído e nenhuma versão nova foi lançada. Os instaladores anteriores continuam disponíveis.\n\n[Código do instalador gráfico](https://github.com/'+REPOSITORY+'/tree/'+args.source_commit+'/tools/installer).\n'
    if marker not in notes:request(api+'/releases/'+str(release['id']),'PATCH',json.dumps({'body':notes+addition},ensure_ascii=False).encode('utf-8'))
    after=request(api+'/releases/'+str(release['id']))
    current={x['name']:(x['id'],x.get('digest'),x['size']) for x in after['assets']}
    assert all(current.get(name)==value for name,value in before.items())
    assert set(current)==set(before)|{path.name}
    with urllib.request.urlopen(urllib.request.Request(asset['browser_download_url'],headers={'User-Agent':'SubForgeAI-public-check'}),timeout=60) as response:download=response.read(2*1024**2)
    assert hashlib.sha256(download).hexdigest()==digest.removeprefix('sha256:')
    report=dict(version=args.version,url=asset['browser_download_url'],sha256=digest.removeprefix('sha256:'),bytes=len(data),old_assets_preserved=True,old_assets=len(before),assets=len(current),source_commit=args.source_commit,public_download_verified=True,new_application_version_created=False)
    (ROOT/'reviews/visual-installer/publication.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':main()
