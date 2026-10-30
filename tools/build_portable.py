"""Build a clean, model-free portable distribution and a verified one-click installer."""
from pathlib import Path
import argparse
import base64
import json
import os
import sys
import zipfile
import copy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from release_info import VERSION, REPOSITORY, PUBLIC_KEY_B64
from release_crypto import protect, sign
from update_core import allowed, canonical, file_sha


def files(root):
    root = Path(root)
    candidates = list(root.glob('*.py')) + [root / 'SubForgeAI Studio.exe']
    for folder in ('studio_ui', 'assets/brand', 'assets/screenshots', '_studio_boot', 'runtime', 'lib', 'tools/ffmpeg', 'licenses'):
        candidates.extend(p for p in (root / folder).rglob('*') if p.is_file())
    candidates += [root / 'ollama.exe', root / 'docs/STUDIO.md', root / 'docs/PRIMEIROS-PASSOS.md', root / 'docs/THIRD-PARTY.md', root / 'community/glossary/README.md']
    for path in sorted(set(candidates)):
        relative = path.relative_to(root)
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError('Portable package cannot contain external links: ' + str(relative))
        if '__pycache__' in relative.parts or path.suffix.lower() in ('.pyc', '.pyo', '.lnk', '.lib'):
            continue
        # Never collect caches, configuration, user media, model weights or publisher keys.
        if path.is_file():
            yield path, relative.as_posix()


def write_archive(archive, records, reuse=False):
    """Refresh application files while retaining verified compressed runtime entries.

    ZIP local records contain compressed data and relative sizes, not absolute
    offsets. The standard zipfile writer regenerates the central directory with
    the new offsets. This avoids recompressing unchanged multi-GB libraries.
    """
    if not reuse:
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as z:
            for index, (path, relative) in enumerate(records):
                z.write(path, relative)
                if index % 2000 == 0: print(f'Packed {index}/{len(records)}', flush=True)
        return
    refreshed = archive.with_suffix('.refreshed.zip')
    with zipfile.ZipFile(archive) as old, zipfile.ZipFile(refreshed, 'w', zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as new:
        ordered = sorted(old.infolist(), key=lambda info: info.header_offset)
        ends = {info.filename: ordered[i+1].header_offset if i+1 < len(ordered) else old.start_dir for i, info in enumerate(ordered)}
        previous = {info.filename: info for info in ordered}
        for path, relative in records:
            info = previous.get(relative)
            # Runtime is immutable throughout a build. All application/source
            # and documentation files are reread to include final validated edits.
            reuse_entry = relative.startswith(('runtime/', 'lib/', '_studio_boot/')) and info is not None and path.stat().st_size == info.file_size
            if not reuse_entry:
                new.write(path, relative)
                continue
            cloned = copy.copy(info)
            new.fp.seek(new.start_dir)
            cloned.header_offset = new.fp.tell()
            old.fp.seek(info.header_offset)
            remaining = ends[relative] - info.header_offset
            while remaining:
                chunk = old.fp.read(min(8*1024**2, remaining))
                if not chunk: raise ValueError('Truncated cached archive')
                new.fp.write(chunk); remaining -= len(chunk)
            new.filelist.append(cloned); new.NameToInfo[relative] = cloned
            new.start_dir = new.fp.tell(); new._didModify = True
    with zipfile.ZipFile(refreshed) as check:
        bad = check.testzip()
        if bad: raise ValueError('Refreshed archive failed integrity check: ' + bad)
    refreshed.replace(archive)


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--version', default=VERSION)
    parser.add_argument('--reuse-runtime', action='store_true')
    args = parser.parse_args()
    if args.version != VERSION:
        raise ValueError('Set release_info.VERSION before building the portable package')
    out = ROOT / 'dist/releases' / ('v' + VERSION); out.mkdir(parents=True, exist_ok=True)
    archive = out / ('SubForgeAI-portable-' + VERSION + '.zip')
    records = list(files(ROOT)); raw_size = sum(p.stat().st_size for p, _ in records)
    print(json.dumps(dict(files=len(records), raw_bytes=raw_size)), flush=True)
    write_archive(archive, records, reuse=args.reuse_runtime)
    with zipfile.ZipFile(archive) as z:
        bad = z.testzip()
        if bad: raise ValueError('Archive integrity failed: ' + bad)
    parts = []
    with archive.open('rb') as source:
        index = 1
        while True:
            target = out / f'SubForgeAI-portable-{VERSION}.part{index:02}.bin'
            total = 0
            with target.open('wb') as stream:
                while total < 1024**3:
                    chunk = source.read(min(8*1024**2, 1024**3-total))
                    if not chunk: break
                    stream.write(chunk); total += len(chunk)
            if not total:
                target.unlink(); break
            parts.append(dict(name=target.name, size=total, sha256=file_sha(target)))
            index += 1
    payload = dict(schema='subforge-portable-1', version=VERSION, repository=REPOSITORY,
                   zip_sha256=file_sha(archive), zip_size=archive.stat().st_size,
                   raw_size=raw_size, files=len(records), parts=parts)
    private = protect((Path(os.environ['LOCALAPPDATA'])/'SubForgeAI-release-signing/release-key.dpapi').read_bytes(), True)
    encoded = canonical(payload)
    envelope = dict(payload_b64=base64.b64encode(encoded).decode(), signature=base64.b64encode(sign(private, encoded)).decode())
    manifest = out / f'SubForgeAI-portable-{VERSION}.manifest.json'
    manifest.write_text(json.dumps(envelope, indent=2), encoding='utf-8')
    from tools.build_visual_installer import build as build_installer
    setup = build_installer(ROOT, out, VERSION)
    print(json.dumps(dict(setup=str(setup), parts=parts, manifest=str(manifest), zip_size=payload['zip_size'])), flush=True)


if __name__ == '__main__': main()
