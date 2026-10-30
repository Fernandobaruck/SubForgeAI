"""Build one small .NET/WPF executable using existing signed portable assets."""
import argparse,base64,json,os,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from release_info import VERSION,REPOSITORY,PUBLIC_KEY_B64
from update_core import version_tuple

def build(root,out,version,public_key=None,download_bytes=None,installed_bytes=None):
    root,out=Path(root),Path(out);version_tuple(version);out.mkdir(parents=True,exist_ok=True)
    key=public_key or PUBLIC_KEY_B64
    if download_bytes is None or installed_bytes is None:
        envelope=json.loads((root/'dist/releases'/('v'+version)/('SubForgeAI-portable-'+version+'.manifest.json')).read_text(encoding='utf-8'))
        payload=json.loads(base64.b64decode(envelope['payload_b64']))
        download_bytes,installed_bytes=payload['zip_size'],payload['raw_size']
    framework=Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319'
    compiler=framework/'csc.exe'
    if not compiler.is_file():raise RuntimeError('Compilador .NET Framework ausente.')
    exe=out/('SubForgeAI-Instalar-visual-'+version+'.exe')
    with tempfile.TemporaryDirectory(prefix='visual-build-',dir=out) as temporary:
        stage=Path(temporary)
        worker=(root/'tools/installer/Instalar.ps1').read_text(encoding='utf-8').replace('__VERSION__',version).replace('__REPOSITORY__',REPOSITORY).replace('__PUBLIC_KEY__',key)
        (stage/'Instalar.ps1').write_bytes(b'\xef\xbb\xbf'+worker.encode('utf-8'))
        source=(root/'tools/installer/InstallerGui.cs').read_text(encoding='utf-8').replace('__VERSION__',version).replace('__DOWNLOAD_BYTES__',str(int(download_bytes))+'L').replace('__INSTALLED_BYTES__',str(int(installed_bytes))+'L')
        (stage/'InstallerGui.cs').write_text(source,encoding='utf-8-sig')
        (stage/'app.manifest').write_text('''<?xml version="1.0" encoding="utf-8"?><assembly manifestVersion="1.0" xmlns="urn:schemas-microsoft-com:asm.v1"><assemblyIdentity version="1.0.0.0" name="SubForgeAI.Installer"/><trustInfo xmlns="urn:schemas-microsoft-com:asm.v3"><security><requestedPrivileges><requestedExecutionLevel level="asInvoker" uiAccess="false"/></requestedPrivileges></security></trustInfo><compatibility xmlns="urn:schemas-microsoft-com:compatibility.v1"><application><supportedOS Id="{8e0f7a12-bfb3-4fe8-b9a5-48fd50a15a9a}"/></application></compatibility><application xmlns="urn:schemas-microsoft-com:asm.v3"><windowsSettings><dpiAware xmlns="http://schemas.microsoft.com/SMI/2005/WindowsSettings">true</dpiAware></windowsSettings></application></assembly>''',encoding='utf-8')
        references=['System.dll','System.Core.dll','System.Drawing.dll','System.Windows.Forms.dll','System.Web.Extensions.dll','System.Xaml.dll','WPF/WindowsBase.dll','WPF/PresentationCore.dll','WPF/PresentationFramework.dll']
        command=[str(compiler),'/nologo','/target:winexe','/platform:anycpu','/optimize+','/codepage:65001','/out:'+str(exe),'/win32icon:'+str(root/'assets/brand/subforge-studio.ico'),'/win32manifest:'+str(stage/'app.manifest')]
        command+=['/reference:'+str(framework/name) for name in references]
        command+=['/resource:'+str(root/'tools/installer/InstallerWindow.xaml')+',InstallerWindow.xaml','/resource:'+str(stage/'Instalar.ps1')+',Instalar.ps1','/resource:'+str(root/'tools/installer/DownloadEngine.cs')+',DownloadEngine.cs',str(stage/'InstallerGui.cs')]
        result=subprocess.run(command,capture_output=True,text=True,encoding='oem',errors='replace',timeout=60,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode:raise RuntimeError(result.stdout+result.stderr)
    return exe

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--version',default=VERSION);args=parser.parse_args()
    path=build(ROOT,ROOT/'dist/releases'/('v'+args.version),args.version)
    print(json.dumps(dict(executable=str(path),bytes=path.stat().st_size),ensure_ascii=False))

if __name__=='__main__':main()
