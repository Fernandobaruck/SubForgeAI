"""Contextual subtitle preparation, series terminology and quality triage.

No series-specific vocabulary belongs here. Automatic entity suggestions are
editable and never override an explicit series glossary.
"""
from __future__ import annotations
from collections import Counter
from pathlib import Path
import hashlib
import json
import re
import unicodedata

VERSION = "context-cues-v5-caption-markers"
FORMAT = re.compile(r"\{[^}]*\}|<[^>]+>|\\[Nhnh]|\r?\n|[♪♫♬♩](?:[ \t]+)?")
SENTINEL = re.compile(r"ZXQFMT(\d+)QXZ", re.I)
STOP = set("""a an the i you he she it we they me him her us them my your our their
this that these those is are was were be been being am do does did have has had
and or but so if then when where why what who whom which how not no yes oh ah
hey well now really right all some any only just even still already too very
there here come go get take look see know think want can could would should
will must may might please thank thanks sorry hello goodbye good morning night
master father mother brother sister big sir miss mister madam lord lady prince
princess king queen captain teacher doctor magic sorcerer sorcerers court tower
fangs sword light death spirit black white bloody august january february march
april june july september october november december next love don't doesn't
unforgivable absolutely nothing something anything everything wait damn geez
wow whoa huh prepare quiet shut stop help listen welcome congratulations
first last after before following years year month day time understand
it's that's there's here's what's who's he's she's i'm i've i'll you're you've
they're we're don't can't won't isn't wasn't couldn't wouldn't shouldn't
healing naive nakedness bad fencing club brassier orchestra terror star knights
for from of to in on at by with without into since through about as up out
""".split())


def plain(text: str) -> str:
    def visible(match):
        token = match.group()
        if token[:1] in "♪♫♬♩" or token in ("\n", "\r\n", r"\N", r"\n", r"\h") or re.fullmatch(r"<br\s*/?>",token,re.I):
            return " "
        # ASS overrides and inline HTML occupy no horizontal space. Inserting
        # spaces here split words such as Beg{\frz5}o{\frz4}ne into fragments.
        return ""
    return re.sub(r"\s+", " ", FORMAT.sub(visible, text)).strip()


def romanized_japanese(text: str) -> bool:
    """Recognize common romaji grammar, not arbitrary capitalized Latin words."""
    words = re.findall(r"[a-z]+", plain(text).casefold())
    if not words: return False
    english={"i","you","he","she","we","they","is","are","was","were","am","have","has","had",
             "did","does","could","would","should","will","want","need","think","the","this","these",
             "those","your","our","their","said","told","found","get","come",
             "and","or","but","here","there","with","from"}
    if sum(w in english for w in words)>=2:return False
    content = {"watashi", "boku", "ore", "omae", "kimi", "anata", "aitsu", "honto", "hontou",
               "kokoro", "kuchibiru", "hajimete", "zutto", "dakishimetai", "wakaranai", "nazedayo",
               "hitori", "aenaku", "abiru", "marude", "yasashii", "mamoritai", "aishiattari",
               "shiritai", "tsuki", "omoi", "konya", "mabushi", "ryoute", "naichauyo",
               "onna", "yowai", "kono", "terasu", "saigo", "kuchi", "komatteta", "kuchizuke",
               "nokotteiru", "wasureyou", "shitari", "nugisutete", "sutechaeru", "michi",
               "tsuyoku", "ima", "doushiyou", "koi",
               "kumo", "kirema", "sagasu", "sagashite", "sora", "ame", "yuki",
               "kaze", "hoshi", "yume", "sekai", "mirai", "ashita", "kinou",
               "hibi", "aruku", "hashiru", "warau", "utau", "mitsukeru",
               "koe", "namida", "egao", "tsubasa", "yureru", "todoku"}
    particles = {"wa", "ga", "ni", "wo", "o", "no", "de", "to", "mo", "yo", "ka", "kai", "sa", "dake", "ja", "ne"}
    known = sum(w in content for w in words)
    grammar = sum(w in particles for w in words)
    return (known >= 2 or known >= 1 and grammar >= 1
            or any(w in {"wakaranai", "nazedayo", "dakishimetai", "nugisutete", "sutechaeru"} for w in words))


