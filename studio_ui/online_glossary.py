"""Public, bounded glossary exchange; local confirmed terms always take priority."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.parse import urlsplit
from pipeline_io import atomic_write_text
from release_info import REPOSITORY

MAX_BYTES = 2 * 1024 * 1024
BASE = 'https://raw.githubusercontent.com/' + REPOSITORY + '/main/community/glossary/'


def slug(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,79}', value):
        raise ValueError('Identificador do glossário inválido.')
    return value


def text(value, limit=500):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or any(ord(c) < 32 for c in value):
        raise ValueError('Texto do glossário inválido.')
    return value.strip()


def terms(value):
    if not isinstance(value, list) or not 1 <= len(value) <= 1000:
        raise ValueError('O glossário deve conter entre 1 e 1000 termos.')
    result = []; seen = set()
    for row in value:
        if not isinstance(row, dict): raise ValueError('Termo inválido.')
        source, target = text(row.get('source')), text(row.get('target'))
        if source.casefold() in seen: raise ValueError('Termo original duplicado.')
        seen.add(source.casefold()); result.append(dict(source=source, target=target))
    return result


def catalog(value):
    if not isinstance(value, dict) or value.get('schema') != 1 or not isinstance(value.get('collections'), list) or len(value['collections']) > 500:
        raise ValueError('Catálogo online inválido.')
    result = []; seen = set()
    for item in value['collections']:
        if not isinstance(item, dict): raise ValueError('Entrada do catálogo inválida.')
        identifier = slug(item.get('id'))
        if identifier in seen: raise ValueError('Glossário duplicado no catálogo.')
        seen.add(identifier)
        if not re.fullmatch('[a-f0-9]{64}', str(item.get('sha256', ''))): raise ValueError('Hash do glossário inválido.')
        if item.get('source_language') not in ('en', 'ja') or item.get('target_language') != 'pt-BR': raise ValueError('Idioma do glossário inválido.')
        result.append(dict(id=identifier, title=text(item.get('title'), 160), description=text(item.get('description'), 600),
                           revision=text(item.get('revision'), 80), sha256=item['sha256'], source_language=item['source_language'], target_language='pt-BR'))
    return result


def collection(raw, entry):
    if len(raw) > MAX_BYTES or hashlib.sha256(raw).hexdigest() != entry['sha256']:
        raise ValueError('O glossário mudou ou está incompleto. Atualize o catálogo e tente novamente.')
    value = json.loads(raw.decode('utf-8-sig'))
    if not isinstance(value, dict) or value.get('schema') != 1 or value.get('id') != entry['id'] or value.get('revision') != entry['revision'] or value.get('source_language') != entry['source_language'] or value.get('target_language') != 'pt-BR':
        raise ValueError('O arquivo não corresponde ao catálogo.')
    return terms(value.get('terms'))


class Redirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.startswith(BASE) or urlsplit(newurl).netloc != 'raw.githubusercontent.com':
            raise ValueError('Redirecionamento não permitido no catálogo.')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(name, cancel=None):
    if name != 'index.json': slug(name.removesuffix('.json'))
    request = Request(BASE + name, headers={'User-Agent': 'SubForgeAI-glossary', 'Accept': 'application/json'})
    with build_opener(Redirect()).open(request, timeout=20) as response:
        chunks = []; size = 0
        while True:
            if cancel is not None and cancel.is_set(): raise ValueError('Consulta interrompida.')
            block = response.read(64 * 1024)
            if not block: break
            size += len(block)
            if size > MAX_BYTES: raise ValueError('Arquivo online maior que o limite permitido.')
            chunks.append(block)
        return b''.join(chunks)


class Store:
    def __init__(self, root): self.base = Path(root) / 'cache/community_glossary'

    def _read(self, path):
        if path.stat().st_size > MAX_BYTES: raise ValueError('Cache online inválido.')
        return path.read_bytes()

    def cached_catalog(self):
        try:
            envelope = json.loads(self._read(self.base/'index.json'))
            return catalog(envelope['catalog']), envelope['fetched_at']
        except (OSError, ValueError, KeyError, TypeError): return [], ''

    def refresh(self, cancel):
        try:
            value = json.loads(fetch('index.json', cancel)); rows = catalog(value)
            stamp = datetime.now(timezone.utc).isoformat(timespec='seconds')
            atomic_write_text(self.base/'index.json', json.dumps(dict(catalog=value, fetched_at=stamp), ensure_ascii=False))
            return rows, stamp, False
        except (OSError, ValueError, KeyError, TypeError):
            if cancel.is_set(): raise ValueError('Consulta interrompida.')
            rows, stamp = self.cached_catalog()
            if stamp: return rows, stamp, True
            raise ValueError('Não foi possível consultar o catálogo. Confira a conexão e tente novamente.')

    def load(self, entry, cancel):
        path = self.base / (slug(entry['id']) + '-' + entry['sha256'] + '.json')
        try:
            raw = fetch(entry['id'] + '.json', cancel); rows = collection(raw, entry)
            atomic_write_text(path, raw.decode('utf-8-sig'))
            return rows, False
        except (OSError, ValueError, KeyError, TypeError):
            if cancel.is_set(): raise ValueError('Consulta interrompida.')
            try: return collection(self._read(path), entry), True
            except (OSError, ValueError, KeyError, TypeError):
                raise ValueError('Não foi possível baixar este glossário. Atualize o catálogo e tente novamente.')


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def preview(local, incoming):
    existing = {row['source'].casefold(): row for row in local}
    result = []
    for row in incoming:
        old = existing.get(row['source'].casefold())
        status = 'new' if old is None else 'same' if old['target'] == row['target'] else 'conflict'
        result.append(dict(row, status=status, localTarget=old['target'] if old else '', eligible=status == 'new'))
    return result


def apply(registry, project, incoming, selected, expected, origin):
    local = registry.terms(project)
    if fingerprint(local) != expected: raise ValueError('O glossário local mudou. Reabra a prévia antes de importar.')
    rows = preview(local, terms(incoming)); chosen = set(selected)
    additions = [dict(source=row['source'], target=row['target'], confirmed=False, origin=origin)
                 for i, row in enumerate(rows) if i in chosen and row['eligible']]
    if not additions: raise ValueError('Selecione termos novos para importar.')
    registry._save_terms(project, local + additions)
    return len(additions)
