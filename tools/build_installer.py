"""Build a small installer independently, reusing published signed portable parts."""
import argparse
import sys
import zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from release_info import VERSION, REPOSITORY, PUBLIC_KEY_B64
from update_core import version_tuple


def build(root, out, version, fast=False):
    version_tuple(version);root=Path(root);out=Path(out);out.mkdir(parents=True,exist_ok=True)
    script=(root/'tools/installer/Instalar.ps1').read_text(encoding='utf-8')
    script=script.replace('__VERSION__',version).replace('__REPOSITORY__',REPOSITORY).replace('__PUBLIC_KEY__',PUBLIC_KEY_B64)
    name='SubForgeAI-Instalar-'+('rapido-' if fast else '')+version+'.zip'
    target=out/name
    command='@echo off\r\ncd /d "%~dp0"\r\npowershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Instalar.ps1"{options}\r\nif errorlevel 1 pause\r\n'
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('Instalar.ps1',b'\xef\xbb\xbf'+script.encode('utf-8'))
        archive.write(root/'tools/installer/DownloadEngine.cs','DownloadEngine.cs')
        archive.writestr('Instalar.cmd',command.format(options=''))
        archive.writestr('Instalar-1-conexao.cmd',command.format(options=' -Connections 1'))
        archive.writestr('LEIA-ME.txt',('Extraia todos os arquivos deste ZIP e abra Instalar.cmd. Feche o CMD do instalador anterior antes de abrir este.\r\n'
            'O download usa motor nativo com ate quatro partes simultaneas, retomada e verificacao de integridade. Nao exige instalar outro programa.\r\n'
            'Para a mesma versao, os arquivos ja baixados pelo instalador anterior sao aproveitados automaticamente no mesmo usuario do Windows. Nao apague o cache.\r\n'
            'Se houver problema com conexoes paralelas, feche o instalador e use Instalar-1-conexao.cmd.\r\n'
            'Nao execute dois instaladores ao mesmo tempo. Escolha uma pasta; os modelos sao baixados depois pelo Studio. Nao precisa executar como administrador.\r\n').encode('utf-8'))
    return target


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--version',default=VERSION);parser.add_argument('--fast',action='store_true');args=parser.parse_args()
    print(build(ROOT,ROOT/'dist/releases'/('v'+args.version),args.version,args.fast))
