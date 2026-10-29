"""Deterministic season review tools. Every operation is previewable and scoped."""
from __future__ import annotations
import math,re,os
from pathlib import Path
from review_workspace import SubtitleDocument,TEXT_EXTENSIONS,digest,json_read

STYLE_DEFAULTS={'honorifics':'preserve','register':'source','profanity':'source','notes':'none','line_width':42,'max_cps':20}
STYLE_CHOICES={'honorifics':('preserve','adapt'),'register':('source','formal','casual'),'profanity':('source','soften'),'notes':('none','preserve')}

def validate_style(value):
    if not isinstance(value,dict):raise ValueError('Guia de estilo inválido.')
    result={**STYLE_DEFAULTS,**{k:v for k,v in value.items() if k in STYLE_DEFAULTS}}
    for key,choices in STYLE_CHOICES.items():
        if result[key] not in choices:raise ValueError('Guia de estilo inválido.')
    for key,low,high in (('line_width',24,60),('max_cps',10,30)):
        number=result[key]
        if type(number) not in (int,float) or not math.isfinite(number) or int(number)!=number or not low<=number<=high:raise ValueError('Limites de legibilidade inválidos.')
        result[key]=int(number)
    return result

def style_prompt(style):
    style=validate_style(style)
    return ' Project style: '+ ' '.join((
        {'preserve':'Keep existing Japanese honorifics; do not add absent ones.','adapt':'Adapt honorifics naturally without losing relationships or respect.'}[style['honorifics']],
        {'source':'Follow each speaker’s original register.','formal':'Prefer formal wording while preserving character voice and meaning.','casual':'Prefer conversational wording while preserving respect and meaning.'}[style['register']],
        {'source':'Preserve the original intensity of profanity.','soften':'Soften profanity without reversing intent or adding politeness.'}[style['profanity']],
        {'none':'Never add translator notes.','preserve':'Preserve existing translator notes, but never invent new notes.'}[style['notes']]))

def reflow(text,width=42,ass=False):
    """Only plain, single-speaker prose. Never rewrite styling, lyrics or drawings."""
    if re.search(r'\{[^}]*\}|<[^>]*>|[♪♫♬♩]|\\[Nnh]|^\s*[-–—]|\n\s*[-–—]',text):return text
    words=text.split()
    if not words:return text
    joined=' '.join(words)
    if len(joined)<=width:return joined
    candidates=[]
    for i in range(1,len(words)):
        a=' '.join(words[:i]);b=' '.join(words[i:])
        if max(len(a),len(b))<=width:
            penalty=abs(len(a)-len(b))+(0 if a[-1] in ',;:.!?' else 5)
            candidates.append((penalty,a,b))
    if not candidates:return text  # no deletion or three-line expansion
    _,a,b=min(candidates)
    return a+(r'\N' if ass else '\n')+b

def timestamp(value,ass=False):
    unit=100 if ass else 1000;ticks=round(value*unit)
    hours,rest=divmod(ticks,3600*unit);minutes,rest=divmod(rest,60*unit);sec,frac=divmod(rest,unit)
    return f'{hours}:{minutes:02}:{sec:02}.{frac:02}' if ass else f'{hours:02}:{minutes:02}:{sec:02},{frac:03}'

