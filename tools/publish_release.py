"""Publish an already signed update using the owner's Git Credential Manager login.

Credentials remain in memory and are never logged or written to the project.
"""
import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from release_info import REPOSITORY
from update_core import file_sha, validate_envelope, version_tuple


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--version', required=True)
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
    owner = REPOSITORY.split('/')[0]
    result = subprocess.run(
        ['git', '-c', 'credential.interactive=never', 'credential', 'fill'],
        input=f'protocol=https\nhost=github.com\nusername={owner}\n\n',
        text=True, capture_output=True, check=False, timeout=30)
    credentials = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
    if result.returncode or not credentials.get('password'):
        raise RuntimeError('No usable GitHub login in Git Credential Manager')
    token = credentials['password']

    def request(url, method='GET', data=None, content_type='application/json'):
        req = urllib.request.Request(url, data=data, method=method, headers={
            'Authorization': 'Bearer ' + token,
            'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28',
            'User-Agent': 'SubForgeAI-release-publisher',
            'Content-Type': content_type,
        })
        with urllib.request.urlopen(req, timeout=180) as response:
            return json.load(response)

    api = 'https://api.github.com/repos/' + REPOSITORY
    tag = 'v' + args.version
    try:
        release = request(api + '/releases/tags/' + tag)
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
    for path in (package, manifest):
        if path.name in assets:
            raise RuntimeError('Draft already has an asset with this name; inspect it before retrying')
        content_type = 'application/zip' if path.suffix == '.zip' else 'application/json'
        request(f'https://uploads.github.com/repos/{REPOSITORY}/releases/{release["id"]}/assets?name={path.name}',
                'POST', path.read_bytes(), content_type)
    release = request(api + '/releases/' + str(release['id']), 'PATCH', b'{"draft":false}')
    print('Published: ' + release['html_url'])


if __name__ == '__main__':
    try:
        main()
    except urllib.error.HTTPError as error:
        print(f'GitHub request failed: HTTP {error.code}', file=sys.stderr)
        sys.exit(1)
