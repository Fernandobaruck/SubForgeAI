"""Publish an already signed update using the owner's Git Credential Manager login.

Credentials remain in memory and are never logged or written to the project.
"""
import argparse
import json
import base64
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from release_info import REPOSITORY, PUBLIC_KEY_B64
from release_crypto import verify
from update_core import file_sha, validate_envelope, version_tuple


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--version', required=True)
    parser.add_argument('--portable', action='store_true')
    parser.add_argument('--draft-only', action='store_true')
    args = parser.parse_args()
    version_tuple(args.version)
    folder = ROOT / 'dist/releases' / ('v' + args.version)
    stem = 'SubForgeAI-update-' + args.version
    package = folder / (stem + '.zip')
    manifest = folder / (stem + '.manifest.json')
    envelope = json.loads(manifest.read_text(encoding='utf-8'))
    validate_envelope(envelope)
    payload = envelope['manifest']
    if payload['repository'] != REPOSITORY or payload['version'] != args.version:
        raise ValueError('Release identity differs from this source checkout')
    if package.stat().st_size != payload['zip_size'] or file_sha(package) != payload['zip_sha256']:
        raise ValueError('Update package does not match its signed manifest')
    paths = [package, manifest]
    if args.portable:
        portable_manifest = folder / f'SubForgeAI-portable-{args.version}.manifest.json'
        portable_envelope = json.loads(portable_manifest.read_text(encoding='utf-8'))
        encoded = base64.b64decode(portable_envelope['payload_b64'], validate=True)
        if not verify(base64.b64decode(PUBLIC_KEY_B64), encoded, base64.b64decode(portable_envelope['signature'], validate=True)):
            raise ValueError('Portable signature is invalid')
        portable = json.loads(encoded)
        if portable['repository'] != REPOSITORY or portable['version'] != args.version:
            raise ValueError('Portable identity mismatch')
        graphical=folder / f'SubForgeAI-Instalar-visual-{args.version}.exe'
        if not graphical.is_file() or graphical.read_bytes()[:2]!=b'MZ':
            raise ValueError('Graphical installer is missing or invalid')
        paths.extend([graphical,portable_manifest])
        for part in portable['parts']:
            path = folder / part['name']
            if path.parent != folder or path.stat().st_size != part['size'] or file_sha(path) != part['sha256']:
                raise ValueError('Portable part mismatch')
            paths.append(path)
    owner = REPOSITORY.split('/')[0]
    result = subprocess.run(
        ['git', '-c', 'credential.interactive=never', 'credential', 'fill'],
        input=f'protocol=https\nhost=github.com\nusername={owner}\n\n',
        text=True, capture_output=True, check=False, timeout=30)
    credentials = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
    if result.returncode or not credentials.get('password'):
        raise RuntimeError('No usable GitHub login in Git Credential Manager')
    token = credentials['password']

    def request(url, method='GET', data=None, content_type='application/json', size=None):
        headers = {
            'Authorization': 'Bearer ' + token,
            'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28',
            'User-Agent': 'SubForgeAI-release-publisher',
            'Content-Type': content_type,
        }
        if size is not None: headers['Content-Length'] = str(size)
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        with urllib.request.urlopen(req, timeout=180) as response:
            return json.load(response)

    api = 'https://api.github.com/repos/' + REPOSITORY
    tag = 'v' + args.version
    try:
        releases = request(api + '/releases?per_page=100')
        release = next((item for item in releases if item['tag_name'] == tag), None)
        if release is None:
            raise urllib.error.HTTPError(api, 404, 'Release not found', None, None)
        if not release['draft']:
            print('Release already published: ' + release['html_url'])
            return
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
        body = (folder / 'RELEASE-NOTES.md').read_text(encoding='utf-8')
        release = request(api + '/releases', 'POST', json.dumps({
            'tag_name': tag, 'target_commitish': 'main',
            'name': 'SubForgeAI Studio ' + tag, 'body': body,
            'draft': True, 'prerelease': False,
        }).encode())
    assets = {asset['name']: asset for asset in release.get('assets', [])}
    class Upload:
        def __init__(self, stream, path):
            self.stream, self.path = stream, path
            self.done = 0; self.last = time.monotonic()
        def __iter__(self): return self
        def __next__(self):
            data = self.stream.read(1024 * 1024)
            if not data: raise StopIteration
            self.done += len(data)
            if time.monotonic() - self.last > 15:
                print(f'Uploading {self.path.name}: {self.done*100/self.path.stat().st_size:.1f}%', flush=True)
                self.last = time.monotonic()
            return data
    for path in paths:
        if path.name in assets:
            asset = assets[path.name]
            if asset.get('digest') != 'sha256:' + file_sha(path) or asset['size'] != path.stat().st_size:
                raise RuntimeError('Draft asset differs from local package; inspect before retrying')
            print('Verified existing asset: ' + path.name, flush=True)
            continue
        content_type = {'.zip':'application/zip', '.json':'application/json'}.get(path.suffix, 'application/octet-stream')
        print('Uploading: ' + path.name, flush=True)
        with path.open('rb') as stream:
            asset = request(f'https://uploads.github.com/repos/{REPOSITORY}/releases/{release["id"]}/assets?name={path.name}',
                    'POST', Upload(stream, path), content_type, path.stat().st_size)
        if asset.get('digest') != 'sha256:' + file_sha(path):
            raise RuntimeError('Remote asset hash differs from local package')
    if args.draft_only:
        print('Draft ready: ' + release['html_url'], flush=True)
        return
    release = request(api + '/releases/' + str(release['id']), 'PATCH', b'{"draft":false}')
    print('Published: ' + release['html_url'])


if __name__ == '__main__':
    try:
        main()
    except urllib.error.HTTPError as error:
        print(f'GitHub request failed: HTTP {error.code}', file=sys.stderr)
        sys.exit(1)