def japanese_input(text: str, protected=()) -> str:
    """Convert confirmed romaji input, keeping embedded English lyric words."""
    import romkan
    english={"cry","fly","headlights","heels","pride","kiss","looking","for","you","and","fall","in","love","just","on","my"}
    particles={"wa":"は","o":"を","wo":"を","e":"へ"}
    def convert(match):
        word=match.group();key=word.casefold()
        if key in english:return word
        return particles.get(key) or romkan.to_hiragana(word)
    patterns=[r'ZXQFMT\d+QXZ']+[r'(?<!\w)'+re.escape(term)+r'(?!\w)' for term in sorted(protected,key=len,reverse=True)]
    keep=re.compile('(?:'+'|'.join(patterns)+')',re.I)
    parts=[];at=0
    for match in keep.finditer(text):
        parts.extend([re.sub(r"[A-Za-z']+",convert,text[at:match.start()]),match.group()]);at=match.end()
    parts.append(re.sub(r"[A-Za-z']+",convert,text[at:]))
    return ''.join(parts)


def normalized(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return "".join(c for c in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(c))


def contains(text: str, term: str) -> bool:
    if re.search(r"[\u3040-\u9fff]", term):
        return term in text
    return bool(re.search(r"(?<!\w)" + re.escape(normalized(term)) + r"(?!\w)", normalized(text)))


def term_present(text: str, term: str) -> bool:
    if contains(text, term): return True
    core = re.sub(r"^(?:o|a|os|as|um|uma)\s+", "", term, flags=re.I)
    return core != term and contains(text, core)


def detect_names(texts: list[str]) -> dict[str, str]:
    """Conservative Latin-script suggestions from repeated names and vocatives."""
    counts = Counter()
    total_counts = Counter()
    canonical = {}
    vocatives = set()
    compound_words = {word.casefold() for term in detect_terms(texts) for word in term.split()}
    for text in texts:
        text = plain(text)
        for match in re.finditer(r"\b[A-Z][a-z]+(?:[-'][A-Z]?[a-z]+)*\b", text):
            token = match.group()
            if token.casefold() in STOP or token.casefold() in compound_words:
                continue
            total_counts[token.casefold()] += 1
            # Mid-sentence capitalized words are stronger evidence than first words.
            if match.start() > 0 and text[:match.start()].strip():
                counts[token.casefold()] += 1
            if re.search(r"\b[A-Z][a-z]+\s+$", text[:match.start()]) or re.match(r"\s+[A-Z][a-z]+\b", text[match.end():]):
                counts[token.casefold()] += 1
            if re.search(r"\b(?:of|in|from)\s+$", text[:match.start()]):
                counts[token.casefold()] += 1
            canonical.setdefault(token.casefold(), token)
        match = re.fullmatch(r"([A-Z][a-z]+(?:[-'][A-Z]?[a-z]+)*)[!?.…]*", text)
        if match and match[1].casefold() not in STOP and match[1].casefold() not in compound_words:
            vocatives.add(match[1].casefold())
    return {canonical[key]: canonical[key] for key in canonical
            if counts[key] >= 2 or (counts[key] >= 1 and total_counts[key] >= 2) or key in vocatives}


def detect_terms(texts: list[str]) -> list[str]:
    joined = "\n".join(plain(t) for t in texts)
    pattern = r"\b[A-Z][a-z]+(?:\s+(?:(?:of|the|of the)\s+)?[A-Z][a-z]+){1,3}\b"
    counts = Counter(re.findall(pattern, joined))
    excluded = {"Big Brother", "Big Sister", "Good Morning", "Good Night", "Thank You",
                "Young Master", "Young Mistress", "My Lord", "My Lady"}
    return sorted((term for term, count in counts.items() if count >= 2 and term not in excluded),
                  key=lambda term: (-len(term), term))[:40]


def load_mapping(path: Path) -> dict[str, str]:
    """Carrega um JSON de termos (UTF-8, com ou sem BOM) de forma tolerante.

    Antes esta função fazia ``path.read_text(encoding="utf-8-sig")`` direto.
    Consequência: um sidecar salvo em cp1252/latin-1 (comum quando alguém
    edita ``series_memory.json`` no Bloco de Notas do Windows) ou um JSON
    truncado levantava UnicodeDecodeError/JSONDecodeError e derrubava a
    tradução do episódio inteiro — o erro aparecia como
    "1 arquivo(s) falharam", sem indicar a causa real.

    Agora:
    * tenta UTF-8-sig, depois cp1252 (superset do latin-1) e por fim
      substitui bytes inválidos, para nunca abortar por codificação;
    * só considera o arquivo inválido se o CONTEÚDO for inválido
      (JSON malformado ou estrutura que não é ``{str: str}``);
    * nesse caso levanta ValueError com o caminho e o motivo, que o
      chamador consegue mostrar ao usuário.
    """
    raw: bytes
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"Não foi possível ler {path}: {exc}") from exc

    text = None
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        # Último recurso: preserva o máximo de texto legível em vez de falhar.
        text = raw.decode("utf-8", errors="replace")

    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ValueError(f"JSON inválido em {path}: {exc}") from exc

    if not isinstance(data, dict) or any(not isinstance(k, str) or not isinstance(v, str)
                                       or not k.strip() or not v.strip() for k, v in data.items()):
        raise ValueError(f"Glossário inválido: {path}")
    return {k.strip(): v.strip() for k, v in data.items()}


