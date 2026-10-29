"""User-confirmed anime projects shared across media folders and seasons."""
from __future__ import annotations
import hashlib,json,re,uuid
from pathlib import Path
from pipeline_io import atomic_write_text


def read_json(path,default=None):
    path=Path(path)
    if not path.is_file():return {} if default is None else default
    return json.loads(path.read_text(encoding='utf-8-sig'))


def folder_key(path):
    return hashlib.sha256(str(Path(path).resolve()).casefold().encode()).hexdigest()[:20]


class SeriesRegistry:
    def __init__(self,root):self.root=Path(root);self.base=self.root/'series_projects'
    def index(self):
        value=read_json(self.base/'index.json',{'projects':[],'folders':{}})
        if not isinstance(value,dict) or not isinstance(value.get('projects'),list) or not isinstance(value.get('folders'),dict):raise ValueError('Cadastro de animes inválido.')
        seen=set()
        for project in value['projects']:
            if not isinstance(project,dict) or not re.fullmatch(r'[a-f0-9]{32}',str(project.get('id',''))) or not isinstance(project.get('name'),str) or not project['name'].strip() or project['id'] in seen:raise ValueError('Cadastro de animes inválido.')
            seen.add(project['id'])
        return value
    def projects(self):return self.index()['projects']
    def _id(self,identifier):
        if not re.fullmatch(r'[a-f0-9]{32}',str(identifier)):raise ValueError('Anime inválido.')
        if not any(p['id']==identifier for p in self.projects()):raise ValueError('Anime não encontrado.')
        return identifier
    def create(self,name):
        name=str(name).strip()
        if not name or len(name)>120:raise ValueError('Informe um nome de anime com até 120 caracteres.')
        index=self.index()
        if any(p['name'].casefold()==name.casefold() for p in index['projects']):raise ValueError('Este anime já está cadastrado.')
        identifier=uuid.uuid4().hex;index['projects'].append({'id':identifier,'name':name})
        atomic_write_text(self.base/'index.json',json.dumps(index,ensure_ascii=False,indent=2));return identifier
    def style(self,identifier):
        from season_tools import validate_style
        self._id(identifier)
        return validate_style(read_json(self.base/identifier/'style.json',{}))
    def set_style(self,identifier,value):
        from season_tools import validate_style
        self._id(identifier);value=validate_style(value);path=self.base/identifier/'style.json'
        if path.is_file():atomic_write_text(self.base/identifier/'history'/('style-'+uuid.uuid4().hex+'.json'),path.read_text(encoding='utf-8'))
        atomic_write_text(path,json.dumps(value,ensure_ascii=False,indent=2))

    def terms(self,identifier):
        self._id(identifier);value=read_json(self.base/identifier/'terms.json',[])
        if not isinstance(value,list):raise ValueError('Glossário do anime inválido.')
        seen=set()
        for term in value:
            if not isinstance(term,dict) or not isinstance(term.get('source'),str) or not isinstance(term.get('target'),str) or type(term.get('confirmed')) is not bool or not term['source'].strip() or not term['target'].strip() or term['source'].casefold() in seen:raise ValueError('Glossário do anime inválido.')
            seen.add(term['source'].casefold())
        return value
    def set_term(self,identifier,source,target,confirmed):
        self._id(identifier);source=str(source).strip();target=str(target).strip()
        if not source or not target or len(source)>500 or len(target)>500:raise ValueError('Informe o termo original e a tradução.')
        terms=[term for term in self.terms(identifier) if term['source'].casefold()!=source.casefold()]
        terms.append({'source':source,'target':target,'confirmed':bool(confirmed)})
        self._save_terms(identifier,terms)
    def remove_term(self,identifier,source):
        self._save_terms(identifier,[term for term in self.terms(identifier) if term['source'].casefold()!=source.casefold()])
    def _save_terms(self,identifier,terms):
        self._id(identifier);path=self.base/identifier/'terms.json'
        if path.is_file():
            digest=hashlib.sha256(path.read_bytes()).hexdigest()[:16]
            atomic_write_text(self.base/identifier/'history'/(digest+'.json'),path.read_text(encoding='utf-8'))
        atomic_write_text(path,json.dumps(terms,ensure_ascii=False,indent=2))
    def confirmed(self,identifier):return {t['source']:t['target'] for t in self.terms(identifier) if t.get('confirmed')}
    def memory(self,identifier):
        self._id(identifier);value=read_json(self.base/identifier/'memory.json',{})
        if not isinstance(value,dict) or any(not isinstance(k,str) or not isinstance(v,str) for k,v in value.items()):raise ValueError('Memória do anime inválida.')
        return value
    def remember(self,identifier,source,target):
        if not str(source).strip() or not str(target).strip():raise ValueError('A memória exige origem e tradução.')
        memory=self.memory(identifier);memory[str(source)]=str(target)
        path=self.base/identifier/'memory.json'
        if path.is_file():atomic_write_text(self.base/identifier/'history'/('memory-'+uuid.uuid4().hex+'.json'),path.read_text(encoding='utf-8'))
        atomic_write_text(path,json.dumps(memory,ensure_ascii=False,indent=2))
    def bind_folder(self,identifier,folder):
        self._id(identifier);folder=Path(folder).resolve()
        if not folder.is_dir():raise ValueError('Pasta de temporada indisponível.')
        index=self.index();index['folders'][folder_key(folder)]={'project':identifier,'path':str(folder)}
        atomic_write_text(self.base/'index.json',json.dumps(index,ensure_ascii=False,indent=2))
    def folders(self,identifier):
        self._id(identifier)
        return [{'key':key,'path':value.get('path',key)} for key,value in self.index()['folders'].items() if isinstance(value,dict) and value.get('project')==identifier]
    def unbind_folder(self,identifier,key):
        self._id(identifier);index=self.index();value=index['folders'].get(key,{})
        if isinstance(value,dict) and value.get('project')==identifier:
            del index['folders'][key];atomic_write_text(self.base/'index.json',json.dumps(index,ensure_ascii=False,indent=2))
    def resolve(self,path):
        path=Path(path).resolve();identifier=self.index()['folders'].get(folder_key(path if path.is_dir() else path.parent),'')
        identifier=identifier.get('project','') if isinstance(identifier,dict) else identifier
        return self._id(identifier) if identifier else ''


def apply_project(source,origin,root,identifier):
    """Attach context only to an owned generated copy, never the source file."""
    from speech_context import read_context,write_context
    context=read_context(source)
    registry=SeriesRegistry(root);registry._id(identifier)
    terms={**context.get('confirmed_terms',{}),**registry.confirmed(identifier)}
    write_context(source,context.get('source_file') or origin,terms,context.get('speech_terms'),context.get('uncertain_ranges'),context.get('source_kind','subtitle'))
    path=Path(str(source)+'.source.json');data=read_json(path);data['series_project']=identifier
    atomic_write_text(path,json.dumps(data,ensure_ascii=False,indent=2))