def synced_raw(doc,offset,scale):
    offset=float(offset);scale=float(scale)
    if not math.isfinite(offset) or not math.isfinite(scale) or not .5<=scale<=2 or abs(offset)>86400:raise ValueError('Parâmetros de sincronização inválidos.')
    intervals=[]
    for a,b in doc.bounds:
        if a is None or b is None or b<=a:raise ValueError('Corrija os tempos inválidos antes de sincronizar.')
        a=a*scale+offset;b=b*scale+offset
        precision=100 if doc.ext=='.ass' else 1000
        if a<0 or b<=a or b>359999 or round(b*precision)<=round(a*precision):raise ValueError('O ajuste criaria tempos negativos ou inválidos.')
        intervals.append((a,b))
    raw=doc.render();lines=raw.splitlines(keepends=True);index=0;inside=False;fields=[]
    pattern=r'((?:\d+:)?\d{2}:\d{2}[.,]\d{2,3})(\s+-->\s+)((?:\d+:)?\d{2}:\d{2}[.,]\d{2,3})'
    # For SRT/VTT, change only timing lines, never timestamps inside dialogue/NOTE.
    if doc.ext!='.ass':
        blocks=re.split(r'(\r?\n\s*\r?\n)',raw);changed=0
        for bi in range(0,len(blocks),2):
            bl=blocks[bi].splitlines(keepends=True)
            if bl and bl[0].strip().startswith(('NOTE','STYLE','REGION','WEBVTT')):continue
            for li in range(min(2,len(bl))):
                if re.match('^'+pattern,bl[li].strip()):
                    a,b=intervals[changed];left=timestamp(a);right=timestamp(b)
                    if doc.ext=='.vtt':left=left.replace(',','.');right=right.replace(',','.')
                    bl[li]=re.sub(pattern,lambda m:left+m[2]+right,bl[li],count=1);changed+=1;break
            blocks[bi]=''.join(bl)
        if changed!=len(intervals):raise ValueError('Estrutura temporal não reconhecida.')
        return ''.join(blocks)
    fields=['layer','start','end','style','name','marginl','marginr','marginv','effect','text']
    for i,line in enumerate(lines):
        stripped=line.strip()
        if stripped.startswith('['):inside=stripped.casefold()=='[events]'
        elif inside and stripped.casefold().startswith('format:'):fields=[x.strip().casefold() for x in stripped.split(':',1)[1].split(',')]
        elif inside and re.match(r'Dialogue\s*:',stripped,re.I):
            prefix,payload=line.split(':',1);newline='\r\n' if line.endswith('\r\n') else '\n' if line.endswith('\n') else ''
            payload=payload.rstrip('\r\n');ti=fields.index('text');front=payload.split(',',ti);remaining=len(fields)-ti-1
            values=front[:-1]+(front[-1].rsplit(',',remaining) if remaining else [front[-1]])
            a,b=intervals[index];values[fields.index('start')]=timestamp(a,True);values[fields.index('end')]=timestamp(b,True)
            lines[i]=prefix+':'+','.join(values)+newline;index+=1
    if index!=len(intervals):raise ValueError('Estrutura temporal não reconhecida.')
    return ''.join(lines)

def replace_visible(text,old,new,case_sensitive=True,whole=True):
    if not old or not old.strip() or not new.strip() or any(x in old+new for x in ('\n','\r','{','}','<','>','\\')):raise ValueError('Use termos de texto simples para propagar.')
    # Exclude markup and ASS escape sequences from replacements.
    pieces=re.split(r'(\{[^}]*\}|<[^>]*>|\\[Nnh]|&\w+;)',text)
    pattern=re.escape(old)
    if whole:
        if old[0].isalnum():pattern=r'(?<!\w)'+pattern
        if old[-1].isalnum():pattern+=r'(?!\w)'
    for i in range(0,len(pieces),2):pieces[i]=re.sub(pattern,lambda _:new,pieces[i],flags=0 if case_sensitive else re.I)
    return ''.join(pieces)

def discover(folders,limit=1500):
    found=set();skip={'history','context_inputs','retranslate','samples','previews','runtime','cache','.ollama_home','ollama_models_v2','.git','_cache_traducao'}
    for folder in folders:
        folder=Path(folder)
        if folder.is_file():
            if folder.suffix.lower() in TEXT_EXTENSIONS:found.add(folder.resolve())
            continue
        for base,dirs,files in os.walk(folder,followlinks=False):
            dirs[:]=sorted(d for d in dirs if d not in skip and not Path(base,d).is_symlink())
            for name in sorted(files):
                path=Path(base,name)
                if path.suffix.lower() in TEXT_EXTENSIONS and not path.is_symlink():found.add(path.resolve())
                if len(found)>limit:raise ValueError('Selecione uma pasta menor: limite de 1500 legendas.')
    return sorted(found,key=lambda p:str(p).casefold())

def episode_summary(doc,style=None):
    import subtitle_quality as Q
    style=validate_style(style or {});doc.line_width=style['line_width'];doc.max_cps=style['max_cps'];flags=doc.flags();speeds=[]
    for text,(a,b) in zip(doc.values,doc.bounds):
        if a is not None and b is not None and b>a:speeds.append(len(Q.plain(text))/(b-a))
    return dict(file=doc.origin_path.name,path=str(doc.path),total=len(doc.values),pending=sum(bool(f) and i not in doc.approved for i,f in enumerate(flags)),approved=len(doc.approved),
                fast=sum(s>style['max_cps'] for s in speeds),long=sum(any(len(Q.plain(line))>style['line_width'] for line in re.split(r'\n|\\N',t)) for t in doc.values),maxCps=round(max(speeds,default=0),1),source=doc.source_context.get('source_kind') or ('subtitle' if doc.source_path else 'unknown'))