def longest_matches(mapping: dict[str, str], text: str) -> dict[str, str]:
    """Resolve overlapping expressions, never require a word inside its phrase."""
    text = normalized(text)
    occupied, selected = [], {}
    for source, target in sorted(mapping.items(), key=lambda pair: -len(pair[0])):
        pattern = re.escape(normalized(source))
        if not re.search(r"[\u3040-\u9fff]", source): pattern = r"(?<!\w)" + pattern + r"(?!\w)"
        matches = [m for m in re.finditer(pattern, text)
                   if not any(m.start() < end and m.end() > start for start, end in occupied)]
        if matches:
            selected[source] = target
            occupied.extend(m.span() for m in matches)
    return selected


class SeriesTerms:
    def __init__(self, source: Path, texts: list[str], cache_dir: Path, language: str):
        self.source = source
        self.explicit = {}
        self.memory = {}
        from speech_context import read_context
        self.provenance = read_context(source)
        origin = Path(self.provenance['source_file']) if self.provenance.get('source_file') else source
        identity = self.provenance.get('series_identity') or hashlib.sha256(str(source.parent.resolve()).casefold().encode()).hexdigest()[:20]
        file_identity = hashlib.sha256(str(source.resolve()).casefold().encode()).hexdigest()[:20]
        app = Path(__file__).resolve().parent
        # Workspace registries keep confirmed vocabularies portable even when
        # the source-video folder is read-only. Source sidecars still win.
        for root in (app,app.parent):
            registry=root/"series_glossaries"
            paths=(registry/(identity+".json"),registry/"files"/(file_identity+".json"))
            if any(p.is_file() for p in paths):
                for path in paths:
                    if path.is_file():self.explicit.update(load_mapping(path))
                break
        for root in (app,app.parent):
            registry=root/"series_memories"
            paths=(registry/(identity+".json"),registry/"files"/(file_identity+".json"))
            if any(p.is_file() for p in paths):
                for path in paths:
                    if path.is_file():self.memory.update(load_mapping(path))
                break
        from series_registry import SeriesRegistry
        registry=SeriesRegistry(app)
        project=self.provenance.get('series_project') or registry.resolve(origin)
        self.style=registry.style(project) if project else {}
        if project:
            self.explicit.update(registry.confirmed(project))
            self.memory.update(registry.memory(project))
        # Folder-level glossary shares vocabulary across episodes; file-level wins.
        self.explicit.update(self.provenance.get('confirmed_terms',{}))
        self.explicit.update(self.provenance.get('speech_terms',{}))
        for path in (origin.parent / "series_glossary.json", origin.with_suffix('.glossary.json'), source.parent / "series_glossary.json", source.with_suffix(".glossary.json")):
            if path.is_file():
                self.explicit.update(load_mapping(path))
        for path in (origin.parent/'series_memory.json',origin.with_suffix('.memory.json'),
                     source.parent/"series_memory.json",source.with_suffix(".memory.json")):
            if path.is_file():self.memory.update(load_mapping(path))
        self.path = cache_dir / "series_terms" / (identity + ".json")
        self.values = load_mapping(self.path) if self.path.is_file() else {}
        self.names = detect_names(texts)
        self.values.update({k: v for k, v in self.names.items() if k not in self.values})
        self.candidates = detect_terms(texts) if language == "en" else []
        self.values.update(self.explicit)

    def fingerprint(self) -> str:
        # Automatic discoveries must not invalidate every episode's checkpoint.
        # Exact-cue memories overwrite only their matching cue on every run.
        # Changing one approved lyric must not reset all unrelated dialogue.
        return hashlib.sha256(json.dumps([self.explicit,self.style], sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def relevant(self, text: str) -> dict[str, str]:
        return longest_matches(self.explicit, text)

    def suggestions(self, text: str) -> dict[str, str]:
        # Legacy files contain unverified identities such as Save -> Save.
        # Never treat those as instructions to keep ordinary source words.
        automatic = {k: v for k, v in self.values.items() if k not in self.explicit and normalized(k) != normalized(v)}
        combined = longest_matches({**automatic, **self.explicit}, text)
        return {k: v for k, v in combined.items() if k not in self.explicit}

    def memory_for(self, text: str) -> str | None:
        identity=normalized(plain(text))
        return next((value for key,value in self.memory.items() if normalized(plain(key))==identity),None)


def render_memory(source: str, translation: str, ass: bool = False) -> str:
    if ass:translation=translation.replace("\r\n","\n").replace("\n",r"\N")
    markup=lambda text:[m.group() for m in FORMAT.finditer(text)
                        if m.group() not in ("\n","\r\n",r"\N",r"\n")]
    if markup(source)==markup(translation):return reflow(translation,ass=ass)
    safe,tokens,prefix,suffix=prepare(source)
    return reflow(restore(plain(translation),tokens,prefix,suffix),ass=ass)


def contextual_address_terms(text: str, before: str = "", after: str = "") -> dict[str,str]:
    """Disambiguate household forms of address only with local evidence."""
    context = " ".join((plain(before),plain(text),plain(after)))
    if re.search(r"\bYoung Master\b",plain(text),re.I) and re.search(
            r"\b(?:father|mother|household|maid|butler|servant|mistress)\b|\bcared for\b",context,re.I):
        return {"Young Master":"jovem senhor"}
    return {}


def terms_only(text: str, confirmed: dict[str,str]) -> str | None:
    """Render name/term lists directly only when every word is confirmed."""
    if not confirmed:return None
    keys=sorted(confirmed,key=len,reverse=True)
    pattern=re.compile(r'(?<!\w)(?:'+'|'.join(re.escape(key) for key in keys)+r')(?!\w)',re.I)
    if not pattern.search(text) or re.search(r'\w',pattern.sub('',text)):
        return None
    values={key.casefold():value for key,value in confirmed.items()}
    return pattern.sub(lambda m:values[m.group().casefold()],text)


def semantic_breaks(text: str) -> bool:
    """Recognize speaker changes and caption annotations across display lines."""
    return bool(re.search(r"(?:\r?\n|\\N|\\n)\s*(?:[-–—]|[（(][^）)\r\n]{1,40}[）)])",text))


def prepare(text: str) -> tuple[str, list[str], str, str]:
    """Remove visual wraps, retain semantic speaker boundaries and exact tags."""
    hard_breaks = semantic_breaks(text)
    tokens = []
    def shield(match):
        value = match.group()
        if value in ("\n", "\r\n", r"\N", r"\n") and not hard_breaks:
            return " "
        key = f"ZXQFMT{len(tokens)}QXZ"
        tokens.append(value)
        return key
    safe = FORMAT.sub(shield, text)
    # Wrappers need no cooperation from the model and cannot move to other text.
    prefix, suffix = "", ""
    while (match := re.match(r"^ZXQFMT\d+QXZ", safe)):
        prefix += match.group(); safe = safe[match.end():]
    while (match := re.search(r"ZXQFMT\d+QXZ$", safe)):
        suffix = match.group() + suffix; safe = safe[:match.start()]
    return safe.strip(), tokens, prefix, suffix


def restore(text: str, tokens: list[str], prefix: str, suffix: str) -> str:
    hard = [i for i, value in enumerate(tokens) if value in ("\n", "\r\n", r"\N", r"\n")]
    if hard and len(re.findall(r"\r?\n", text)) == len(hard) and not any(f"ZXQFMT{i}QXZ" in text for i in hard):
        ids = iter(hard)
        text = re.sub(r"\r?\n", lambda _: f"ZXQFMT{next(ids)}QXZ", text)
    packed = prefix + text.strip() + suffix
    indices = [int(m[1]) for m in SENTINEL.finditer(packed)]
    if indices != list(range(len(tokens))):
        raise ValueError("Marcadores de formatação perdidos, repetidos ou reordenados.")
    if re.search(r"ZXQ|QXZ", SENTINEL.sub("", packed), re.I):
        raise ValueError("Marcador de formatação danificado.")
    if FORMAT.search(SENTINEL.sub("", packed)):
        raise ValueError("O modelo inventou formatação ou quebras.")
    return SENTINEL.sub(lambda m: tokens[int(m[1])], packed)


def request_text(safe: str, tokens: list[str]) -> str:
    for i, value in enumerate(tokens):
        if value in ("\n", "\r\n", r"\N", r"\n"):
            safe = safe.replace(f"ZXQFMT{i}QXZ", "\n")
    return safe


def align_inline(source: str, target: str, translate_span) -> str:
    """Restore paired emphasis around an unambiguous translated phrase.

    Span translation is used solely to locate formatting. The full-sentence
    translation is never replaced by concatenated fragment translations.
    """
    if SENTINEL.search(target) or FORMAT.search(target):
        raise ValueError("Não é possível alinhar uma resposta com marcadores extras.")
    stack, insertions, order = [], [], 0
    for match in FORMAT.finditer(source):
        value = match.group()
        if value in ("\n", "\r\n", r"\N", r"\n"):
            if semantic_breaks(source):
                raise ValueError("Quebra entre falantes não pode ser descartada.")
            continue
        opening = re.fullmatch(r"<([a-z]+)(?:\s[^>]*)?>", value, re.I)
        closing = re.fullmatch(r"</([a-z]+)>", value, re.I)
        ass_open = re.fullmatch(r"\{\\([ibu])1\}", value)
        ass_close = re.fullmatch(r"\{\\([ibu])0\}", value)
        if opening or ass_open:
            kind = (opening or ass_open)[1].casefold()
            stack.append((kind, value, match.end(), order)); order += 1
        elif closing or ass_close:
            kind = (closing or ass_close)[1].casefold()
            if not stack or stack[-1][0] != kind: raise ValueError("Tags sem par para alinhamento.")
            _, token, start, index = stack.pop()
            fragment = plain(source[start:match.start()])
            if fragment == plain(source):
                left, right = 0, len(target)
            else:
                translated = plain(translate_span(fragment)).strip('"“” .!?…')
                variants = [translated, re.sub(r"^(?:o|a|os|as|um|uma)\s+", "", translated, flags=re.I)]
                positions = []
                for variant in variants:
                    if not variant: continue
                    positions = list(re.finditer(re.escape(variant), target, re.I))
                    if len(positions) == 1: break
                if len(positions) != 1: raise ValueError("Trecho formatado não pôde ser alinhado com segurança.")
                left, right = positions[0].span()
            insertions.extend([(left, index, token), (right, order, value)]); order += 1
        else:
            raise ValueError("Formatação complexa precisa de revisão de alinhamento.")
    if stack: raise ValueError("Tag sem fechamento.")
    result, at = [], 0
    for position, _, value in sorted(insertions):
        result.extend([target[at:position], value]); at = position
    result.append(target[at:])
    return "".join(result)


def reflow(text: str, ass: bool = False, width: int = 42) -> str:
    """Wrap at word boundaries without truncation or changes to drawing commands."""
    if re.search(r"\{[^}]*\\p[1-9]", text):
        return text
    if "\n" in text or r"\N" in text:
        # Explicit speaker boundaries remain separate.
        return text
    if len(plain(text)) <= width:
        return text
    protected = [(m.start(), m.end()) for m in FORMAT.finditer(text)]
    choices = []
    for match in re.finditer(r" +", text):
        if any(a <= match.start() < b for a, b in protected):
            continue
        left, right = text[:match.start()], text[match.end():]
        l, r = len(plain(left)), len(plain(right))
        if not l or not r: continue
        bad_end = bool(re.search(r"\b(?:de|da|do|das|dos|a|o|as|os|e|em|com|para|que)$", plain(left), re.I))
        score = max(0, l-width)*100 + max(0, r-width)*100 + abs(l-r) + 12*bad_end
        choices.append((score, match.start(), match.end()))
    if not choices: return text
    _, start, end = min(choices)
    return text[:start] + (r"\N" if ass else "\n") + text[end:]


def quality_flags(source: str, target: str, duration: float | None, terms: dict[str, str], language: str = "en", *, width: int = 42, cps: float = 20) -> list[str]:
    flags = []
    if not re.search(r"[（(]",source) and re.search(
            r"[（(]\s*(?:express(?:ão|ões)\s+de|onomatopeia|nota\s+do\s+tradutor|tradução\s*:)",target,re.I):
        flags.append("translator_explanation")
    if any(not term_present(target, value) for key, value in terms.items() if contains(source, key)):
        flags.append("terminology")
    if re.search(r"\w+\((?:a|o|as|os)\)", target, re.I): flags.append("gender_alternatives")
    if re.search(r"\b(?:meu irmão/minha irmã|irmão/irmã|ele/ela|dele/dela|o/a|um/uma)\b", target, re.I):
        flags.append("gender_alternatives")
    if language == "en":
        if re.search(r"\b(?:programa|reality show)\b", target, re.I) and not re.search(r"\b(?:show|program|programme|reality)\b", source, re.I):
            flags.append("unsupported_show_reference")
        if re.search(r"\b(?:empresa|companhia)\b", target, re.I) and not re.search(r"\b(?:company|business|corporation|firm)\b", source, re.I):
            flags.append("unsupported_company_reference")
        if re.search(r"\byour\b", source, re.I) and not re.search(r"\b(?:my|our)\b", source, re.I) and re.search(r"\b(?:meu|minha|meus|minhas)\b", target, re.I):
            flags.append("possessive_shift")
        if re.search(r"\byour old man\b", source, re.I) and not re.search(r"\b(?:pai|velho)\b", target, re.I):
            flags.append("old_man_relationship")
        if re.search(r"\bpor favor\b", target, re.I) and not re.search(r"\b(?:please|beg|kindly|favor)\b", source, re.I):
            flags.append("added_politeness")
    lines = re.split(r"\n|\\N", target)
    if any(len(plain(line)) > width for line in lines): flags.append("long_line")
    if len(lines) > 2: flags.append("too_many_lines")
    if duration and len(plain(target))/duration > cps: flags.append("reading_speed")
    if language == "en":
        source_words = re.findall(r"\b[\w’']+\b", plain(source))
        target_words = re.findall(r"\b[\w’']+\b", plain(target))
        if len(target_words) >= len(source_words)+5 and len(target_words) > max(1,len(source_words))*2.5:
            flags.append("excessive_expansion")
    return list(dict.fromkeys(flags + fidelity_flags(source,target,language)))


def fidelity_flags(source: str, target: str, language: str) -> list[str]:
    source, target = plain(source), plain(target)
    latin = re.findall(r"[A-Za-zÀ-ÿ’']+",source)
    japanese = len(re.findall(r'[\u3040-\u30ff\u3400-\u9fff]',source))
    words = re.findall(r"[\w’']+",target)
    if japanese:
        limit = max(8, int(japanese*.9)+len(latin)*2)
        if len(words)>limit: return ['excessive_expansion']
    elif len(latin)<=3 and len(words)>max(5,len(latin)*2+2):
        return ['excessive_expansion']
    return []


def context_flags(source: str, target: str, names: dict[str, str]) -> list[str]:
    if re.search(r'[\u3040-\u9fff]',source):
        # A Latin canonical name is not evidence of leakage when ASR writes
        # its Japanese pronunciation. Only matched-script aliases are testable.
        names={k:v for k,v in names.items() if re.search(r'[\u3040-\u9fff]',k)}
    permitted=[dst for src,dst in names.items() if contains(source,src)]
    if any(contains(target, dst) and not contains(source, src)
           and not any(contains(allowed,dst) for allowed in permitted)
           for src, dst in names.items()):
        return ["context_entity_leak"]
    return []


def duration(timestamp: str) -> float | None:
    matches = re.findall(r"(?:\d+:)?\d{2}:\d{2}[.,]\d+", timestamp)
    if len(matches) != 2: return None
    def seconds(value):
        result = 0.0
        for part in value.replace(",", ".").split(":"): result = result*60 + float(part)
        return result
    return seconds(matches[1])-seconds(matches[0])
