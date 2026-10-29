"""Fansub metadata, safe ASS export, episode ordering and empirical queue estimates."""
from __future__ import annotations
import re,math,statistics
from pathlib import Path
from html.parser import HTMLParser
from season_tools import timestamp

KINDS=('dialogue','music','sign')
PRESET_DEFAULTS=dict(font='Arial',size=48,color='#FFFFFF',outline_color='#000000',outline=2,shadow=1,margin=45,alignment=2,width=1920,height=1080,preserve_ass=True,bold=False)
# Calibrated against the user's captures; this is not an official service preset.
REFERENCE_PRESET={**PRESET_DEFAULTS,'font':'Trebuchet MS','size':66,'outline':5,'shadow':0,'bold':True}

def annotations(value,count):
    if not isinstance(value,dict):raise ValueError('Classificação de blocos inválida.')
    result={}
    for key,entry in value.items():
        if not str(key).isdigit() or not 0<=int(key)<count or not isinstance(entry,dict) or entry.get('kind') not in KINDS or type(entry.get('simultaneous')) is not bool:raise ValueError('Classificação de blocos inválida.')
        result[int(key)]={'kind':entry['kind'],'simultaneous':entry['simultaneous']}
    return result

def ass_fields(doc):
    if doc.ext!='.ass':return [{} for _ in doc.values]
    fields=['layer','start','end','style','name','marginl','marginr','marginv','effect','text'];inside=False;result=[]
    for line in doc.render().splitlines():
        if line.strip().startswith('['):inside=line.strip().casefold()=='[events]'
        elif inside and line.lower().startswith('format:'):fields=[v.strip().lower() for v in line.split(':',1)[1].split(',')]
        elif inside and re.match(r'Dialogue\s*:',line,re.I):
            payload=line.split(':',1)[1].lstrip();i=fields.index('text');front=payload.split(',',i);tail=len(fields)-i-1;values=front[:-1]+(front[-1].rsplit(',',tail) if tail else [front[-1]])
            result.append(dict(zip(fields,values)))
    return result

def suggest(doc):
    fields=ass_fields(doc);result=[]
    for i,text in enumerate(doc.values):
        style=fields[i].get('style','').casefold();kind='dialogue';reason=''
        if any(mark in text for mark in '♪♫♬♩') or re.search(r'\b(song|karaoke|lyrics|opening|ending|op|ed)\b',style) or re.search(r'\\k[fo]?\d',text):kind='music';reason='music_marker'
        elif re.search(r'\b(signs?|placas?|titles?)\b',style) or re.search(r'\\(?:pos|move|an[789])\b',text):kind='sign';reason='position_or_style'
        result.append(dict(index=i,number=i+1,time=doc.times[i],text=text,suggestedKind=kind,reason=reason,**getattr(doc,'annotations',{}).get(i,{'kind':'dialogue','simultaneous':False})))
    return result

