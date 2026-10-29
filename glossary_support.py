"""Load user terminology and select bounded, relevant glossary instructions."""
from __future__ import annotations

import hashlib
from functools import lru_cache
import json
from pathlib import Path
import re
import unicodedata


def _fold(text: str) -> str:
    """Normaliza para comparação: NFKD, sem diacríticos, minúsculo.

    Espelha ``subtitle_quality.normalized`` de propósito: as duas funções
    precisam concordar sobre o que é "o mesmo termo", senão glossário e
    validação divergem.
    """
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


@lru_cache(maxsize=4096)
def _term_pattern(term: str):
    folded = _fold(term)
    return re.compile(r"(?<!\w)" + re.escape(folded) + r"(?!\w)") if folded else None


def _matches_prepared(term: str, text: str, folded: str) -> bool:
    if re.search(r"[\u3040-\u30ff\u3400-\u9fff]",term):
        return term in text
    pattern = _term_pattern(term)
    return bool(pattern and pattern.search(folded))


class Glossary:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._signature = None
        self._terms = {}

    def terms(self) -> dict[str, str]:
        if not self.path.is_file():
            self._signature, self._terms = None, {}
            return self._terms
        stat = self.path.stat()
        signature = (str(self.path.resolve()), stat.st_mtime_ns, stat.st_size)
        if signature != self._signature:
            data = json.loads(self.path.read_text(encoding="utf-8-sig"))
            if not isinstance(data, dict) or any(
                not isinstance(k, str) or not isinstance(v, str) or not k.strip() or not v.strip()
                for k, v in data.items()
            ):
                raise ValueError("O glossário deve conter pares de texto: termo original e tradução.")
            self._terms = {k.strip(): v.strip() for k, v in data.items()}
            self._signature = signature
        return self._terms

    def fingerprint(self) -> str:
        data = json.dumps(self.terms(), ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(data.encode("utf-8")).hexdigest()

    @staticmethod
    def matches(term: str, text: str) -> bool:
        """Verifica se ``term`` aparece em ``text``.

        Precisa concordar com ``subtitle_quality.contains``, que normaliza com
        NFKD e remove diacríticos. Antes, esta versão testava o texto CRU com
        ``\\w`` Unicode: como letras acentuadas contam como caractere de
        palavra, ``matches("coracao", "O coração dela")`` dava False enquanto
        ``contains`` dava True. O resultado era um pipeline com dois
        vocabulários incompatíveis — o termo entrava no prompt pelo glossário
        mas não era reconhecido na validação (ou vice-versa).
        """
        if re.search(r"[\u3040-\u30ff\u3400-\u9fff]", term):
            return term in text
        folded = _fold(term)
        if not folded:
            return False
        target = _fold(text)
        return bool(re.search(r"(?<!\w)" + re.escape(folded) + r"(?!\w)", target))

    def prompt(self, texts: list[str]) -> str:
        joined = "\n".join(texts)
        folded = _fold(joined)
        relevant = [(src, dst) for src, dst in self.terms().items()
                    if _matches_prepared(src,joined,folded) or _matches_prepared(dst,joined,folded)]
        relevant.sort(key=lambda pair: (-len(pair[0]), pair[0]))
        lines, length = [], 0
        for src, dst in relevant[:80]:
            line = json.dumps(src, ensure_ascii=False) + " -> " + json.dumps(dst, ensure_ascii=False)
            if length + len(line) > 6000:
                break
            lines.append(line)
            length += len(line)
        if not lines:
            return ""
        return ("\nGLOSSÁRIO DO PROJETO (use os termos aplicáveis; não acrescente falas):\n"
                + "\n".join(lines) + "\n")
