"""Exercise the real Windows PowerShell installer with a tiny signed fixture."""
from pathlib import Path
import base64
import json
import subprocess
import sys
import tempfile
import zipfile
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from release_crypto import generate_key, sign
from update_core import canonical, file_sha


def main():
    public, private = generate_key()
    with tempfile.TemporaryDirectory(prefix='installer-', dir=ROOT/'reviews/updater') as folder:
        base = Path(folder); source = base/'source'; source.mkdir()
        parent = base/'destination'; parent.mkdir()
        version = '0.0.0'
        archive = source/f'SubForgeAI-portable-{version}.part01.bin'
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('SubForgeAI Studio.exe', 'test only - never execute')
            z.writestr('studio_ui/qml/qmldir', 'module Studio\n')
        payload = dict(schema='subforge-portable-1', version=version, repository='Fernandobaruck/SubForgeAI',
                       raw_size=128, zip_size=archive.stat().st_size, zip_sha256=file_sha(archive),
                       parts=[dict(name=archive.name, size=archive.stat().st_size, sha256=file_sha(archive))])
        def envelope(data):
            encoded = canonical(data)
            return dict(payload_b64=base64.b64encode(encoded).decode(), signature=base64.b64encode(sign(private, encoded)).decode())
        manifest = source/f'SubForgeAI-portable-{version}.manifest.json'
        original = envelope(payload); manifest.write_text(json.dumps(original))
        script = (ROOT/'tools/installer/Instalar.ps1').read_text(encoding='utf-8').replace('__VERSION__', version).replace('__REPOSITORY__', 'Fernandobaruck/SubForgeAI').replace('__PUBLIC_KEY__', base64.b64encode(public).decode())
        target = base/'Instalar.ps1'; target.write_bytes(b'\xef\xbb\xbf'+script.encode())
        def run(where):
            return subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(target),
                '-DestinationParent',str(where),'-SourceDirectory',str(source),'-NoLaunch'],capture_output=True,timeout=90)
        result = run(parent)
        assert result.returncode == 0, result.stdout.decode(errors='replace')+result.stderr.decode(errors='replace')
        installed = parent/f'SubForgeAI-{version}'
        assert (installed/'studio_ui/qml/qmldir').read_text() == 'module Studio\n'
        sentinel = installed/'keep.txt'; sentinel.write_text('preserve')
        result = run(parent); assert result.returncode != 0 and sentinel.read_text() == 'preserve'
        other = base/'bad-signature'; other.mkdir()
        tampered = dict(original, signature=base64.b64encode(b'wrong').decode()); manifest.write_text(json.dumps(tampered))
        result = run(other); assert result.returncode != 0 and not list(other.iterdir())
        manifest.write_text(json.dumps(original)); archive.write_bytes(archive.read_bytes()+b'changed')
        result = run(other); assert result.returncode != 0 and not list(other.iterdir())
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('../outside.txt', 'escape')
            z.writestr('SubForgeAI Studio.exe', 'test')
        payload.update(zip_size=archive.stat().st_size, zip_sha256=file_sha(archive))
        payload['parts'][0].update(size=archive.stat().st_size, sha256=file_sha(archive))
        manifest.write_text(json.dumps(envelope(payload)))
        result = run(other)
        assert result.returncode != 0 and not list(other.iterdir())
        assert not (base/'outside.txt').exists()
        print(json.dumps(dict(real_powershell_install=True, existing_data_preserved=True,
                             invalid_signature_rejected=True, corrupt_part_rejected=True, traversal_rejected=True)))


if __name__ == '__main__': main()
