from __future__ import annotations

from hashlib import blake2b
import math
import os
import re
from typing import Any
from typing import Protocol

import requests

from .text_tokenization import lexical_tokens


class EmbeddingProvider(Protocol):
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        ...


def embed_query(provider: EmbeddingProvider, query: str) -> list[float]:
    query_embedder = getattr(provider, "embed_query", None)
    if callable(query_embedder):
        return [float(value) for value in query_embedder(query)]
    return [float(value) for value in provider.embed_texts([query])[0]]


class HashingEmbeddingProvider:
    """Small deterministic local embedding fallback for tests and offline use."""

    def __init__(self, dimensions: int = 128) -> None:
        if dimensions <= 0:
            raise ValueError("dimensions must be positive")
        self.dimensions = int(dimensions)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [_normalize(_hashing_vector(text, self.dimensions)) for text in texts]

    def embed_query(self, query: str) -> list[float]:
        return self.embed_texts([query])[0]


class OpenAICompatibleEmbeddingProvider:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 30.0,
        session: Any | None = None,
    ) -> None:
        if not base_url:
            raise ValueError("base_url is required for openai-compatible embeddings")
        if not api_key:
            raise ValueError("api_key is required for openai-compatible embeddings")
        if not model:
            raise ValueError("model is required for openai-compatible embeddings")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = float(timeout)
        self.session = session or requests.Session()

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        response = self.session.post(
            f"{self.base_url}/embeddings",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={"model": self.model, "input": texts},
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        return [list(item["embedding"]) for item in payload.get("data", [])]

    def embed_query(self, query: str) -> list[float]:
        return self.embed_texts([query])[0]


class SentenceTransformersEmbeddingProvider:
    def __init__(
        self,
        *,
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        model: Any | None = None,
        batch_size: int = 32,
        max_seq_length: int = 0,
        normalize_embeddings: bool = True,
    ) -> None:
        self.model_name = model_name
        self.model = model if model is not None else _load_sentence_transformer_model(model_name)
        self.batch_size = int(batch_size)
        self.max_seq_length = max(0, int(max_seq_length or 0))
        if self.max_seq_length and hasattr(self.model, "max_seq_length"):
            self.model.max_seq_length = self.max_seq_length
        self.normalize_embeddings = bool(normalize_embeddings)
        dimension_getter = getattr(self.model, "get_sentence_embedding_dimension", None)
        self.dimensions = int(dimension_getter() or 0) if callable(dimension_getter) else 0

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return self._encode(texts)

    def embed_query(self, query: str) -> list[float]:
        kwargs: dict[str, Any] = {}
        if self._has_query_prompt():
            kwargs["prompt_name"] = "query"
        return self._encode([query], **kwargs)[0]

    def _encode(self, texts: list[str], **extra_kwargs: Any) -> list[list[float]]:
        kwargs = {
            "batch_size": self.batch_size,
            "normalize_embeddings": self.normalize_embeddings,
        }
        kwargs.update(extra_kwargs)
        encoded = self.model.encode(
            texts,
            **kwargs,
        )
        if hasattr(encoded, "tolist"):
            encoded = encoded.tolist()
        return [[float(value) for value in vector] for vector in encoded]

    def _has_query_prompt(self) -> bool:
        prompts = getattr(self.model, "prompts", None)
        return isinstance(prompts, dict) and "query" in prompts


def build_embedding_provider(
    provider: str,
    *,
    base_url: str = "",
    api_key: str = "",
    model: str = "",
    dimensions: int = 128,
    batch_size: int = 32,
    max_seq_length: int = 0,
) -> EmbeddingProvider:
    name = (provider or "local").strip().lower()
    if name in {"local", "hashing", "hash"}:
        return HashingEmbeddingProvider(dimensions=dimensions)
    if name in {"openai-compatible", "openai"}:
        resolved_base_url = base_url or os.getenv("SCANSCI_EMBEDDING_BASE_URL", "")
        resolved_api_key = api_key or os.getenv("SCANSCI_EMBEDDING_API_KEY", "")
        resolved_model = model or os.getenv("SCANSCI_EMBEDDING_MODEL", "")
        return OpenAICompatibleEmbeddingProvider(
            base_url=resolved_base_url,
            api_key=resolved_api_key,
            model=resolved_model,
        )
    if name in {"sentence-transformers", "sentence_transformers", "sbert"}:
        resolved_model = (
            model
            or os.getenv("SCANSCI_EMBEDDING_MODEL", "")
            or "sentence-transformers/all-MiniLM-L6-v2"
        )
        return SentenceTransformersEmbeddingProvider(
            model_name=resolved_model,
            batch_size=batch_size,
            max_seq_length=max_seq_length,
        )
    raise ValueError(f"Unsupported embedding provider: {provider}")


def _load_sentence_transformer_model(model_name: str) -> Any:
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as error:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "sentence-transformers is required for --embedding-provider sentence-transformers; "
            "install sentence-transformers or use --embedding-provider local"
        ) from error
    return SentenceTransformer(model_name)


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    return sum(a * b for a, b in zip(left, right))


def _hashing_vector(text: str, dimensions: int) -> list[float]:
    vector = [0.0] * dimensions
    for token in lexical_tokens(text):
        digest = blake2b(token.encode("utf-8"), digest_size=8).digest()
        bucket = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if int.from_bytes(digest[4:], "big") % 2 == 0 else -1.0
        vector[bucket] += sign
    return vector


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm <= 0:
        return vector
    return [value / norm for value in vector]