def validate_preset(value):
    if not isinstance(value,dict):raise ValueError('Padrão de exportação inválido.')
    preset={**PRESET_DEFAULTS,**{k:v for k,v in value.items() if k in PRESET_DEFAULTS}}
    if not isinstance(preset['font'],str) or not re.fullmatch(r'[\w .()\-]{1,80}',preset['font']):raise ValueError('Nome de fonte inválido.')
    for key in ('color','outline_color'):
        if not isinstance(preset[key],str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',preset[key]):raise ValueError('Use uma cor no formato #RRGGBB.')
    for key,low,high in [('size',14,100),('outline',0,8),('shadow',0,8),('margin',0,300),('width',320,7680),('height',240,4320)]:
        number=preset[key]
        if type(number) not in (float,int) or not math.isfinite(number) or int(number)!=number or not low<=number<=high:raise ValueError('Dimensões do padrão inválidas.')
        preset[key]=int(number)
    if preset['alignment'] not in (2,8) or type(preset['preserve_ass']) is not bool or type(preset['bold']) is not bool:raise ValueError('Padrão de exportação inválido.')
    preset['alignment']=int(preset['alignment'])
    return preset

class AssText(HTMLParser):
    def __init__(self,bold=False):super().__init__(convert_charrefs=True);self.out=[];self.stack=[];self.bold=bold
    def handle_data(self,data):
        if re.search(r'[{}]|\\[Nnh]',data):raise ValueError('Texto com comandos ASS literais exige conversão manual.')
        self.out.append(data.replace('\r\n','\n').replace('\n',r'\N'))
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag in self.stack:raise ValueError('Tags aninhadas do mesmo tipo exigem revisão manual.')
        if tag in ('b','i','u','s'):self.out.append('{\\'+tag+'1}');self.stack.append(tag)
        elif tag in ('v','lang'):self.stack.append(tag)
        elif tag=='br':self.out.append(r'\N')
        elif tag=='font' and set(attrs)<= {'color'} and attrs.get('color') and re.fullmatch(r'#[0-9a-fA-F]{6}',attrs['color']):
            self.out.append('{\\c'+ass_color(attrs['color'])+'}');self.stack.append(tag)
        else:raise ValueError('Formatação não suportada na conversão ASS. Preserve o ASS original ou revise o bloco.')
    def handle_endtag(self,tag):
        if tag=='br':return
        if not self.stack or self.stack.pop()!=tag:raise ValueError('Tags sem par na exportação ASS.')
        if tag in ('v','lang'):return
        self.out.append(r'{\c}' if tag=='font' else '{\\'+tag+('1' if tag=='b' and self.bold else '0')+'}')

def ass_color(color):return '&H00'+color[5:7]+color[3:5]+color[1:3]+'&'

def render_ass(doc,value):
    preset=validate_preset(value)
    if doc.ext=='.ass' and preset['preserve_ass']:return doc.render()
    if doc.ext=='.ass':raise ValueError('ASS existente preserva sua diagramação. Converta uma origem SRT/VTT para aplicar outro padrão.')
    header=f'''[Script Info]
Title: SubForgeAI export
ScriptType: v4.00+
PlayResX: {preset['width']}
PlayResY: {preset['height']}
WrapStyle: 0
ScaledBorderAndShadow: yes
Collisions: Normal

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
'''
    for name,alignment,italic in [('Dialogue',preset['alignment'],0),('Simultaneous',preset['alignment'],0),('Music',8,-1),('Sign',8,0)]:
        header+=f"Style: {name},{preset['font']},{preset['size']},{ass_color(preset['color'])},&H000000FF,{ass_color(preset['outline_color'])},&H80000000,{-1 if preset['bold'] else 0},{italic},0,0,100,100,0,0,1,{preset['outline']},{preset['shadow']},{alignment},{preset['margin']},{preset['margin']},{preset['margin']},1\n"
    header+='\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'
    for i,(text,(a,b)) in enumerate(zip(doc.values,doc.bounds)):
        if a is None or b is None or a<0 or b<=a or round(b*100)<=round(a*100):raise ValueError('A exportação ASS exige tempos válidos de pelo menos um centésimo.')
        annotation=getattr(doc,'annotations',{}).get(i,{});kind=annotation.get('kind','dialogue');style={'dialogue':'Dialogue','music':'Music','sign':'Sign'}[kind]
        if kind=='dialogue' and annotation.get('simultaneous'):style='Simultaneous'
        parser=AssText(bold=preset['bold']);parser.feed(text);parser.close()
        if parser.stack:raise ValueError('Tags sem par na exportação ASS.')
        header+=f'Dialogue: 0,{timestamp(a,True)},{timestamp(b,True)},{style},,0,0,0,,'+''.join(parser.out)+'\n'
    return header


def reference_copy(source, cancel=None):
    """Create a styled sibling; do not rewrite source text, timing or artwork."""
    from types import SimpleNamespace
    from review_workspace import load_document_without_reports,decode
    from subtitle_formats import parse_ass_document
    from pipeline_io import reserve_output,staged_output
    from speech_context import read_context,write_context
    source=Path(source)
    if cancel is not None and cancel.is_set():raise RuntimeError('Cancelado')
    if source.suffix.lower() not in ('.srt','.vtt','.ass'):raise ValueError('Selecione uma legenda SRT, ASS ou VTT.')
    context=read_context(source)
    if context.get('visual_style')=='reference-v1':return str(source.resolve())
    import hashlib
    source_sha=hashlib.sha256(source.read_bytes()).hexdigest()
    preferred=source.with_name(source.stem+'.visual.ass')
    cached=read_context(preferred) if preferred.is_file() else {}
    if cached.get('visual_style')=='reference-v1' and cached.get('visual_source_sha')==source_sha and cached.get('visual_source_path')==str(source.resolve()):
        return str(preferred.resolve())
    if source.suffix.lower()=='.ass':
        raw=decode(source.read_bytes());template,records=parse_ass_document(raw)
        doc=SimpleNamespace(ext='.ass',render=lambda:raw)
        fields=ass_fields(doc);match=re.search(r'(?im)^PlayResY\s*:\s*(\d+)\s*$',raw)
        height=int(match[1]) if match else 288
        if not 1<=height<=7680:raise ValueError('Resolução ASS inválida.')
        size=66*height/1080;outline=5*height/1080
        prefix=r'{\fnTrebuchet MS\fs'+f'{size:.3f}'+r'\b1\bord'+f'{outline:.3f}'+r'\shad0\1c&HFFFFFF&\3c&H000000&}'
        values=[];changed=0
        for index,(_,value) in enumerate(records):
            if cancel is not None and cancel.is_set():raise RuntimeError('Cancelado')
            style=fields[index].get('style','')
            special=re.search(r'(?i)(sign|placa|title|karaoke|song|music|lyrics|opening|ending)',style) or re.search(r'\\(?:pos\b|move\b|org\b|clip\b|iclip\b|p[1-9]|k[fo]?\d|an[789]|t\(|fr[xyz]?\b|fax\b|fay\b|fsc[xy]\b)',value) or any(c in value for c in '♪♫♬♩')
            if special:values.append(value)
            elif value.startswith(prefix):values.append(value)
            else:values.append(prefix+value);changed+=1
        if not changed:
            if any(value.startswith(prefix) for value in values):return str(source.resolve())
            raise ValueError('Esta legenda ASS contém apenas elementos especiais; sua diagramação foi preservada.')
        content=template.render(values)
    else:
        doc=load_document_without_reports(source);doc.ext=source.suffix.lower();doc.annotations={}
        if not doc.values:raise ValueError('A legenda não contém falas válidas.')
        content=render_ass(doc,REFERENCE_PRESET)
    with reserve_output(preferred) as target:
        with staged_output(target) as temporary:
            temporary.write_text(content,encoding='utf-8-sig')
            if cancel is not None and cancel.is_set():raise RuntimeError('Cancelado')
        write_context(target,context.get('source_file') or source,context.get('confirmed_terms',{}),context.get('speech_terms'),context.get('uncertain_ranges'),context.get('source_kind','subtitle'),context.get('series_project'))
        import json
        from pipeline_io import atomic_write_text
        sidecar=Path(str(target)+'.source.json');data=json.loads(sidecar.read_text(encoding='utf-8'));data.update(visual_style='reference-v1',visual_source_sha=source_sha,visual_source_path=str(source.resolve()))
        atomic_write_text(sidecar,json.dumps(data,ensure_ascii=False,indent=2))
    return str(target.resolve())

def episode_number(path):
    name=Path(path).stem
    if re.search(r'(?i)(?:^|[\W_])(?:ova|oad|specials?|especiais?|ncop|nced|creditless|opening|ending|op|ed)(?:[\W_]|\d|$)',name):return None,None,'special'
    match=re.search(r'(?i)(?<![A-Za-z0-9])S(\d{1,2})[ ._-]*E(\d{1,3})(?!\d)',name)
    if match:return int(match[1]),int(match[2]),'episode'
    cleaned=re.sub(r'\[[^]]*\]|\([^)]*\)',' ',name);cleaned=re.split(r'(?i)[ _.-]track\d',cleaned)[0]
    if re.search(r'(?i)(?:^|\s|-)\d{1,3}\s*[-–]\s*\d{1,3}(?:\s|$)',cleaned):return None,None,'range'
    match=re.search(r'(?i)(?:\b(?:ep(?:isode|isódio)?|e)\s*|(?:^|\s[-–]\s|\s))(\d{1,3})(?=\s*(?:[._ -]*(?:ptbr|pt-br|eng|en|ja|jpn|pt|br|sub|subtitle|result))*\s*$)',cleaned)
    return (None,int(match[1]),'episode') if match else (None,None,'unknown')

def organize(paths,expected_end=0):
    expected_end=int(expected_end)
    if not 0<=expected_end<=500:raise ValueError('Informe o último episódio entre 0 e 500.')
    rows=[];groups={};numbers={}
    for path in paths:
        season,number,kind=episode_number(path);row=dict(path=str(path),file=Path(path).name,season=season,episode=number,kind=kind,duplicate=False);rows.append(row)
        if number is not None:
            groups.setdefault((season,number,Path(path).suffix.lower()),[]).append(row);numbers.setdefault(season,set()).add(number)
    for matches in groups.values():
        if len(matches)>1:
            for row in matches:row['duplicate']=True
    missing=[]
    for season,values in numbers.items():
        end=expected_end or max(values)
        missing.extend(dict(season=season,episode=i) for i in range(1,end+1) if i not in values)
    rows.sort(key=lambda r:(r['season'] or 0,r['episode'] is None,r['episode'] or 0,r['file'].casefold()))
    return dict(rows=rows,missing=missing)

def performance_key(operation,options,settings):
    return (operation,options.get('source_mode','auto'),settings.get('whisper_model',''),settings.get('whisper_device',''),settings.get('whisper_demucs_mode',''),settings.get('ollama_model',''),bool(options.get('sample_seconds')),options.get('audio_language',settings.get('whisper_language','auto')),settings.get('extract_to','copy'),bool(settings.get('embed_enabled')),settings.get('resource_cpu_threads',0),settings.get('resource_gpu_layers',-1),settings.get('resource_background',False))

def estimate(items,reports,settings):
    remaining=[];rates=[];sizes=[];unknown=0
    for item in items:
        if item.get('state')=='Concluído':continue
        options=item.get('options') or {};key=performance_key(item.get('operation','auto'),options,settings);ext=Path(item['path']).suffix.lower();history=[]
        for report in reports:
            if report.get('state')!='Concluído' or tuple(report.get('performance_key',[]))!=key or Path(report.get('input','')).suffix.lower()!=ext:continue
            duration=report.get('effective_seconds');output_bytes=report.get('output_bytes')
            if type(duration) in (int,float) and math.isfinite(duration) and duration>0:history.append(duration)
            if type(output_bytes) is int and output_bytes>=0:sizes.append(output_bytes)
        if len(history)<2:unknown+=1;continue
        avg=statistics.median(history[-20:])
        try:progress=float(item.get('progress',0)) if item.get('state')=='Executando' else 0
        except (ValueError,TypeError):progress=0
        progress=min(1,max(0,progress)) if math.isfinite(progress) else 0
        remaining.append(avg*(1-progress));rates.append(3600/avg)
    return dict(pending=sum(i.get('state')!='Concluído' for i in items),seconds=round(sum(remaining)) if remaining else None,unknown=unknown,episodesPerHour=round(statistics.median(rates),1) if rates else None,
                outputBytes=round(statistics.median(sizes)*sum(i.get('state')!='Concluído' for i in items)) if sizes and not unknown else None)
