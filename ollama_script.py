# -*- coding: utf-8 -*-
"""
SubForgeAI - Ollama subtitle translator (SRT/ASS/VTT)
- Batch translation with strict markers <<<N>>> to keep 1:1 mapping
- Auto retry & auto split on format mismatch
- Optional review pass: off | auto | always
- Prints progress bar + PASS 2/2 message only when reviewing
- Compatible with Ollama /api/chat (new) and /api/generate (fallback)
- Output to "outputs/pt-br" by default
- Cache/progress folder is removed by default to avoid conflicts
"""
from __future__ import annotations

import argparse
from contextvars import ContextVar
import hashlib
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path
from typing import List, Optional, Tuple

# Embedded Python uses an isolated ._pth; include this script's own modules.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pipeline_io import atomic_write_text, directory_lock, reserve_output
from glossary_support import Glossary
import subtitle_quality as Q
from subtitle_formats import (parse_vtt_document, build_vtt_document,
                              parse_ass_document, build_ass_document)

import requests

CONTEXT_REQUEST_STATE = ContextVar("subtitle_request_state", default=None)

APP_DIR = Path(__file__).resolve().parent
_DEFAULT_GLOSSARY = next((p for p in (APP_DIR / "glossary.json", APP_DIR.parent / "glossary.json")
                          if p.is_file()), APP_DIR / "glossary.json")
GLOSSARY = Glossary(_DEFAULT_GLOSSARY)
DEFAULT_OUTDIR = APP_DIR / "outputs" / "pt-br"

# defaults (can be overridden by CLI)
MODELO_OLLAMA = "translategemma:12b"
BLOCOS_POR_REQUISICAO = 1
PROGRESS_EVERY = 5
BAR_SIZE = 24
MAX_RETRIES = 3
CACHE_VERSION = "3-validated-format"

TEMPO_ENTRE_REQS = 0.08
TIMEOUT_REQ = 180

# Teto de chamadas extras que o reparo de resíduo em inglês pode fazer por lote.
# Sem teto, um lote com muitas linhas "ruins" multiplicava requisições no multipass.
_MAX_ENGLISH_REPAIRS = 4

# Review mode:
# - off: fastest
# - auto: only review if heuristics detect likely issues (recommended)
# - always: always review (best quality, slower)
REVIEW_MODE = "auto"  # off | auto | always
SOURCE_LANGUAGE = "auto"
ACTIVE_SOURCE_LANGUAGE = "en"
ACTIVE_SERIES_HINTS = {}
ACTIVE_PROJECT_STYLE = {}
TRANSLATEGEMMA_ADAPTER = "context-cues-v1"

# Whether to print PASS 2/2 line when reviewing
SHOW_REVIEW_PASS_LOG = True

# Novos modos de revisão (2026):
# - disabled: sem revisão (mais rápido)
# - auto: revisão por heurística (equilibrado)
# - enabled: Tradução → Revisão → Refino → Revisão (dupla revisão)
# - enabled_plus: enabled + 1 revisão global extra no final
#
# Compat: "off" == "disabled", "on" == "enabled", "on_plus" == "enabled_plus", "always" mantém modo legado (revisa todo lote).
def normalize_review_mode(raw: str) -> str:
    v = (raw or "").strip().lower()
    if not v:
        return "auto"
    mapping = {
        "off": "disabled",
        "disabled": "disabled",
        "none": "disabled",
        "0": "disabled",
        "false": "disabled",
        "auto": "auto",
        "always": "always",   # legado
        "on": "enabled",
        "enabled": "enabled",
        "on_plus": "enabled_plus",
        "enabled_plus": "enabled_plus",
        "enabled+": "enabled_plus",
        "plus": "enabled_plus",
    }
    return mapping.get(v, "auto")


SUB_EXTS = {".srt", ".ass", ".vtt"}

SYSTEM_PROMPT = (
    "Você é um tradutor profissional de legendas para PT-BR.\n"
    "REGRAS OBRIGATÓRIAS:\n"
    "1) Traduza SOMENTE o texto falado.\n"
    "2) NÃO invente falas.\n"
    "3) NÃO adicione explicações, notas ou comentários.\n"
    "4) Preserve quebras de linha.\n"
    "5) Preserve tags e códigos (ex: {\\...}, <i>...</i>, [..]).\n"
    "6) Não mude nomes próprios.\n"
    "7) Retorne SOMENTE o texto traduzido.\n"
    "8) Se estiver incerto(a), retorne o texto original SEM inventar.\n"
)

# Mesmas palavras, porém exigindo fronteira de palavra no que se testa para decidir
# se uma linha PT precisa de revisão. Sem isso, "is" casa dentro de "isto", "to"
# dentro de "gato" e "at" dentro de "atitude" — a revisão dispararia em todo lote.
_REPEATS = re.compile(r"(.)\1\1\1+")
MARKER_RE = re.compile(r"<<<(\d+)>>>\s*(.*?)(?=(<<<\d+>>>|$))", re.S)

# Sentinelas para tokens que o LLM costuma destruir na tradução.
# \N, \n e \h são quebras/espaços do ASS; [..] são rótulos de efeito sonoro.

# Options de amostragem enviadas ao Ollama. Servidores novos aceitam o objeto
# "options"; os antigos simplesmente ignoram o campo, então é retrocompatível.
OLLAMA_OPTIONS: dict = {
    "temperature": 0.1,
    "top_p": 0.9,
    "repeat_penalty": 1.08,
    "num_ctx": 8192,
}


class InvalidModelOutput(ValueError):
    """The model response cannot safely be published as subtitle text."""


def _is_translategemma(model: str) -> bool:
    return model.split(":", 1)[0].split("/")[-1].lower() == "translategemma"


