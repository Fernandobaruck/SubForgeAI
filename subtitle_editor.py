"""Reusable source-aware post-editing; series vocabulary stays in data files."""
from __future__ import annotations
import json
import re
import subtitle_quality as Q

POLICY = "editorial-v3"


def japanese_input(text):
    return Q.japanese_input(text)


def normalized_source(text: str, language: str = "en") -> tuple[str, list[str]]:
    notes = []
    if language == "en":
        changed = re.sub(r"^1,(?=\s+the\s)", "I,", text)
        changed = re.sub(r"\bI-1(?=\s+(?:wonder|think|guess|don't|can't))", "I-I", changed)
        if changed != text: notes.append("source_ocr_pronoun")
        text = changed
    elif language == "ja":
        changed = re.sub(r"\b0\b", "o", text)
        if changed != text: notes.append("source_ocr_romaji_particle")
        text = changed
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) == 2 and re.fullmatch(r'"[^"\n]+"', lines[1]):
        from difflib import SequenceMatcher
        letters = lambda value: re.sub(r"[^a-z]", "", value.casefold())
        if SequenceMatcher(None, letters(lines[0]), letters(lines[1])).ratio() >= .8:
            text = lines[1].strip('"'); notes.append("source_duplicate_caption")
    return text, notes


def postedit(call, model, source, draft, before, after, terms, seconds, *, feedback="", language_hint=None):
    romaji = language_hint == "ja" or Q.romanized_japanese(source)
    language = "Japanese" if romaji else "English"
    code = "ja" if romaji else "en"
    # The existing draft already carries scene context. Repeating neighbouring
    # dialogue here made the translation model append those lines to the cue.
    before, after = "", ""
    prompt = (
        f"You are a professional {language} ({code}) to Brazilian Portuguese (pt-BR) subtitle translator. "
        "Post-edit the supplied Portuguese draft against the source. Return the draft unchanged if already faithful and natural. "
        "Correct wrong meaning, subject, tense, negation, gender and word choice. Preserve the speaker's tone. "
        "Do not add information, explanations, requests, or dialogue from neighbouring cues. "
        "Never turn a character's name into an ordinary word. Never output gender alternatives like obrigado(a). "
        "Use concise natural spoken Brazilian Portuguese, without dropping facts. "
        "Translate complete sentences across display line breaks; those breaks are not sentence boundaries. "
        "The current cue is the ONLY text to translate. Background is ONLY for disambiguation. "
    )
    if romaji: prompt += "These are Japanese song lyrics. Translate their meaning, not their spelling. "
    if terms: prompt += "\nConfirmed terminology: " + json.dumps(terms, ensure_ascii=False)
    if before or after:
        prompt += "\nBackground ONLY: " + json.dumps({"previous":before[-650:],"following":after[:650]}, ensure_ascii=False)
    if not romaji:
        prompt += "\nPortuguese draft to correct: " + json.dumps(Q.plain(draft),ensure_ascii=False)
    if seconds: prompt += f"\nTry to fit about {max(12,int(seconds*20))} characters without losing meaning."
    if feedback: prompt += "\nRequired correction: " + feedback
    translated_source=Q.japanese_input(source,protected=terms) if romaji else source
    prompt += f"\nProduce ONLY the corrected Brazilian Portuguese subtitle. Please translate the following {language} text into Brazilian Portuguese:\n\n\n{translated_source}"
    return call(model,[{"role":"user","content":prompt}]).strip()


def validate(source, candidate, terms, names):
    flags=[]
    if not candidate.strip(): return ["empty"]
    if re.search(r"(?im)^\s*(?:translation|tradução|source|original|previous|following|draft)\s*:",candidate):flags.append("instruction_leak")
    if Q.SENTINEL.search(candidate):flags.append("marker_leak")
    if any(m.group() not in ("\n","\r\n") for m in Q.FORMAT.finditer(candidate)):
        flags.append("unexpected_format")
    flags += [f for f in Q.quality_flags(source,candidate,None,terms) if f in ("terminology","gender_alternatives","unsupported_show_reference","unsupported_company_reference","excessive_expansion","possessive_shift","old_man_relationship")]
    flags += Q.context_flags(source,candidate,{**names,**terms})
    if len(Q.plain(source).split()) >= 15 and len(candidate.split()) < 4:flags.append("possible_omission")
    return list(dict.fromkeys(flags))


def render(source, candidate, span_call):
    safe,tokens,prefix,suffix=Q.prepare(source)
    if not any(t in ("\n","\r\n",r"\N",r"\n") for t in tokens):
        candidate=re.sub(r"\s*\r?\n\s*"," ",candidate)
    try:result=Q.restore(candidate,tokens,prefix,suffix)
    except ValueError:result=Q.align_inline(source,candidate,span_call)
    return Q.reflow(result)
