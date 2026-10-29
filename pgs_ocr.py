"""Offline PGS reader and conservative OCR. Originals are never modified."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import re
import os
from pipeline_io import atomic_write_text, reserve_output

@dataclass
class BitmapCue:
    start: float
    end: float
    image: object


def segments(data):
    offset = 0
    while offset + 3 <= len(data):
        kind = data[offset]
        size = int.from_bytes(data[offset+1:offset+3], "big")
        if offset + 3 + size > len(data):
            raise ValueError("Segmento PGS truncado")
        yield kind, data[offset+3:offset+3+size]
        offset += 3 + size
    if offset != len(data):
        raise ValueError("Cabeçalho PGS truncado")


def read_pgs(path):
    import av
    import numpy as np
    palettes = {}
    palette_id = 0
    active = None
    composition_time = None
    pending = []
    with av.open(str(path)) as container:
        for packet in container.demux():
            if not packet.size:
                continue
            timestamp = float(packet.pts * packet.time_base) if packet.pts is not None else None
            for kind, payload in segments(bytes(packet)):
                if kind == 0x14:
                    palette = palettes.setdefault(payload[0], np.zeros((256,2), dtype=np.uint8))
                    for i in range(2,len(payload)-4,5):
                        palette[payload[i]] = (payload[i+1],payload[i+4])
                elif kind == 0x16:
                    if active is not None and timestamp is not None:
                        if timestamp > active.start:
                            active.end = timestamp
                            yield active
                        active = None
                    composition_time = timestamp
                    palette_id = payload[9]
                    pending = []
            rectangles = packet.decode()
            for rect in rectangles:
                if not hasattr(rect, "planes") or not rect.planes:
                    continue
                palette = palettes.get(palette_id)
                if palette is None:
                    raise ValueError("PGS sem paleta disponível")
                indices = np.frombuffer(bytes(rect.planes[0]), dtype=np.uint8).reshape(rect.height, rect.width)
                luminance = np.clip((palette[:,0].astype(float)-16)*255/219,0,255)
                lookup = (255-luminance*palette[:,1].astype(float)/255).astype(np.uint8)
                pending.append((rect.x,rect.y,lookup[indices]))
            if rectangles and pending and composition_time is not None:
                x=min(r[0] for r in pending);y=min(r[1] for r in pending)
                right=max(a+im.shape[1] for a,b,im in pending)
                bottom=max(b+im.shape[0] for a,b,im in pending)
                canvas=np.full((bottom-y,right-x),255,dtype=np.uint8)
                for a,b,im in pending:
                    target=canvas[b-y:b-y+im.shape[0],a-x:a-x+im.shape[1]]
                    np.minimum(target,im,out=target)
                active=BitmapCue(composition_time,composition_time,canvas)
    if active is not None:
        raise ValueError("Última imagem PGS sem tempo de término; arquivo possivelmente incompleto")


def text_lines(image):
    import numpy as np
    ink=np.any(image < 150,axis=1)
    runs=[];start=None
    for i,value in enumerate([*ink,False]):
        if value and start is None:start=i
        elif not value and start is not None:
            if runs and start-runs[-1][1]<=3:runs[-1]=(runs[-1][0],i)
            else:runs.append((start,i))
            start=None
    return [image[max(0,a-2):min(image.shape[0],b+2)] for a,b in runs if b-a>=3]


class Reader:
    def __init__(self):
        from rapidocr import RapidOCR
        from maintenance_tools import resources
        threads=resources({'resource_cpu_threads':os.environ.get('SUBFORGEAI_CPU_THREADS','0')})['resource_cpu_threads'] or 4
        self.engine=RapidOCR(params={"Global.log_level":"error", "EngineConfig.onnxruntime.intra_op_num_threads":threads,"EngineConfig.onnxruntime.inter_op_num_threads":1})

    def recognize(self,image):
        import cv2
        lines=[];scores=[]
        for line in text_lines(image):
            line=cv2.copyMakeBorder(line,5,5,5,5,cv2.BORDER_CONSTANT,value=255)
            line=cv2.resize(line,None,fx=2,fy=2)
            result=self.engine(line,use_det=False,use_cls=False)
            lines.extend(result.txts or ())
            scores.extend(float(x) for x in (result.scores or ()))
        padded=cv2.copyMakeBorder(image,10,10,10,10,cv2.BORDER_CONSTANT,value=255)
        alternate=self.engine(cv2.resize(padded,None,fx=2,fy=2))
        text="\n".join(lines)
        detected=" ".join(alternate.txts or ())
        norm=lambda s:re.sub(r"[^a-z0-9]","",s.casefold())
        flags=[]
        if not text.strip():flags.append("empty_ocr")
        if scores and min(scores)<0.95:flags.append("low_ocr_confidence")
        if norm(text)!=norm(detected):flags.append("ocr_disagreement")
        return {"text":text,"min_score":min(scores,default=0),"alternate":detected,"flags":flags}


def timestamp(seconds):
    ms=max(0,round(seconds*1000));h,ms=divmod(ms,3600000);m,ms=divmod(ms,60000);s,ms=divmod(ms,1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def convert(path,outdir,reader=None):
    path=Path(path);reader=reader or Reader();records=[]
    for cue in read_pgs(path):
        record=reader.recognize(cue.image)
        record.update(start=cue.start,end=cue.end)
        records.append(record)
    if not records or any(not r["text"].strip() for r in records):
        raise ValueError("OCR vazio: consulte as imagens antes de gerar uma legenda incompleta")
    content="\n\n".join(f"{i}\n{timestamp(r['start'])} --> {timestamp(r['end'])}\n{r['text']}" for i,r in enumerate(records,1))+"\n"
    with reserve_output(Path(outdir)/(path.stem+".ocr.srt")) as output:
        atomic_write_text(Path(str(output)+".ocr.json"),json.dumps({"source":str(path.resolve()),"source_sha256":hashlib.sha256(path.read_bytes()).hexdigest(),"verified":False,"records":records},ensure_ascii=False,indent=2))
        atomic_write_text(output,content)
        from speech_context import write_context
        write_context(output,path,{},uncertain_ranges=[{"start":r["start"],"end":r["end"],"flags":r["flags"]} for r in records if r["flags"]],source_kind="ocr")
    return output


if __name__=="__main__":
    import argparse
    parser=argparse.ArgumentParser(description="Converte PGS/SUP por OCR offline; exige revisão das divergências.")
    parser.add_argument("inputs",nargs="+")
    parser.add_argument("--outdir",required=True)
    args=parser.parse_args();reader=Reader()
    for item in args.inputs:print(convert(item,args.outdir,reader),flush=True)