def _detect_source_language(text: str) -> str:
    if SOURCE_LANGUAGE != "auto":
        return SOURCE_LANGUAGE
    # Script detection disambiguates short Asian dialogue before statistical detection.
    latin = len(re.findall(r"[A-Za-z]", text))
    if len(re.findall(r"[\u3040-\u30ff]", text)) >= max(1, latin // 6):
        return "ja"
    if len(re.findall(r"[\uac00-\ud7af]", text)) >= max(1, latin // 6):
        return "ko"
    from langdetect import DetectorFactory, detect, LangDetectException
    DetectorFactory.seed = 0
    plain = re.sub(r"<[^>]*>|\{[^}]*\}|\d+|[^\w\sÀ-ž]", " ", text)
    if not plain.strip():
        return "en"
    try:
        return detect(plain[:24000])
    except LangDetectException as exc:
        raise ValueError("Não foi possível detectar o idioma; informe --source-lang.") from exc


def _translategemma_item(model: str, text: str) -> str:
    safe, tokens, prefix, suffix = Q.prepare(text)
    if not re.search(r"[^\W\d_]", safe):
        return Q.restore(safe, tokens, prefix, suffix)
    translated = _context_call(model, Q.request_text(safe, tokens), "", "", {})
    try:
        return Q.reflow(Q.restore(translated, tokens, prefix, suffix))
    except ValueError as exc:
        raise InvalidModelOutput(str(exc)) from exc



def _has_prompt_scaffolding(text: str) -> bool:
    return bool(re.search(r"(?im)^\s*SRC\s*:", text)
                and re.search(r"(?im)^\s*PT\s*:", text))


def _validated_marked_call(model: str, items: List[str], prompt: str,
                           context_texts: Optional[List[str]] = None) -> List[str]:
    protected, maps = [], []
    for text in items:
        safe, mapping = _protect_tags(text)
        protected.append(safe)
        maps.append(mapping)
    if context_texts is not None:
        if len(context_texts) != len(items):
            raise ValueError("Contexto e tradução têm quantidades diferentes de itens.")
        packed_items = [f"SRC:\n{_strip_tags_for_check(src)}\nPT:\n{pt}"
                        for src, pt in zip(context_texts, protected)]
    else:
        packed_items = protected
    glossary = GLOSSARY.prompt([*(context_texts or []), *items])
    user = (prompt + "\nRetorne apenas o texto final de cada item; não repita SRC: ou PT:.\n"
            + glossary + "\n" + _pack_marked(packed_items))
    response = _ollama_call(model, [{"role": "system", "content": SYSTEM_PROMPT},
                                    {"role": "user", "content": user}])
    parsed = _parse_marked(response, len(items))
    if parsed is None:
        raise InvalidModelOutput("O modelo omitiu itens, repetiu marcadores ou retornou campos de instrução.")
    result = [_restore_tags(text, mapping) for text, mapping in zip(parsed, maps)]
    if any(not text.strip() for text in result):
        raise InvalidModelOutput("O modelo retornou uma fala vazia.")
    for original, translated in zip(items, result):
        if _format_tokens(original) != _format_tokens(translated):
            raise InvalidModelOutput("O modelo alterou tags ou quebras de linha da legenda.")
    return result


def _llm_refine_call(model: str, items: List[str], prompt: str) -> List[str]:
    pairs = [json.loads(item) for item in items]
    return _validated_marked_call(model, [pair["translation"] for pair in pairs], prompt,
                                  context_texts=[pair["source"] for pair in pairs])








def _hash_key(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8", errors="ignore")).hexdigest()


def _load_json(path: Path) -> dict:
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
            print(f"[WARN] Cache inválido; os itens serão reprocessados: {path}")
    except (OSError, ValueError) as exc:
        print(f"[WARN] Não foi possível ler o cache {path}: {exc}")
    return {}


def _save_json(path: Path, data: dict) -> None:
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2))


def _cache_prefix(path: Path) -> str:
    return _hash_key(os.path.normcase(str(path.resolve()))) + ":"


def _cache_context(path: Path, model: str, texts: List[str], pass_tag: str) -> str:
    settings = [CACHE_VERSION, model, normalize_review_mode(REVIEW_MODE), SYSTEM_PROMPT,
                OLLAMA_OPTIONS, GLOSSARY.fingerprint(), pass_tag, texts]
    if _is_translategemma(model):
        settings += [TRANSLATEGEMMA_ADAPTER, ACTIVE_SOURCE_LANGUAGE, "num_ctx=4096"]
    return _cache_prefix(path) + _hash_key(json.dumps(settings, ensure_ascii=False))


def _item_cache_key(context: str, index: int) -> str:
    return f"{context}:{index}"


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _write_text(path: Path, txt: str) -> None:
    atomic_write_text(path, txt)


class OllamaTransientError(RuntimeError):
    """A request can be retried without accepting its partial response."""


def _ollama_stream(url: str, payload: dict) -> Optional[str]:
    started = time.monotonic()
    for without_options in (False, True):
        body = dict(payload, stream=True)
        if without_options:
            body.pop("options", None)
        try:
            with requests.post(url, json=body, stream=True, timeout=(10, TIMEOUT_REQ)) as response:
                if response.status_code in (404, 405):
                    return None
                if response.status_code in (400, 422) and not without_options:
                    continue
                if response.status_code in (408, 429, 500, 502, 503, 504):
                    raise OllamaTransientError(f"Ollama temporariamente indisponível (HTTP {response.status_code}).")
                response.raise_for_status()
                chunks = []
                for line in response.iter_lines():
                    if time.monotonic() - started > 900:
                        raise OllamaTransientError("Ollama excedeu 15 minutos nesta chamada.")
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except (ValueError, TypeError) as exc:
                        raise OllamaTransientError("Resposta de fluxo inválida do Ollama.") from exc
                    if data.get("error"):
                        raise RuntimeError(f"Ollama: {data['error']}")
                    chunks.append((data.get("message") or {}).get("content") or data.get("response") or "")
                    if data.get("done") is True:
                        if data.get("done_reason") == "length":
                            raise InvalidModelOutput("Ollama atingiu o limite de geração; resposta incompleta descartada.")
                        return "".join(chunks).strip()
                raise OllamaTransientError("Ollama encerrou a conexão antes de concluir a resposta.")
        except requests.RequestException as exc:
            if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
                raise OllamaTransientError(f"Falha temporária de comunicação com Ollama: {exc}") from exc
            raise RuntimeError(f"Falha ao chamar o Ollama em {url}: {exc}") from exc
    raise RuntimeError("Ollama rejeitou a requisição.")


def _ollama_call(model: str, messages: list[dict]) -> str:
    base = (os.environ.get("SUBFORGEAI_OLLAMA_BASE_URL") or "http://127.0.0.1:11434").rstrip("/")
    chat_url = f"{base}/api/chat"
    gen_url = f"{base}/api/generate"

    from studio_ui.gpu_policy import ensure_ollama_gpu
    ensure_ollama_gpu(base, model)
    options = dict(OLLAMA_OPTIONS)
    from maintenance_tools import resources
    limits=resources({'resource_cpu_threads':os.environ.get('SUBFORGEAI_CPU_THREADS','0'),'resource_gpu_layers':os.environ.get('SUBFORGEAI_GPU_LAYERS','-1')})
    if limits['resource_cpu_threads']:options['num_thread']=limits['resource_cpu_threads']
    options['num_gpu'] = 999  # All layers; CPU/mixed residency is rejected before generation.
    if _is_translategemma(model):
        options.update(num_ctx=4096, num_predict=2048, temperature=0.0, repeat_penalty=1.0)
    result = _ollama_stream(chat_url, {"model": model, "messages": messages, "options": options, "keep_alive": "2m"})
    if result is not None:
        return result
    prompt = "\n\n".join(m.get("content") or "" for m in messages if m.get("role") in ("system", "user"))
    result = _ollama_stream(gen_url, {"model": model, "prompt": prompt, "options": options, "keep_alive": "2m"})
    if result is None:
        raise RuntimeError("O servidor Ollama não oferece /api/chat nem /api/generate.")
    return result


def _protect_tags(text: str) -> Tuple[str, dict]:
    """Protect each format token once, in source order."""
    mapping = {}
    def replace(match):
        key = f"⟦TAG{len(mapping)}⟧"
        mapping[key] = match.group(0)
        return key
    pattern = r"\\[Nnh]|\r\n|\n|\r|\{[^}]*\}|<[^>]+>|\[[^\[\]]{1,80}\]|⟦[^⟦⟧]*⟧"
    return re.sub(pattern, replace, text or ""), mapping


def _format_tokens(text: str) -> list[str]:
    return re.findall(r"\\[Nnh]|\r\n|\n|\r|\{[^}]*\}|<[^>]+>|\[[^\[\]]{1,80}\]|⟦[^⟦⟧]*⟧", text)


def _restore_tags(text: str, mapping: dict) -> str:
    """Accept tolerant token spelling, but reject loss, duplication or reordering."""
    expected = list(mapping)
    normal = lambda value: re.sub(r"[\s_-]+", "", value).casefold()
    by_normal = {normal(key): key for key in expected}
    observed = []
    def restore(match):
        key = by_normal.get(normal(match.group(0)))
        if key is None:
            raise InvalidModelOutput("O modelo devolveu um marcador de formatação desconhecido.")
        observed.append(key)
        return mapping[key]
    result = re.sub(r"⟦[^⟦⟧]{1,80}⟧", restore, text or "")
    if observed != expected:
        raise InvalidModelOutput("O modelo perdeu, duplicou ou reordenou tags da legenda.")
    return result


def _strip_tags_for_check(text: str) -> str:
    text = re.sub(r"\{[^}]*\}", " ", text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\[[^\]]*\]", " ", text)
    text = re.sub(r"⟦[^⟦⟧]*⟧", " ", text)
    text = text.replace("\\N", " ").replace("\\n", " ").replace("\\h", " ")
    return re.sub(r"\s+", " ", text).strip()


def _src_probably_english(text: str) -> bool:
    """Use distinct English evidence; ambiguous Portuguese words never count."""
    words = re.findall(r"[^\W\d_]+(?:['’-][^\W\d_]+)*", _strip_tags_for_check(text), re.UNICODE)
    tokens = {word.casefold() for word in words}
    english = tokens & {
        "the", "you", "your", "are", "is", "was", "were", "have", "has",
        "does", "did", "with", "from", "this", "that", "these", "those",
        "and", "of", "don't", "doesn't", "didn't", "can't", "thank",
        "hello", "goodbye", "sorry", "thanks", "please",
    }
    portuguese = tokens & {
        "o", "a", "os", "as", "do", "da", "dos", "das", "de", "no", "na",
        "nos", "nas", "um", "uma", "eu", "você", "vocês", "não", "sim",
        "está", "estão", "é", "são", "meu", "minha", "para", "pelo", "pela",
        "com", "que", "ele", "ela", "isso", "isto", "aqui", "também", "mas",
        "seu", "sua", "obrigado", "por",
    }
    if len(tokens) == 1:
        return bool(english & {"hello", "goodbye", "sorry", "thanks", "please"})
    return len(english) >= 2 and len(english) > len(portuguese) and len(english) / max(1, len(words)) >= 0.25


def _has_english_residual(src: str, tr: str) -> bool:
    # The translated text itself must contain English evidence. A Portuguese
    # phrase never becomes English just because its source was English.
    if _src_probably_english(tr):return True
    # Source-aligned ordinary nouns can leak inside an otherwise Portuguese
    # sentence. Require lowercase evidence; proper names/loanwords stay intact.
    ordinary={'cuckoo','starling','gullible','clairvoyance','underlings','squirrelly','peeping'}
    source_words=set(re.findall(r"\b[a-z]+\b",_strip_tags_for_check(src).casefold()))
    target_words=set(re.findall(r"\b[a-z]+\b",_strip_tags_for_check(tr)))
    return bool(ordinary & source_words & target_words)


def _deterministic_english_cleanup(src: str, tr: str) -> str:
    # Only complete, unformatted glossary entries are substituted directly;
    # sentence terminology is supplied as context to the model.
    for original, translated in GLOSSARY.terms().items():
        if (tr or "").strip().casefold() == original.casefold():
            return translated
    return tr or ""


def _retry_no_english_line(model: str, src: str) -> str:
    return _validated_marked_call(
        model, [src],
        "Traduza fielmente para PT-BR, corrigindo resíduos em inglês. Preserve nomes próprios, honoríficos e todos os tokens.",
    )[0]


def _repair_english_residual_lines(model: str, src_list: List[str], tr_list: List[str]) -> List[str]:
    """Corrige resíduos em inglês sem multiplicar chamadas ao LLM.

    Antes, cada pass do multipass chamava este reparo, e cada linha "ruim"
    gerava uma requisição própria. Aqui limitamos a reparos cirúrgicos:
      - nunca age quando a fonte é PT (evita retraduzir legenda já correta);
      - nunca age quando a linha traduzida já não tem residual;
      - limita o total de chamadas extras por lote a _MAX_ENGLISH_REPAIRS.
    """
    fixed = list(tr_list)
    if not src_list or not fixed:
        return fixed

    limit = min(len(fixed), _MAX_ENGLISH_REPAIRS)
    repaired = 0

    for i, (src, tr) in enumerate(zip(src_list, fixed)):
        if repaired >= limit:
            break
        if not _has_english_residual(src, tr):
            continue

        # 1) tentativa determinística (sem LLM)
        cur = _deterministic_english_cleanup(src, tr)
        if not _has_english_residual(src, cur):
            fixed[i] = cur
            continue

        # The residual detector now validates the output language itself;
        # this also repairs English accidentally produced from Japanese.
        try:
            retried = _retry_no_english_line(model, src)
        except Exception:
            fixed[i] = cur
            continue

        retried = _deterministic_english_cleanup(src, retried)
        if retried.strip():
            fixed[i] = retried
            repaired += 1

    return fixed


def _progress_bar(done: int, total: int) -> str:
    total = max(1, int(total))
    done = max(0, min(int(done), total))
    pct = int(done * 100 / total)
    filled = int(BAR_SIZE * pct / 100)
    bar = "█" * filled + "░" * (BAR_SIZE - filled)
    return f"[{bar}] {pct}% ({done}/{total})"


def parse_srt(content: str) -> List[Tuple[str, str, str]]:
    """Converte SRT em [(índice, timestamp, texto)].

    Tolerâncias importantes em relação à versão anterior:
      - CRLF/CR normalizados (antes o '\\r' final contaminava o texto);
      - blocos sem numeração explícita são aceitos (a 1ª linha já é o
        timestamp), pois legendas extraídas de vídeo frequentemente vêm assim;
      - blocos com 2+ linhas são mantidos (antes exigia 3 e descartava falas,
        encurtando a legenda de saída).
    """
    if content is None:
        return []
    normalized = (content or "").replace("\r\n", "\n").replace("\r", "\n")
    blocks: List[Tuple[str, str, str]] = []

    for part in re.split(r"\n\s*\n", normalized.strip()):
        lines = [ln for ln in part.split("\n")]
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()

        if not lines:
            continue

        first = lines[0].strip()
        if "-->" in first:
            # sem índice: o próprio timestamp abre o bloco
            idx = str(len(blocks) + 1)
            ts = first
            txt = "\n".join(lines[1:]).rstrip()
        elif len(lines) >= 2 and "-->" in lines[1]:
            idx = first
            ts = lines[1].strip()
            txt = "\n".join(lines[2:]).rstrip()
        else:
            # bloco sem timestamp válido: preserva como texto para não perder fala
            idx = str(len(blocks) + 1)
            ts = "00:00:00,000 --> 00:00:00,000"
            txt = "\n".join(lines).strip()
            if not txt:
                continue

        blocks.append((idx, ts, txt))

    return blocks


def build_srt(blocks: List[Tuple[str, str, str]]) -> str:
    out = []
    for idx, ts, txt in blocks:
        out.append(str(idx))
        out.append(ts)
        out.append(txt)
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def parse_vtt(content: str) -> Tuple[str, List[Tuple[str, str]]]:
    return parse_vtt_document(content or "")






def build_vtt(header: str, cues: List[Tuple[str, str]]) -> str:
    return build_vtt_document(header, cues)


def parse_ass(content: str) -> Tuple[str, List[Tuple[str, str]]]:
    return parse_ass_document(content or "")


def build_ass(header: str, dialogues: List[Tuple[str, str]]) -> str:
    return build_ass_document(header, dialogues)


def _needs_review(src_list: List[str], tr_list: List[str]) -> bool:
    if not src_list or not tr_list or len(src_list) != len(tr_list):
        return True
    bad = 0
    for s, t in zip(src_list, tr_list):
        s2 = (s or "").strip()
        t2 = (t or "").strip()
        if s2 and not t2:
            bad += 2
            continue
        if s2 and len(t2) > max(80, int(len(s2) * 2.6)):
            bad += 1
        if _has_english_residual(s2, t2):
            bad += 2
        if _REPEATS.search(t2):
            bad += 1
    return bad >= 2


def _pack_marked(items: List[str]) -> str:
    return "\n".join([f"<<<{i}>>>\n{t}\n" for i, t in enumerate(items, start=1)])


def _parse_marked(out: str, n: int) -> Optional[List[str]]:
    if n <= 0:
        return []
    first = MARKER_RE.search(out or "")
    if first is None or (out or "")[:first.start()].strip():
        return None
    found = {}
    for match in MARKER_RE.finditer(out or ""):
        index = int(match.group(1))
        if index < 1 or index > n or index in found:
            return None
        text = (match.group(2) or "").strip()
        if not text or _has_prompt_scaffolding(text):
            return None
        found[index] = text
    if set(found) != set(range(1, n + 1)):
        return None
    return [found[index] for index in range(1, n + 1)]


def _translate_batch(model: str, texts: List[str]) -> Optional[List[str]]:
    if _is_translategemma(model):
        translated = [_translategemma_item(model, text) for text in texts]
        if normalize_review_mode(REVIEW_MODE) != "disabled":
            for index, (source, target) in enumerate(zip(texts, translated)):
                if ACTIVE_SOURCE_LANGUAGE == "en" and _has_english_residual(source, target):
                    print("[INFO] TranslateGemma: repetindo fala com possível resíduo em inglês.", flush=True)
                    translated[index] = _translategemma_item(model, source)
                    if _has_english_residual(source, translated[index]):
                        raise InvalidModelOutput("TranslateGemma manteve texto em inglês; item não foi aceito.")
        return translated
    prompt = (
        "Traduza cada item para PT-BR. Retorne SOMENTE os itens com seus marcadores <<<N>>>.\n"
        "Preserve todos os tokens ⟦TAGN⟧ exatamente uma vez, na ordem original.\n"
        "Não adicione itens, notas, cabeçalhos ou falas."
    )
    translated = _validated_marked_call(model, texts, prompt)
    translated = _repair_english_residual_lines(model, texts, translated)
    mode = normalize_review_mode(REVIEW_MODE)
    if mode in ("disabled", "enabled", "enabled_plus"):
        return translated
    if mode == "always" or (mode == "auto" and _needs_review(texts, translated)):
        if SHOW_REVIEW_PASS_LOG:
            print("  ↳ PASS 2/2: Revisão do lote...", flush=True)
        # A review that cannot preserve the format fails explicitly. Never
        # substitute source text or a wrapped SRC/PT instruction as a result.
        translated = _validated_marked_call(
            model, translated,
            "Revise levemente o PT-BR, preservando o sentido e todos os tokens. "
            "Retorne somente os itens com seus marcadores.",
            context_texts=texts,
        )
    return translated


def _translate_with_retries(model: str, texts: List[str]) -> List[str]:
    return _call_with_retries_generic(model, texts, _translate_batch)



# -------------------------
# Multipass (Tradução/Rev/Refino/Rev [+ Global])
# -------------------------
def _llm_marked_call(model: str, items: List[str], user_prompt_prefix: str) -> Optional[List[str]]:
    return _validated_marked_call(model, items, user_prompt_prefix)


def _call_with_retries_generic(model: str, items: List[str], call_fn) -> List[str]:
    if not items:
        return []
    for attempt in range(MAX_RETRIES):
        try:
            result = call_fn(model, items)
            if (result is not None and len(result) == len(items)
                    and all(isinstance(text, str) and text.strip()
                            and not _has_prompt_scaffolding(text) for text in result)):
                return result
        except InvalidModelOutput as exc:
            print(f"[WARN] {exc} Tentativa {attempt + 1}/{MAX_RETRIES}.", flush=True)
        except OllamaTransientError as exc:
            if len(items) > 1:
                half = len(items) // 2
                print(f"[WARN] {exc} Reduzindo lote de {len(items)} para até {len(items) - half} itens.", flush=True)
                return (_call_with_retries_generic(model, items[:half], call_fn)
                        + _call_with_retries_generic(model, items[half:], call_fn))
            if attempt + 1 == MAX_RETRIES:
                raise
            print(f"[WARN] {exc} Nova tentativa {attempt + 2}/{MAX_RETRIES}.", flush=True)
        if attempt + 1 < MAX_RETRIES:
            time.sleep(TEMPO_ENTRE_REQS)
    if len(items) > 1:
        half = len(items) // 2
        return (_call_with_retries_generic(model, items[:half], call_fn)
                + _call_with_retries_generic(model, items[half:], call_fn))
    raise InvalidModelOutput("Resposta incompleta ou com formatação inválida após as tentativas. O progresso válido foi preservado.")


def _run_pass(
    *,
    pass_idx: int,
    pass_total: int,
    pass_name: str,
    pass_tag: str,
    file_path: Path,
    model: str,
    in_items: List[str],
    call_fn,
    cache: dict,
    progress: dict,
    save_cache_fn,
    save_prog_fn,
) -> List[str]:
    total = len(in_items)
    file_key = _cache_context(file_path, model, in_items, pass_tag)
    start_at = sum(_item_cache_key(file_key, i) in cache for i in range(total))

    print("\n" + "-" * 60)
    print(f"[PASS {pass_idx}/{pass_total}] {pass_name}", flush=True)
    print(f"Itens: {total} | Retomar: {start_at}/{total}", flush=True)

    out_items = list(in_items)
    # Rebuild every completed item; a cursor alone is not an output checkpoint.
    i = 0
    done = 0

    while i < total:
        batch_indices: List[int] = []
        batch_items: List[str] = []

        while i < total and len(batch_items) < BLOCOS_POR_REQUISICAO:
            inp = in_items[i]
            ckey = _item_cache_key(file_key, i)
            if ckey in cache:
                out_items[i] = cache[ckey]
                progress[file_key] = i + 1
                i += 1
                done += 1
                if done % PROGRESS_EVERY == 0 or done == total:
                    print(_progress_bar(done, total), flush=True)
                continue

            batch_indices.append(i)
            batch_items.append(inp)
            i += 1

        if not batch_items:
            continue

        # log do lote (pra acompanhar em tempo real)
        b0 = batch_indices[0] + 1
        b1 = batch_indices[-1] + 1
        print(f"  ↳ Lote {b0}-{b1}/{total} ...", flush=True)

        out_batch = _call_with_retries_generic(model, batch_items, call_fn)

        for k, tr in enumerate(out_batch):
            bi = batch_indices[k]
            inp = in_items[bi]
            ckey = _item_cache_key(file_key, bi)
            cache[ckey] = tr
            out_items[bi] = tr
            progress[file_key] = bi + 1
            done = max(done, bi + 1)

        # salva progresso/caches frequentemente (rollback e resume seguros)
        save_cache_fn()
        save_prog_fn()

        if done % PROGRESS_EVERY == 0 or done == total:
            print(_progress_bar(done, total), flush=True)

        time.sleep(TEMPO_ENTRE_REQS)

    return out_items


def _multipass_pipeline(
    *,
    file_path: Path,
    src_texts: List[str],
    model: str,
    cache: dict,
    progress: dict,
    save_cache_fn,
    save_prog_fn,
    mode: str,
) -> List[str]:
    """
    enabled:
      T1 (traduz) -> R1 (revisa) -> T2 (refino com SRC+PT) -> R2 (revisa)
    enabled_plus:
      enabled + GR (revisão global extra)
    """
    mode_n = normalize_review_mode(mode)
    if not src_texts:
        raise ValueError("A legenda não contém falas para traduzir.")
    if mode_n not in ("enabled", "enabled_plus"):
        return src_texts

    # prompts
    p_translate = (
        "Traduza para PT-BR cada item abaixo.\n"
        "IMPORTANTE:\n"
        "- MANTENHA os marcadores <<<N>>> exatamente.\n"
        "- NÃO mude a ordem.\n"
        "- NÃO adicione itens.\n"
        "- Não invente frases.\n"
        "- Preserve tags/códigos.\n"
        "- Retorne SOMENTE os itens traduzidos com seus marcadores."
    )

    p_review = (
        "Revise a legenda PT-BR abaixo.\n"
        "Objetivo: corrigir erros, ajustar pontuação e naturalidade, mantendo o sentido.\n"
        "IMPORTANTE:\n"
        "- MANTENHA os marcadores <<<N>>>.\n"
        "- NÃO adicione itens.\n"
        "- NÃO invente falas.\n"
        "- Preserve tags/códigos exatamente.\n"
        "- Retorne SOMENTE os itens revisados com seus marcadores."
    )

    p_refine = (
        "Você receberá, para cada item, o TEXTO ORIGINAL (SRC) e a TRADUÇÃO ATUAL (PT).\n"
        "Tarefa: produzir a MELHOR TRADUÇÃO FINAL (PT-BR), fiel ao SRC.\n"
        "IMPORTANTE:\n"
        "- MANTENHA os marcadores <<<N>>>.\n"
        "- NÃO adicione itens.\n"
        "- NÃO invente falas.\n"
        "- Preserve tags/códigos exatamente.\n"
        "- Retorne SOMENTE a tradução final (PT) com seus marcadores.\n"
        "- NÃO repita 'SRC:' ou 'PT:' na resposta."
    )

    p_global = (
        "Revisão GLOBAL final da legenda PT-BR.\n"
        "Objetivo: padronizar termos, nomes e tratamento, e corrigir pequenos deslizes.\n"
        "IMPORTANTE:\n"
        "- MANTENHA os marcadores <<<N>>>.\n"
        "- NÃO adicione itens.\n"
        "- NÃO invente falas.\n"
        "- Preserve tags/códigos exatamente.\n"
        "- Retorne SOMENTE os itens revisados com seus marcadores."
    )

    # define plano de passes
    if mode_n == "enabled":
        pass_total = 4
    else:
        pass_total = 5

    # PASS 1: tradução base (SRC -> PT)
    t1 = _run_pass(
        pass_idx=1,
        pass_total=pass_total,
        pass_name="Tradução (1ª rodada)",
        pass_tag="T1",
        file_path=file_path,
        model=model,
        in_items=src_texts,
        call_fn=lambda m, items: _llm_marked_call(m, items, p_translate),
        cache=cache,
        progress=progress,
        save_cache_fn=save_cache_fn,
        save_prog_fn=save_prog_fn,
    )

    # PASS 2: revisão 1 (PT -> PT revisado)
    r1 = _run_pass(
        pass_idx=2,
        pass_total=pass_total,
        pass_name="Revisão (1ª rodada)",
        pass_tag="R1",
        file_path=file_path,
        model=model,
        in_items=t1,
        call_fn=lambda m, items: _llm_marked_call(m, items, p_review),
        cache=cache,
        progress=progress,
        save_cache_fn=save_cache_fn,
        save_prog_fn=save_prog_fn,
    )

    # PASS 3: refino (SRC + PT -> PT final)
    refine_inputs = [json.dumps({"source": src, "translation": pt}, ensure_ascii=False)
                     for src, pt in zip(src_texts, r1)]
    t2 = _run_pass(
        pass_idx=3,
        pass_total=pass_total,
        pass_name="Tradução (2ª rodada — refino com SRC+PT)",
        pass_tag="T2",
        file_path=file_path,
        model=model,
        in_items=refine_inputs,
        call_fn=lambda m, items: _llm_refine_call(m, items, p_refine),
        cache=cache,
        progress=progress,
        save_cache_fn=save_cache_fn,
        save_prog_fn=save_prog_fn,
    )

    # PASS 4: revisão 2
    r2 = _run_pass(
        pass_idx=4,
        pass_total=pass_total,
        pass_name="Revisão (2ª rodada)",
        pass_tag="R2",
        file_path=file_path,
        model=model,
        in_items=t2,
        call_fn=lambda m, items: _llm_marked_call(m, items, p_review),
        cache=cache,
        progress=progress,
        save_cache_fn=save_cache_fn,
        save_prog_fn=save_prog_fn,
    )

    if mode_n == "enabled_plus":
        # PASS 5: revisão global extra
        rg = _run_pass(
            pass_idx=5,
            pass_total=pass_total,
            pass_name="Revisão GLOBAL extra (final)",
            pass_tag="RG",
            file_path=file_path,
            model=model,
            in_items=r2,
            call_fn=lambda m, items: _llm_marked_call(m, items, p_global),
            cache=cache,
            progress=progress,
            save_cache_fn=save_cache_fn,
            save_prog_fn=save_prog_fn,
        )
        return rg

    return r2

def _is_ptbr_path(p: Path) -> bool:
    n = p.name.lower()
    return bool(re.search(r"\.ptbr(?:_\d+)?\.(?:srt|ass|vtt)$", n))


def _default_out_for(in_path: Path, out_dir: Path) -> Path:
    root = in_path.stem
    if root.lower().endswith(".ptbr"):
        root = root[:-5]
    return out_dir / f"{root}.PTBR{in_path.suffix}"


def _iter_inputs(paths: List[str]) -> List[Path]:
    out: List[Path] = []
    for raw in paths:
        p = Path(raw).expanduser().resolve()
        if p.is_dir():
            for f in p.rglob("*"):
                if f.is_file() and f.suffix.lower() in SUB_EXTS:
                    out.append(f)
        else:
            if p.is_file() and p.suffix.lower() in SUB_EXTS:
                out.append(p)

    seen = set()
    uniq = []
    for p in out:
        sp = str(p)
        if sp not in seen:
            uniq.append(p)
            seen.add(sp)
    return uniq


def translate_srt(in_path: Path, out_path: Path, model: str, cache: dict, progress: dict, checkpoint=None) -> None:
    if _is_translategemma(model):
        return _translate_context_document(in_path, out_path, model, cache, progress, checkpoint)
    blocks = parse_srt(_read_text(in_path))
    total = len(blocks)

    if not blocks:
        raise ValueError("A legenda SRT não contém blocos de fala válidos.")
    file_key = _cache_context(in_path, model, [text for _, _, text in blocks], "srt")
    start_at = sum(_item_cache_key(file_key, i) in cache for i in range(total))

    print(f"Blocos: {total} | Retomar: {start_at}/{total}")

    i = 0
    done = 0

    while i < total:
        batch_indices = []
        batch_texts = []
        while i < total and len(batch_texts) < BLOCOS_POR_REQUISICAO:
            idx, ts, txt = blocks[i]
            ckey = _item_cache_key(file_key, i)
            if ckey in cache:
                blocks[i] = (idx, ts, cache[ckey])
                progress[file_key] = i + 1
                i += 1
                done += 1
                if done % PROGRESS_EVERY == 0 or done == total:
                    print(_progress_bar(done, total), flush=True)
                continue
            batch_indices.append(i)
            batch_texts.append(txt)
            i += 1

        if not batch_texts:
            continue

        translated_list = _translate_with_retries(model, batch_texts)

        for k, tr in enumerate(translated_list):
            bi = batch_indices[k]
            idx, ts, txt = blocks[bi]
            ckey = _item_cache_key(file_key, bi)
            cache[ckey] = tr
            blocks[bi] = (idx, ts, tr)
            progress[file_key] = bi + 1
            done = max(done, bi + 1)

        if checkpoint:
            checkpoint()
        if done % PROGRESS_EVERY == 0 or done == total:
            print(_progress_bar(done, total), flush=True)

        time.sleep(TEMPO_ENTRE_REQS)

    _write_text(out_path, build_srt(blocks))


def translate_vtt(in_path: Path, out_path: Path, model: str, cache: dict, progress: dict, checkpoint=None) -> None:
    if _is_translategemma(model):
        return _translate_context_document(in_path, out_path, model, cache, progress, checkpoint)
    header, cues = parse_vtt(_read_text(in_path))
    total = len(cues)

    if not cues:
        raise ValueError("A legenda VTT não contém blocos de fala válidos.")
    file_key = _cache_context(in_path, model, [text for _, text in cues], "vtt")
    start_at = sum(_item_cache_key(file_key, i) in cache for i in range(total))

    print(f"Cues: {total} | Retomar: {start_at}/{total}")

    i = 0
    done = 0

    while i < total:
        batch_indices = []
        batch_texts = []
        while i < total and len(batch_texts) < BLOCOS_POR_REQUISICAO:
            ts, txt = cues[i]
            ckey = _item_cache_key(file_key, i)
            if ckey in cache:
                cues[i] = (ts, cache[ckey])
                progress[file_key] = i + 1
                i += 1
                done += 1
                if done % PROGRESS_EVERY == 0 or done == total:
                    print(_progress_bar(done, total), flush=True)
                continue
            batch_indices.append(i)
            batch_texts.append(txt)
            i += 1

        if not batch_texts:
            continue

        translated_list = _translate_with_retries(model, batch_texts)
        for k, tr in enumerate(translated_list):
            bi = batch_indices[k]
            ts, txt = cues[bi]
            ckey = _item_cache_key(file_key, bi)
            cache[ckey] = tr
            cues[bi] = (ts, tr)
            progress[file_key] = bi + 1
            done = max(done, bi + 1)

        if checkpoint:
            checkpoint()
        if done % PROGRESS_EVERY == 0 or done == total:
            print(_progress_bar(done, total), flush=True)

        time.sleep(TEMPO_ENTRE_REQS)

    _write_text(out_path, build_vtt(header, cues))


def translate_ass(in_path: Path, out_path: Path, model: str, cache: dict, progress: dict, checkpoint=None) -> None:
    if _is_translategemma(model):
        return _translate_context_document(in_path, out_path, model, cache, progress, checkpoint)
    header, dialogues = parse_ass(_read_text(in_path))
    total = len(dialogues)

    if not dialogues:
        raise ValueError("A legenda ASS não contém diálogos válidos.")
    file_key = _cache_context(in_path, model, [text for _, text in dialogues], "ass")
    start_at = sum(_item_cache_key(file_key, i) in cache for i in range(total))

    print(f"Dialogues: {total} | Retomar: {start_at}/{total}")

    i = 0
    done = 0

    while i < total:
        batch_indices = []
        batch_texts = []
        while i < total and len(batch_texts) < BLOCOS_POR_REQUISICAO:
            prefix, txt = dialogues[i]
            ckey = _item_cache_key(file_key, i)
            if ckey in cache:
                dialogues[i] = (prefix, cache[ckey])
                progress[file_key] = i + 1
                i += 1
                done += 1
                if done % PROGRESS_EVERY == 0 or done == total:
                    print(_progress_bar(done, total), flush=True)
                continue
            batch_indices.append(i)
            batch_texts.append(txt)
            i += 1

        if not batch_texts:
            continue

        translated_list = _translate_with_retries(model, batch_texts)
        for k, tr in enumerate(translated_list):
            bi = batch_indices[k]
            prefix, txt = dialogues[bi]
            ckey = _item_cache_key(file_key, bi)
            cache[ckey] = tr
            dialogues[bi] = (prefix, tr)
            progress[file_key] = bi + 1
            done = max(done, bi + 1)

        if checkpoint:
            checkpoint()
        if done % PROGRESS_EVERY == 0 or done == total:
            print(_progress_bar(done, total), flush=True)

        time.sleep(TEMPO_ENTRE_REQS)

    _write_text(out_path, build_ass(header, dialogues))



def translate_srt_multipass(in_path: Path, out_path: Path, model: str, cache: dict, progress: dict, save_cache_fn, save_prog_fn, mode: str) -> None:
    blocks = parse_srt(_read_text(in_path))
    src_texts = [txt for _, _, txt in blocks]
    final_texts = _multipass_pipeline(
        file_path=in_path,
        src_texts=src_texts,
        model=model,
        cache=cache,
        progress=progress,
        save_cache_fn=save_cache_fn,
        save_prog_fn=save_prog_fn,
        mode=mode,
    )
    # aplica
    new_blocks = []
    for (idx, ts, _), txt in zip(blocks, final_texts):
        new_blocks.append((idx, ts, txt))
    _write_text(out_path, build_srt(new_blocks))


def translate_vtt_multipass(in_path: Path, out_path: Path, model: str, cache: dict, progress: dict, save_cache_fn, save_prog_fn, mode: str) -> None:
    header, cues = parse_vtt(_read_text(in_path))
    src_texts = [txt for _, txt in cues]
    final_texts = _multipass_pipeline(
        file_path=in_path,
        src_texts=src_texts,
        model=model,
        cache=cache,
        progress=progress,
        save_cache_fn=save_cache_fn,
        save_prog_fn=save_prog_fn,
        mode=mode,
    )
    new_cues = []
    for (ts, _), txt in zip(cues, final_texts):
        new_cues.append((ts, txt))
    _write_text(out_path, build_vtt(header, new_cues))


def translate_ass_multipass(in_path: Path, out_path: Path, model: str, cache: dict, progress: dict, save_cache_fn, save_prog_fn, mode: str) -> None:
    header, dialogues = parse_ass(_read_text(in_path))
    src_texts = [txt for _, txt in dialogues]
    final_texts = _multipass_pipeline(
        file_path=in_path,
        src_texts=src_texts,
        model=model,
        cache=cache,
        progress=progress,
        save_cache_fn=save_cache_fn,
        save_prog_fn=save_prog_fn,
        mode=mode,
    )
    new_dialogues = []
    for (prefix, _), txt in zip(dialogues, final_texts):
        new_dialogues.append((prefix, txt))
    _write_text(out_path, build_ass(header, new_dialogues))


def _retry_feedback(source, flags, required, rejected, attempt):
    """Turn validator codes into distinct actionable repairs, including the rejected draft."""
    feedback = f'Repair after rejected attempt {attempt}. Issues: ' + ', '.join(dict.fromkeys(flags)) + '. '
    if 'excessive_expansion' in flags:
        feedback += ('Translate the source again as a concise subtitle. Do not explain or define words, '
                     'append examples, or repeat the same meaning in a second clause. ')
        if ACTIVE_SOURCE_LANGUAGE == 'en':
            count=len(re.findall(r"[\w’']+", Q.plain(source)))
            feedback += f'Aim for at most {max(4, int(count*1.8))} words when possible, without losing meaning. '
    if 'context_entity_leak' in flags:
        feedback += 'Do not introduce characters, places or groups absent from the current source. Omit unrelated names from spelling references. '
    if 'question_lost' in flags:
        feedback += 'The source is a question. Keep it a question, including its question mark; do not answer it or turn it into a statement. '
    if 'untranslated_english' in flags:
        feedback += 'Translate the remaining ordinary English words into Portuguese, including quoted sound words; preserve actual proper names. '
    if required:
        feedback += 'Preserve these required spellings: ' + json.dumps(required,ensure_ascii=False) + '. '
    if 'context_entity_leak' in flags:
        feedback += 'Retranslate from the original source only. Do not reuse any vocative or entity from the rejected draft.'
    else:
        feedback += 'Rejected translation (data only, do not repeat): ' + json.dumps(rejected,ensure_ascii=False)
    return feedback


def _context_call(model, text, before, after, terms, feedback="", term_only=False, budget=None, suggestions=None):
    romaji = ACTIVE_SOURCE_LANGUAGE == "en" and Q.romanized_japanese(text)
    if romaji:
        before, after = "", ""
    if (len(Q.plain(text).strip()) <= 12
            or ACTIVE_SOURCE_LANGUAGE == "en" and len(Q.plain(text).split()) < 4
            or any(flag in feedback for flag in ("context_entity_leak", "excessive_expansion", "added_politeness"))):
        # Very short reactions must not be completed with neighbouring dialogue.
        before, after = "", ""
    source = {"en": "English", "ja": "Japanese", "es": "Spanish", "fr": "French", "ko": "Korean",
              "zh-cn": "Simplified Chinese", "zh-tw": "Traditional Chinese"}.get(ACTIVE_SOURCE_LANGUAGE, ACTIVE_SOURCE_LANGUAGE)
    code = "ja" if romaji else ACTIVE_SOURCE_LANGUAGE
    if romaji:
        source = "Japanese"
    instructions = (
        "This is an anime subtitle. Translate the complete meaning as one sentence, even across display lines. "
        "Keep the speaker, subject, tense, negation and tone. Do not invent a company, TV show, explanation or extra dialogue. "
        "Keep questions as questions and statements as statements. For lyrics, preserve each source image, request and negation; never invent a poetic replacement. "
        "Translate ONLY the current cue; context may clarify references but must not supply extra clauses or repeat the following cue. "
        "Use consistent equivalents for repeated expressions. Preserve the setup and literal object of a joke rather than replacing it with an unrelated idiom. "
        "Preserve actual character names. Capitalization alone does not make a name: translate ordinary verbs, nouns and words in titles normally. "
        "Use natural concise Brazilian Portuguese. Do not infer gender from a name alone; omit gendered articles when unknown. Never output gender alternatives such as obrigado(a); "
        "if gender is unknown, use a natural neutral construction. Do not add quotation marks. "
    )
    if ACTIVE_PROJECT_STYLE:
        from season_tools import style_prompt
        instructions += style_prompt(ACTIVE_PROJECT_STYLE)
    if ACTIVE_SOURCE_LANGUAGE == "en":
        if re.search(r"\bPeeping Tom\b",text,re.I):instructions += " Peeping Tom describes someone spying on another person's intimacy. In colloquial dialogue use tarado (adapt gender if established), not observador secreto; keep repeated accusations consistent unless an explicit glossary overrides this choice. "
        if re.search(r"\bMaster\b", text): instructions += " Master can address a teacher, an employer, or a household heir: infer the role from the source and context. Young Master as a household address means jovem senhor, not a teacher or a martial-arts mestre. "
        if re.search(r"\bBig Brother\b", text): instructions += " Big Brother addresses an older male sibling: irmão, never a TV show or a female sibling. "
        if re.search(r"\bBig Sister\b", text): instructions += " Big Sister addresses an older female sibling: irmã. "
        if re.search(r"\byour old man\b", text, re.I): instructions += " Preserve YOUR: the listener's father (seu pai), not the speaker's boss. "
    if Q.SENTINEL.search(text):
        instructions += " Copy these exact formatting markers once, in order: " + ", ".join(m.group() for m in Q.SENTINEL.finditer(text)) + ". "
    if "\n" in text:
        instructions += " Keep the same number of separate speaker or caption lines and any existing initial dashes. Never invent dashes. "
    if term_only:
        instructions += "Translate only this recurring title/term consistently; preserve any character names. "
    if ACTIVE_SOURCE_LANGUAGE == "ja":
        instructions += " Keep interjections as interjections, without explaining their meaning in parentheses. Preserve the polarity and intent of wishes and commands: do not soften a hostile wish into a friendly warning or add a negation. "
    if ACTIVE_SOURCE_LANGUAGE == "ja" and re.search(r"(?:^|\n)[（(][^）)\n]{1,40}[）)]",text):
        instructions += " Parenthesized speaker names and sound-effect captions are annotations. Keep them as annotations; never turn them into extra spoken dialogue. "
    context = ""
    if before or after:
        context = ("\nBackground for disambiguation ONLY; never translate or quote this background:\n"
                   + json.dumps({"previous": before[-1000:], "following": after[:1000]}, ensure_ascii=False) + "\n")
    glossary = "" if romaji else GLOSSARY.prompt([text])
    if glossary:
        glossary = "\nTerminology guidance: adapt grammar to this sentence, without adding information. " + glossary
    if terms:
        glossary += "\nRequired series terminology (use these spellings, not synonyms):\n" + json.dumps(terms, ensure_ascii=False)
    if suggestions:
        glossary += ("\nUnconfirmed translation suggestions: use only when they fit the context; "
                     "adapt grammar and do not preserve ordinary English words as names.\n"
                     + json.dumps(suggestions, ensure_ascii=False))
    if ACTIVE_SERIES_HINTS and not any(flag in feedback for flag in ("excessive_expansion", "context_entity_leak")):
        glossary += ('\nConfirmed spelling reference for this series ONLY. Use a spelling only when the source refers to that entity. '
                     'Never add a character, event, explanation or missing words from this reference:\n'
                     + json.dumps(ACTIVE_SERIES_HINTS,ensure_ascii=False))
    if budget:
        instructions += f" Aim for about {budget} visible characters when possible without dropping meaning. "
    if romaji:
        instructions += (" This source is a Japanese lyric written in Latin letters. "
                         "Translate the lyric itself; never explain what its words mean. "
                         "Original romanization for disambiguation: " + json.dumps(text,ensure_ascii=False) + ". ")
    request_text = Q.japanese_input(text,protected=terms) if romaji else text
    prompt = (f"You are a professional {source} ({code}) to Brazilian Portuguese (pt-BR) translator. "
              + instructions + context + glossary + ("\nCorrect these issues from the previous attempt: " + feedback if feedback else "")
              + f"\nProduce only the Brazilian Portuguese translation. Please translate the following {source} text into Brazilian Portuguese:\n\n\n{request_text}")
    state = CONTEXT_REQUEST_STATE.get()
    request_key = (model, prompt, json.dumps(OLLAMA_OPTIONS,sort_keys=True),
                   os.environ.get("SUBFORGEAI_OLLAMA_BASE_URL", "http://127.0.0.1:11434"))
    # Reuse only identical requests within this document. Feedback retries
    # always reach the model; each cue still runs the full validation below.
    if state is not None and not feedback and request_key in state["cache"]:
        state["hits"] += 1
        return state["cache"][request_key]
    if state is not None:state["calls"] += 1
    result = _ollama_call(model, [{"role": "user", "content": prompt}]).strip()
    if not result or MARKER_RE.search(result) or _has_prompt_scaffolding(result):
        raise InvalidModelOutput("Resposta contextual vazia ou com campos de instrução.")
    if re.search(r"(?im)^\s*(?:previous|following|background|translation|tradução|contexto)\s*:", result):
        raise InvalidModelOutput("O modelo incluiu contexto/instruções na tradução.")
    if state is not None and not feedback and len(state["cache"]) < 512:
        state["cache"][request_key] = result
    return result


def _translate_context_document(in_path, out_path, model, cache, progress, checkpoint=None):
    token=CONTEXT_REQUEST_STATE.set({"cache":{},"hits":0,"calls":0})
    try:
        return _translate_context_document_impl(in_path,out_path,model,cache,progress,checkpoint)
    finally:
        CONTEXT_REQUEST_STATE.reset(token)


def _translate_context_document_impl(in_path, out_path, model, cache, progress, checkpoint=None):
    global ACTIVE_SERIES_HINTS, ACTIVE_PROJECT_STYLE
    ext = in_path.suffix.lower()
    if ext == ".srt":
        records = parse_srt(_read_text(in_path)); header = None
        texts = [record[2] for record in records]
        times = [record[1] for record in records]
    elif ext == ".vtt":
        header, records = parse_vtt(_read_text(in_path)); texts = [r[1] for r in records]; times = [r[0] for r in records]
    else:
        header, records = parse_ass(_read_text(in_path)); texts = [r[1] for r in records]
        # ASS uses the actual declared Format column order.
        fields = []
        raw = _read_text(in_path)
        in_events = False
        for line in raw.splitlines():
            if line.startswith("["): in_events = line.strip().casefold() == "[events]"
            if in_events and line.lower().startswith("format:"):
                fields = [part.strip().lower() for part in line.split(":", 1)[1].split(",")]; break
        times = []
        for prefix, _ in records:
            parts = prefix.split(":", 1)[-1].split(",")
            try: times.append(parts[fields.index("start")] + " --> " + parts[fields.index("end")])
            except (ValueError, IndexError): times.append("")
    if not texts:
        raise ValueError("A legenda não contém falas válidas.")
    series = Q.SeriesTerms(in_path, texts, out_path.parent / "_cache_traducao", ACTIVE_SOURCE_LANGUAGE)
    ACTIVE_SERIES_HINTS = dict(list(series.explicit.items())[:80])
    ACTIVE_PROJECT_STYLE = series.style
    width=series.style.get("line_width",42);cps=series.style.get("max_cps",20)
    for term in series.candidates:
        if term in series.values or all(word.casefold() in {n.casefold() for n in series.names}
                                        for word in re.findall(r"[A-Z][a-z]+", term)):
            continue
        try:
            target = _context_call(model, term, "", "", {}, term_only=True).strip('"“” .!?…')
            if Q.FORMAT.search(target) or len(target) > max(120, len(term)*4):
                raise InvalidModelOutput("Termo automático inválido.")
            series.values[term] = target
        except InvalidModelOutput:
            # A suggestion is optional; never silently cache invalid terminology.
            print(f"[WARN] Termo automático precisa de revisão: {term}", flush=True)
    _save_json(series.path, series.values)
    settings = [Q.VERSION, ACTIVE_SOURCE_LANGUAGE, series.fingerprint(), f"width={width},cps={cps}", "season-safe-v1"]
    base_key = _cache_context(in_path, model, texts, ext)
    file_key = base_key + ":season-safe:" + _hash_key(json.dumps(settings))
    legacy = {}
    for old_key, value in cache.items():
        if old_key.startswith(base_key + ":") and ":season-safe:" not in old_key:
            suffix = old_key[len(base_key)+1:].split(":")
            if len(suffix) == 2 and len(suffix[0]) == 40 and suffix[1].isdigit() and isinstance(value, str):
                legacy[int(suffix[1])] = value
        elif old_key.startswith(base_key+":season-safe:") and not old_key.startswith(file_key+":"):
            suffix=old_key[len(base_key)+len(":season-safe:"):].split(":")
            if len(suffix)==2 and len(suffix[0])==40 and suffix[1].isdigit() and isinstance(value,str):
                legacy[int(suffix[1])]=value
    final, findings = [], []
    visible_texts = [Q.plain(text) for text in texts]
    def hard_flags(original, target, seconds, required):
        flags = [f for f in Q.quality_flags(original, target, seconds, required, ACTIVE_SOURCE_LANGUAGE,width=width,cps=cps)
                 if f in ("terminology","excessive_expansion")]
        markup = lambda text: [m.group() for m in Q.FORMAT.finditer(text) if m.group() not in ("\n", "\r\n", r"\N", r"\n")]
        if markup(original) != markup(target): flags.append("format_mismatch")
        if Q.semantic_breaks(original):
            breaks=lambda text:len(re.findall(r"\r?\n|\\N|\\n",text))
            if breaks(original)!=breaks(target):flags.append("speaker_boundary")
        return flags
    def critical_flags(original, target, seconds, required):
        flags = Q.quality_flags(original, target, seconds, required, ACTIVE_SOURCE_LANGUAGE,width=width,cps=cps)
        flags += Q.context_flags(original, target, series.explicit)
        if ACTIVE_SOURCE_LANGUAGE=='en' and _has_english_residual(original,target):flags.append('untranslated_english')
        return list(dict.fromkeys(hard_flags(original, target, seconds, required) +
                    [f for f in flags if f not in ("long_line", "reading_speed", "too_many_lines", "added_politeness")]))
    migrated = 0
    for index, previous in (legacy.items() if not series.style else ()):
        if index >= len(texts): continue
        if Q.romanized_japanese(texts[index]): continue
        key = _item_cache_key(file_key, index)
        required = series.relevant(Q.plain(texts[index]))
        if key not in cache and previous.strip() and not _has_prompt_scaffolding(previous):
            if not critical_flags(texts[index], previous, Q.duration(times[index]), required):
                if not (ACTIVE_SOURCE_LANGUAGE == "en" and _has_english_residual(texts[index], previous)):
                    cache[key] = previous
                    migrated += 1
    if migrated:
        if checkpoint: checkpoint()
        print(f"[INFO] Checkpoints anteriores recuperados e validados: {migrated} bloco(s).", flush=True)
    resumed = sum(_item_cache_key(file_key, i) in cache for i in range(len(texts)))
    print(f"[INFO] Tradução com contexto | termos confirmados: {len(series.explicit)} | sugestões automáticas: {len(series.values)-len(series.explicit)} | Retomar: {resumed}/{len(texts)}", flush=True)
    if resumed:
        print(_progress_bar(resumed, len(texts)), flush=True)
    for index, original in enumerate(texts):
        key = _item_cache_key(file_key, index)
        required = series.relevant(Q.plain(original))
        suggested = series.suggestions(Q.plain(original))
        romaji = ACTIVE_SOURCE_LANGUAGE == "en" and Q.romanized_japanese(original)
        seconds = Q.duration(times[index])
        before = " ".join(visible_texts[max(0, index-2):index])
        after = " ".join(visible_texts[index+1:index+3])
        from speech_context import uncertain_cue
        uncertain = uncertain_cue(times[index],series.provenance)
        if uncertain:before,after='',''
        for term,target in Q.contextual_address_terms(original,before,after).items():
            if not any(Q.normalized(key)==Q.normalized(term) for key in (*required,*GLOSSARY.terms())):
                required[term]=target
        approved = series.memory_for(original)
        if approved is not None:
            cache[key] = Q.render_memory(original, approved, ass=ext==".ass")
            if romaji: cache[key+"#source_language"] = "ja-Latn-kana-v2-context"
        if key in cache and (critical_flags(original, cache[key], seconds, required)
                             or romaji and cache.get(key+"#source_language") != "ja-Latn-kana-v2-context"):
            print(f"[INFO] Reavaliando qualidade do bloco {index+1} salvo no cache.", flush=True)
            del cache[key]
        if key in cache:
            translated = cache[key]
        else:
            safe, tokens, prefix, suffix = Q.prepare(original)
            if ext == ".ass" and re.search(r"\{[^}]*\\p[1-9]", original):
                translated = original
            elif not re.search(r"[^\W\d_]", safe):
                translated = Q.restore(safe, tokens, prefix, suffix)
            elif Q.terms_only(safe,series.explicit) is not None:
                translated = Q.restore(Q.terms_only(safe,series.explicit),tokens,prefix,suffix)
            elif ACTIVE_SOURCE_LANGUAGE == 'en' and Q.preview_heading(safe,series.explicit) is not None:
                translated = Q.restore(Q.preview_heading(safe,series.explicit),tokens,prefix,suffix)
            elif any(re.fullmatch(re.escape(name) + r"[!?.,…]*", Q.plain(original), re.I) for name in series.explicit):
                # A character's name alone is not an invitation to complete the next line.
                name = next(n for n in series.explicit if re.fullmatch(re.escape(n) + r"[!?.,…]*", Q.plain(original), re.I))
                punctuation = Q.plain(original)[len(name):]
                translated = Q.restore(series.values[name] + punctuation, tokens, prefix, suffix)
            else:
                feedback, translated = "", None
                last_candidate = ""
                for attempt in range(MAX_RETRIES):
                    try:
                        candidate = _context_call(model, Q.request_text(safe, tokens), before, after, required, feedback,
                                                  budget=max(15, int(seconds*cps)) if seconds else None, suggestions=suggested)
                        try:
                            candidate = Q.restore(candidate, tokens, prefix, suffix)
                        except ValueError:
                            candidate = Q.align_inline(original, candidate,
                                lambda span: _context_call(model, span, Q.plain(original), "", series.relevant(span), term_only=True))
                        last_candidate = candidate
                        critical = critical_flags(original, candidate, seconds, required)
                        if ACTIVE_SOURCE_LANGUAGE == "en" and _has_english_residual(original, candidate) and not required:
                            critical.append("untranslated_english")
                        if critical:
                            feedback = _retry_feedback(original, critical, required, candidate, attempt+1)
                            raise InvalidModelOutput(feedback)
                        translated = candidate
                        break
                    except (InvalidModelOutput, ValueError, OllamaTransientError) as exc:
                        feedback = str(exc)
                        print(f"[WARN] Bloco {index+1}: nova tentativa ({attempt+1}/{MAX_RETRIES}): {exc}", flush=True)
                        if attempt+1 == MAX_RETRIES:
                            _save_json(Path(str(out_path)+'.review_required.json'),
                                {'status':'blocked','source':str(in_path),'block':index+1,'input':original,
                                 'reason':feedback,'attempts':MAX_RETRIES,'checkpoint_preserved':True,
                                 'source_sha256':hashlib.sha256(in_path.read_bytes()).hexdigest(),
                                 'partial_translations':[{'index':i,'time':times[i],'source':texts[i],'translation':value} for i,value in enumerate(final)],
                                 'rejected_candidate':last_candidate})
                            print(f"[REVIEW] Bloco {index+1} não validado. Revise a entrada; detalhes: {out_path}.review_required.json",flush=True)
                            raise
                if translated is None: raise InvalidModelOutput("Não foi possível validar a fala.")
                if normalize_review_mode(REVIEW_MODE) != "disabled" and seconds and "reading_speed" in Q.quality_flags(original, translated, seconds, required, ACTIVE_SOURCE_LANGUAGE,width=width,cps=cps):
                    try:
                        shorter = _context_call(model, Q.request_text(safe, tokens), before, after, required,
                            feedback="Make the subtitle more concise while preserving ALL facts, names, speaker, tense and negation. Never summarize away information.",
                            budget=max(15, int(seconds*cps)), suggestions=suggested)
                        shorter = Q.restore(shorter, tokens, prefix, suffix)
                        critical = critical_flags(original, shorter, seconds, required)
                        if not critical and len(Q.plain(shorter)) < len(Q.plain(translated)):
                            translated = shorter
                    except (InvalidModelOutput, ValueError, OllamaTransientError):
                        # Keep the validated complete translation and flag it for review.
                        pass
            translated = Q.reflow(translated, ass=ext == ".ass",width=width)
            cache[key] = translated
            if romaji: cache[key+"#source_language"] = "ja-Latn-kana-v2-context"
            progress[file_key] = index+1
            if checkpoint: checkpoint()
        final.append(translated)
        progress[file_key] = index+1
        flags = Q.quality_flags(original, translated, seconds, required, ACTIVE_SOURCE_LANGUAGE,width=width,cps=cps)
        if uncertain:flags.append('ocr_uncertain' if series.provenance.get('source_kind') == 'ocr' else 'asr_disagreement')
        if series.provenance and len(re.sub(r'\W+','',Q.plain(original)))<=2:flags.append('source_fragment')
        if romaji:
            flags.append("romanized_source")
            if Q.romanized_japanese(translated): flags.append("untranslated_romaji")
        if any(not Q.term_present(translated, value) for value in suggested.values()):
            flags.append("suggested_terminology")
        if ACTIVE_SOURCE_LANGUAGE == "en" and _has_english_residual(original, translated):
            flags.append("untranslated_english")
        if flags:
            findings.append({"block": index+1, "time": times[index], "flags": flags,
                             "source": original, "translation": translated})
        if index+1 >= resumed and ((index+1) % PROGRESS_EVERY == 0 or index+1 == len(texts)):
            print(_progress_bar(index+1, len(texts)), flush=True)
    if ext == ".srt": document = build_srt([(r[0], r[1], text) for r, text in zip(records, final)])
    elif ext == ".vtt": document = build_vtt(header, [(r[0], text) for r, text in zip(records, final)])
    else: document = build_ass(header, [(r[0], text) for r, text in zip(records, final)])
    _write_text(out_path, document)
    report = out_path.with_suffix(out_path.suffix + ".quality.json")
    _save_json(report, {"version": Q.VERSION, "source": str(in_path), "blocks": len(final),
                        "series_terms": str(series.path), "needs_review": len(findings), "findings": findings,
                        "confirmed_terms": series.explicit, "automatic_terms_are_suggestions": True,
                        "source_provenance": series.provenance,"project_style":series.style,
                        "request_reuse": {key:CONTEXT_REQUEST_STATE.get()[key] for key in ("hits","calls")},
                        "timestamps_changed": False, "human_review_required": True})
    print(f"[INFO] Revisão de qualidade: {len(findings)} bloco(s) sinalizados. Relatório: {report}", flush=True)
    if checkpoint: checkpoint()


class TranslationBatchError(RuntimeError):
    def __init__(self, outputs: List[Path], failures: list[tuple[Path, str]]):
        self.outputs = outputs
        self.failures = failures
        super().__init__(f"{len(failures)} arquivo(s) falharam; {len(outputs)} concluído(s).")


def translate_paths(
    inputs: List[Path],
    out_dir: Path,
    model: Optional[str] = None,
    force: bool = False,
    allow_ptbr_input: bool = False,
    keep_cache: bool = True,
    clean_cache: bool = False,
    overwrite: bool = False,
) -> List[Path]:
    with directory_lock(out_dir):
        return _translate_paths_locked(
            inputs, out_dir, model, force, allow_ptbr_input, keep_cache, clean_cache, overwrite
        )


def _translate_paths_locked(inputs, out_dir, model, force, allow_ptbr_input,
                            keep_cache, clean_cache, overwrite=False) -> List[Path]:
    global ACTIVE_SOURCE_LANGUAGE
    out_dir.mkdir(parents=True, exist_ok=True)
    mdl = model or MODELO_OLLAMA
    mode_norm = normalize_review_mode(globals().get("REVIEW_MODE") or "auto")
    if _is_translategemma(mdl) and mode_norm not in ("disabled", "auto"):
        print("[INFO] TranslateGemma: usando tradução direta e validação; revisão multipass legada desativada.", flush=True)
        mode_norm = "auto"

    cache_dir = out_dir / "_cache_traducao"
    cache_json = cache_dir / "cache.json"
    prog_json = cache_dir / "progress.json"
    cache_dir.mkdir(parents=True, exist_ok=True)

    cache = _load_json(cache_json)
    progress = _load_json(prog_json)

    outputs: List[Path] = []
    failures: list[tuple[Path, str]] = []

    def checkpoint():
        _save_json(cache_json, cache)
        _save_json(prog_json, progress)

    for in_path in inputs:
        if (not allow_ptbr_input) and _is_ptbr_path(in_path):
            print(f"[SKIP] Já é PTBR: {in_path.name}")
            continue

        if force:
            prefix = _cache_prefix(in_path)
            for mapping in (cache, progress):
                for key in list(mapping):
                    if key.startswith(prefix):
                        del mapping[key]
            checkpoint()

        print("\n" + "=" * 60)
        print(f"📄 Traduzindo: {in_path.name}")
        print(f"Modelo: {mdl} | Batch: {BLOCOS_POR_REQUISICAO} | Review: {mode_norm}")

        try:
            if _is_translategemma(mdl):
                ACTIVE_SOURCE_LANGUAGE = _detect_source_language(_read_text(in_path))
                print(f"[INFO] TranslateGemma: {ACTIVE_SOURCE_LANGUAGE} → pt-BR | contexto 4096 | validação de estrutura", flush=True)
            with reserve_output(_default_out_for(in_path, out_dir), replace=overwrite) as out_path:
                ext = in_path.suffix.lower()
                if mode_norm in ("enabled", "enabled_plus"):
                    translate = {".srt": translate_srt_multipass, ".vtt": translate_vtt_multipass,
                                 ".ass": translate_ass_multipass}.get(ext)
                    if translate is None:
                        raise ValueError(f"Extensão não suportada: {ext}")
                    translate(in_path, out_path, mdl, cache, progress,
                              lambda: _save_json(cache_json, cache),
                              lambda: _save_json(prog_json, progress), mode_norm)
                else:
                    translate = {".srt": translate_srt, ".vtt": translate_vtt,
                                 ".ass": translate_ass}.get(ext)
                    if translate is None:
                        raise ValueError(f"Extensão não suportada: {ext}")
                    translate(in_path, out_path, mdl, cache, progress, checkpoint=checkpoint)
                checkpoint()

            print(f"✅ Salvo: {out_path}")
            outputs.append(out_path)
            print("[RESULT] " + json.dumps({"kind": "translation", "input": str(in_path.resolve()),
                                           "output": str(out_path.resolve())}, ensure_ascii=False), flush=True)

        except Exception as e:
            failures.append((in_path, f"{type(e).__name__}: {e}"))
            print(f"[ERRO] Falhou em {in_path.name}: {e}")

    if failures:
        print(f"[WARN] Progresso preservado em: {cache_dir}")
        print("[WARN] Reexecute o mesmo comando para retomar somente o que faltou.")
        raise TranslationBatchError(outputs, failures)

    print(f"\n[OK] Concluídos: {len(outputs)} arquivo(s). Saída: {out_dir}")

    # O cache NÃO é mais apagado automaticamente.
    # Apagá-lo destruía a retomada de um lote parcial numa execução futura e
    # tornava o --force inútil (não havia cache a invalidar). Com --clean-cache
    # o comportamento antigo continua disponível.
    if clean_cache:
        cache_json.unlink(missing_ok=True)
        prog_json.unlink(missing_ok=True)
        try:
            cache_dir.rmdir()
        except OSError:
            pass
        print("[CLEAN] Cache apagado.")
    else:
        print(f"[INFO] Cache mantido para retomada: {cache_dir}")

    return outputs


def main_cli() -> int:
    global GLOSSARY, SOURCE_LANGUAGE
    parser = argparse.ArgumentParser(description="SubForgeAI - Ollama (traduz legenda)")
    parser.add_argument("inputs", nargs="*", help="Arquivo(s) .srt/.ass/.vtt OU pasta(s)")
    parser.add_argument("--outdir", default=str(DEFAULT_OUTDIR), help="Pasta de saída")
    parser.add_argument("--model", default=None, help="Modelo do Ollama (ex: translategemma:12b)")
    parser.add_argument("--source-lang", default="auto", help="Idioma de origem: auto, en, ja, es, fr etc.")
    parser.add_argument("--glossary", default=None, help="Arquivo JSON de termos; padrão: glossary.json do aplicativo")
    parser.add_argument("--force", action="store_true", help="Força retradução (ignora cache desta legenda)")
    parser.add_argument("--allow-ptbr", action="store_true", help="Permite traduzir arquivos já PTBR")
    parser.add_argument("--keep-cache", action="store_true", help="(padrão) mantém o cache para retomada")
    parser.add_argument("--clean-cache", action="store_true", help="Apaga o cache ao concluir com sucesso")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Sobrescreve a saída existente (padrão: cria Nome_2, Nome_3...)",
    )
    parser.add_argument("--batch", type=int, default=BLOCOS_POR_REQUISICAO, help="Tamanho do batch")
    parser.add_argument("--progress-every", type=int, default=PROGRESS_EVERY, help="Imprime progresso a cada N linhas")
    parser.add_argument(
        "--review",
        default=REVIEW_MODE,
        help="Revisão: disabled|auto|enabled|enabled_plus (compat: off|always|on|on_plus)",
    )
    parser.add_argument("--show-passes", action="store_true", help="Mostra PASS 2/2 quando revisar")
    parser.add_argument("--no-show-passes", action="store_true", help="Não mostra PASS 2/2")
    args = parser.parse_args()
    SOURCE_LANGUAGE = args.source_lang.strip().lower()
    try:
        if args.glossary:
            glossary_path = Path(args.glossary).expanduser().resolve()
            if not glossary_path.is_file():
                raise ValueError(f"Glossário não encontrado: {glossary_path}")
            GLOSSARY = Glossary(glossary_path)
        terms = GLOSSARY.terms()
        if terms:
            print(f"[INFO] Glossário carregado: {GLOSSARY.path} ({len(terms)} termos)")
    except (OSError, ValueError) as exc:
        print(f"[ERRO] Não foi possível carregar o glossário: {exc}")
        return 2

    globals()["BLOCOS_POR_REQUISICAO"] = max(1, int(args.batch))
    globals()["PROGRESS_EVERY"] = max(1, int(args.progress_every))
    globals()["REVIEW_MODE"] = normalize_review_mode(args.review or "auto")

    if args.no_show_passes:
        globals()["SHOW_REVIEW_PASS_LOG"] = False
    elif args.show_passes:
        globals()["SHOW_REVIEW_PASS_LOG"] = True

    if not args.inputs:
        print("[ERRO] Informe arquivos/pastas para traduzir.")
        return 2

    inputs = _iter_inputs(args.inputs)
    if not inputs:
        print("[ERRO] Nenhuma legenda encontrada (.srt/.ass/.vtt).")
        return 2

    out_dir = Path(args.outdir).expanduser().resolve()
    print(f"[OUTDIR] {out_dir}")

    exit_code = 0
    try:
        outs = translate_paths(
            inputs=inputs,
            out_dir=out_dir,
            model=args.model,
            force=args.force,
            allow_ptbr_input=args.allow_ptbr,
            keep_cache=args.keep_cache or not args.clean_cache,
            clean_cache=args.clean_cache,
            overwrite=args.overwrite,
        )
    except TranslationBatchError as exc:
        outs = exc.outputs
        print(f"[ERRO] {exc}")
        exit_code = 1
    except Exception as exc:
        print(f"[ERRO] Não foi possível concluir a tradução: {exc}")
        return 1
    for p in outs:
        try:
            print(f"[OUTFILE] {p}")
        except Exception:
            pass
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main_cli())
