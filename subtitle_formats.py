"""Subtitle text slots: edit dialogue while preserving the surrounding document."""
from __future__ import annotations

import re


class SubtitleTemplate(str):
    def __new__(cls, source: str, slots: list[tuple[int, int]]):
        obj = super().__new__(cls, source)
        obj.slots = slots
        return obj

    def render(self, texts: list[str]) -> str:
        if len(texts) != len(self.slots):
            raise ValueError("A quantidade de falas mudou; a estrutura da legenda foi preservada.")
        chunks, previous = [], 0
        document_crlf = "\r\n" in self
        for (start, end), text in zip(self.slots, texts):
            newline = "\r\n" if "\r\n" in self[start:end] or document_crlf else "\n"
            text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", newline)
            chunks.extend((self[previous:start], text))
            previous = end
        chunks.append(self[previous:])
        return "".join(chunks)


def _iter_vtt_blocks(source: str):
    """Yield (absolute_offset, block_text) for each cue block, CRLF-safe.

    Por que não usar ``re.split`` num separador que inclui ``[ \\t]*``:

        A regex antiga era ``((?:\\r\\n|\\n|\\r)[ \\t]*(?:\\r\\n|\\n|\\r))``.
        Em um arquivo CRLF, a linha em branco entre blocos é ``\\r\\n\\r\\n``.
        O grupo podia casar apenas ``\\r\\n\\r`` e deixar o ``\\n`` restante
        iniciar um "bloco" espúrio. Todo bloco seguinte então entrava em um
        índice ímpar e era descartado como separador; o bloco real caía num
        índice par vazio e o parse abortava com
        "Bloco VTT sem timestamp válido." — ou seja, TODO .vtt salvo no
        Windows era rejeitado.

        Além disso, uma linha em branco DENTRO do texto de uma fala (ex.:
        "A\\n\\nB") era tratada como fim de bloco, e o restante "B" virava um
        bloco sem timestamp — derrubando o arquivo inteiro.

    A regra do WebVTT é explícita: um bloco termina em uma linha em branco,
    e uma linha em branco é uma linha que contém apenas espaços/tabs. Isso é
    o que ``re.splitlines(keepends)`` dá de graça e o que replicamos aqui
    percorrendo linha a linha — sem olhar para frente, sem índice par/ímpar.
    """
    offset = 0
    current: list[str] = []
    for line in source.splitlines(keepends=True):
        if line.strip() == "":
            # Linha em branco: fecha o bloco atual, mas o separador pertence
            # ao documento (não ao slot traduzível).
            if current:
                yield offset - sum(len(part) for part in current), "".join(current)
                current = []
            offset += len(line)
            continue
        current.append(line)
        offset += len(line)
    if current:
        yield offset - sum(len(part) for part in current), "".join(current)


def parse_vtt_document(source: str):
    if not source.lstrip("\ufeff").startswith("WEBVTT"):
        raise ValueError("Cabeçalho WEBVTT não encontrado.")
    slots, cues = [], []
    for offset, block in _iter_vtt_blocks(source):
        lines = block.splitlines(keepends=True)
        if not lines:
            continue
        first = lines[0].strip().lstrip("\ufeff")
        # Cabeçalho e seções especiais não são falas.
        if first == "WEBVTT" or first == "" or first in ("STYLE", "REGION", "NOTE") \
                or first.startswith(("NOTE ", "NOTE\t")):
            continue
        ti = 0 if "-->" in first else 1
        # Sem timestamp o bloco não é uma fala traduzível; ignorar (e não
        # abortar o arquivo inteiro) é o comportamento tolerante esperado.
        if ti >= len(lines) or "-->" not in lines[ti]:
            continue
        timestamp = lines[ti].strip()
        start = offset + sum(len(line) for line in lines[:ti + 1])
        # Keep the final line ending outside the translated text slot.
        tail = len(block) - len(block.rstrip("\r\n"))
        end = offset + len(block) - tail
        if start > end:
            start = end
        slots.append((start, end))
        cues.append((timestamp, source[start:end].replace("\r\n", "\n").replace("\r", "\n")))
    return SubtitleTemplate(source, slots), cues


def parse_ass_document(source: str):
    fields = ["Layer", "Start", "End", "Style", "Name", "MarginL", "MarginR", "MarginV", "Effect", "Text"]
    section, slots, dialogues, offset = "", [], [], 0
    for line in source.splitlines(keepends=True):
        raw = line.rstrip("\r\n")
        stripped = raw.strip().lstrip("\ufeff")
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped.casefold()
        elif section == "[events]" and stripped.casefold().startswith("format:"):
            fields = [field.strip() for field in stripped.split(":", 1)[1].split(",")]
            if sum(field.casefold() == "text" for field in fields) != 1:
                raise ValueError("A seção Events do ASS precisa de um único campo Text.")
        elif section == "[events]" and re.match(r"\s*Dialogue\s*:", raw, re.I):
            match = re.match(r"\s*Dialogue\s*:\s*", raw, re.I)
            payload = raw[match.end():]
            text_index = next(i for i, field in enumerate(fields) if field.casefold() == "text")
            before_count, after_count = text_index, len(fields) - text_index - 1
            before = payload.split(",", before_count)
            if len(before) != before_count + 1:
                raise ValueError("Diálogo ASS com campos ausentes.")
            remaining = before[-1]
            after = remaining.rsplit(",", after_count) if after_count else [remaining]
            if len(after) != after_count + 1:
                raise ValueError("Diálogo ASS com campos ausentes.")
            prefix = raw[:match.end()] + (",".join(before[:-1]) + "," if before_count else "")
            text = after[0]
            start = offset + len(prefix)
            slots.append((start, start + len(text)))
            dialogues.append((prefix, text))
        offset += len(line)
    return SubtitleTemplate(source, slots), dialogues


def build_vtt_document(template, cues):
    if isinstance(template, SubtitleTemplate):
        return template.render([text for _, text in cues])
    return "\n".join([str(template).rstrip(), "", *[f"{ts}\n{text}\n" for ts, text in cues]]).rstrip() + "\n"


def build_ass_document(template, dialogues):
    if isinstance(template, SubtitleTemplate):
        return template.render([text for _, text in dialogues])
    return "\n".join([str(template).rstrip(), *[prefix + text for prefix, text in dialogues]]).rstrip() + "\n"
