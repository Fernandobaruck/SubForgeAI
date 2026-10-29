"""Prepare a human-reviewed collection for publication; never reads private glossaries."""
import argparse
import hashlib
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from studio_ui.online_glossary import terms, slug, text, catalog, MAX_BYTES
from pipeline_io import atomic_write_text


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--id',required=True);parser.add_argument('--title',required=True)
    parser.add_argument('--description',required=True);parser.add_argument('--revision',required=True)
    parser.add_argument('--source-language',choices=['en','ja'],required=True)
    args=parser.parse_args()
    if args.input.stat().st_size>MAX_BYTES:raise ValueError('Proposta grande demais.')
    proposal=json.loads(args.input.read_text(encoding='utf-8-sig'))
    identifier=slug(args.id)
    value=dict(schema=1,id=identifier,revision=text(args.revision,80),source_language=args.source_language,target_language='pt-BR',terms=terms(proposal['terms']))
    raw=(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode()
    if len(raw)>MAX_BYTES:raise ValueError('Coleção grande demais.')
    folder=ROOT/'community/glossary';index=json.loads((folder/'index.json').read_text(encoding='utf-8'));catalog(index)
    existing=next((row for row in index['collections'] if row['id']==identifier),None)
    digest=hashlib.sha256(raw).hexdigest()
    if existing and existing['revision']==args.revision and existing['sha256']!=digest:
        raise ValueError('A coleção mudou: use uma revisão nova.')
    entry=dict(id=identifier,title=text(args.title,160),description=text(args.description,600),revision=value['revision'],source_language=args.source_language,target_language='pt-BR',sha256=digest)
    index['collections']=[row for row in index['collections'] if row['id']!=identifier]+[entry]
    index['collections'].sort(key=lambda row:row['title'].casefold());catalog(index)
    atomic_write_text(folder/(identifier+'.json'),raw.decode())
    atomic_write_text(folder/'index.json',json.dumps(index,ensure_ascii=False,indent=2)+'\n')
    print('Coleção preparada para revisar e publicar: '+identifier)


if __name__=='__main__':main()
