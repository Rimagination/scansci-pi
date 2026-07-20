"""Language-neutral lexical tokens for local retrieval and fallback embeddings."""

from __future__ import annotations

import re


_CJK_RANGE = "\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"


def lexical_tokens(value: str) -> list[str]:
    """Tokenize Latin words and Chinese text without an external segmenter.

    Character bi/tri-grams make Chinese queries useful for offline hashing and
    lexical reranking, including PDF text that separates every glyph by spaces.
    """

    text = str(value or "").lower()
    text = re.sub(rf"(?<=[{_CJK_RANGE}])\s+(?=[{_CJK_RANGE}])", "", text)
    tokens = re.findall(r"[a-z0-9]+", text)
    for sequence in re.findall(rf"[{_CJK_RANGE}]+", text):
        if len(sequence) == 1:
            tokens.append(sequence)
            continue
        if len(sequence) <= 8:
            tokens.append(sequence)
        for width in (2, 3):
            tokens.extend(sequence[index : index + width] for index in range(len(sequence) - width + 1))
    return tokens
