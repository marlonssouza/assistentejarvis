"""Utilidades de texto compartilhadas (tokenização e similaridade).

Usadas pela memória estruturada e pelas políticas/skills para ranquear
relevância sem depender de embeddings (funciona offline).
"""

import re

_STOPWORDS = {
    "de", "da", "do", "das", "dos", "que", "e", "o", "a", "os", "as", "um",
    "uma", "para", "com", "no", "na", "nos", "nas", "em", "por", "ao", "à",
    "the", "of", "and", "to", "is",
}


def tokens(text: str) -> set[str]:
    """Tokeniza em um conjunto de palavras significativas (minúsculas)."""
    if not isinstance(text, str):
        return set()
    return {
        token
        for token in re.findall(r"[0-9a-zà-ÿ]+", text.casefold())
        if len(token) > 1 and token not in _STOPWORDS
    }


def jaccard(a: set[str], b: set[str]) -> float:
    """Similaridade de Jaccard entre dois conjuntos de tokens."""
    if not a or not b:
        return 0.0
    union = len(a | b)
    if not union:
        return 0.0
    return len(a & b) / union


def similarity(a: str, b: str) -> float:
    """Similaridade de Jaccard entre dois textos."""
    return jaccard(tokens(a), tokens(b))
