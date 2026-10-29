"""Conservative candidate comparison and local audio realignment."""
import re
from difflib import SequenceMatcher


def core(text):
    return re.sub(r'\W+', '', text.casefold())


def timing_defects(segments):
    defects=[]
    for segment in segments:
        words=segment.get('words') or []
        for left,right in zip(words,words[1:]):
            if right['start']-left['end']>2.5:
                defects.append((max(0,left['start']-1.0),left['end']+1.5))
                defects.append((max(0,right['start']-1.5),right['start']+5.5))
        for word in words:
            if word['end']-word['start']>2.0:
                defects.append((max(0,word['start']-1),min(word['end']+1,word['start']+10)))
    return defects


def candidate_decision(old,new,score,alignment=False):
    if not new:return False,'empty_candidate'
    previous=''.join(core(s.get('text','')) for s in old)
    proposed=''.join(core(s.get('text','')) for s in new)
    old_score=sum(score(s) for s in old)/max(1,len(old))
    new_score=sum(score(s) for s in new)/len(new)
    agreement=SequenceMatcher(None,previous,proposed).ratio()
    if not previous:return False,'no_baseline'
    if len(proposed)<max(1,len(previous)*.55):return False,'possible_omission'
    if len(proposed)>len(previous)*2+8:return False,'possible_invention'
    # Confidence alone cannot resolve two different meanings.
    if agreement<.65:return False,'recognition_disagreement'
    if new_score<-.95:return False,'weak_candidate'
    if alignment and len(timing_defects(new))<len(timing_defects(old)) and new_score>=old_score-.08:
        return True,'alignment_improved'
    if alignment and not timing_defects(new) and agreement>=.8 and new_score>=old_score-.08:
        return True,'local_alignment_confirmed'
    if new_score>=old_score+.12:return True,'confidence_improved'
    return False,'baseline_preserved'


def alignment_window_segments(segments,start,end):
    """Trim baseline words to the inspected audio, not a 100-second parent cue."""
    selected=[]
    for segment in segments:
        words=[w for w in segment.get('words') or [] if min(w['end'],end)-max(w['start'],start)>0]
        if words:
            selected.append({**segment,'start':words[0]['start'],'end':words[-1]['end'],
                             'text':''.join(w['word'] for w in words),'words':words})
        elif not segment.get('words') and min(segment['end'],end)-max(segment['start'],start)>0:
            selected.append(segment)
    return selected


def replace_aligned_window(segments,start,end,replacement):
    retained=[]
    for segment in segments:
        words=segment.get('words') or []
        if not words:
            if min(segment['end'],end)-max(segment['start'],start)<=0:retained.append(segment)
            continue
        # Preserve material on BOTH sides of a replaced window.
        for part in ([w for w in words if w['end']<=start],[w for w in words if w['start']>=end]):
            if part:retained.append({**segment,'start':part[0]['start'],'end':part[-1]['end'],
                                    'text':''.join(w['word'] for w in part),'words':part})
    return sorted(retained+replacement,key=lambda s:s['start'])
