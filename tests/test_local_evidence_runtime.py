from __future__ import annotations

from types import SimpleNamespace

import torch

from scansci_html.local_evidence_runtime import (
    DEFAULT_LOCAL_EMBEDDING_MODEL,
    DEFAULT_LOCAL_RERANKER_MODEL,
    build_local_evidence_stack,
    default_vector_cache_identity,
)
from scansci_html.rerankers import CascadeReranker, LexicalReranker


class _Embedding:
    pass


class _NeuralReranker:
    def rerank(self, _query, candidates):
        return list(candidates)


def test_local_evidence_stack_caps_candidates_before_neural_reranking(monkeypatch):
    embedding_calls = []

    def fake_embedding(_provider, **kwargs):
        embedding_calls.append(kwargs)
        return _Embedding()

    monkeypatch.setattr("scansci_html.local_evidence_runtime.build_embedding_provider", fake_embedding)
    monkeypatch.setattr(
        "scansci_html.local_evidence_runtime.build_reranker",
        lambda *_args, **_kwargs: _NeuralReranker(),
    )
    monkeypatch.setattr(
        "scansci_html.local_evidence_runtime.installed_models",
        lambda: [
            {
                "id": DEFAULT_LOCAL_EMBEDDING_MODEL,
                "path": "D:/models/qwen3-embedding",
                "ready": True,
            },
            {
                "id": DEFAULT_LOCAL_RERANKER_MODEL,
                "path": "D:/models/qwen3-reranker",
                "ready": True,
            },
        ],
    )

    stack = build_local_evidence_stack(embedding_max_seq_length=192, reranker_candidate_limit=48)

    assert embedding_calls[0]["max_seq_length"] == 192
    assert embedding_calls[0]["model"] == "D:/models/qwen3-embedding"
    assert embedding_calls[0]["cache_identity"] == DEFAULT_LOCAL_EMBEDDING_MODEL
    assert isinstance(stack.reranker, CascadeReranker)
    assert isinstance(stack.reranker.stages[0][0], LexicalReranker)
    assert stack.reranker.stages[0][1] == 48
    assert isinstance(stack.reranker.stages[1][0], _NeuralReranker)
    assert stack.metadata["embedding_max_seq_length"] == 192
    assert stack.metadata["reranker_candidate_limit"] == 48


def test_local_evidence_stack_records_explicit_fallback(monkeypatch):
    def unavailable(*_args, **_kwargs):
        raise RuntimeError("weights missing")

    monkeypatch.setattr("scansci_html.local_evidence_runtime.build_embedding_provider", unavailable)
    monkeypatch.setattr("scansci_html.local_evidence_runtime.build_reranker", unavailable)

    stack = build_local_evidence_stack()

    assert stack.metadata["fallback"] is True
    assert stack.metadata["local_neural_embedding"] is False
    assert stack.metadata["local_neural_reranker"] is False
    assert len(stack.metadata["fallback_reasons"]) == 2


def test_precision_profile_uses_local_qwen_reranker(monkeypatch):
    rerankers = []

    def fake_reranker(provider, **kwargs):
        reranker = _NeuralReranker()
        rerankers.append((provider, kwargs, reranker))
        return reranker

    monkeypatch.setattr(
        "scansci_html.local_evidence_runtime.build_embedding_provider",
        lambda *_args, **_kwargs: _Embedding(),
    )
    monkeypatch.setattr("scansci_html.local_evidence_runtime.build_reranker", fake_reranker)
    monkeypatch.setattr(
        "scansci_html.local_evidence_runtime.installed_models",
        lambda: [
            {
                "id": "Qwen/Qwen3-Embedding-0.6B",
                "path": "D:/models/qwen3-embedding",
                "ready": True,
            },
            {
                "id": "Qwen/Qwen3-Reranker-0.6B",
                "path": "D:/models/qwen3-reranker",
                "ready": True,
            }
        ],
    )

    stack = build_local_evidence_stack(
        quality_profile="precision",
        reranker_candidate_limit=60,
        precision_candidate_limit=30,
    )

    assert [call[0] for call in rerankers] == ["qwen3"]
    assert rerankers[0][1]["model_name"] == "D:/models/qwen3-reranker"
    assert [stage[1] for stage in stack.reranker.stages] == [30, None]
    assert stack.metadata["effective_quality_profile"] == "precision"
    assert stack.metadata["precision_reranker_active"] is True
    assert stack.metadata["qwen_embedding_active"] is True
    assert stack.metadata["qwen_reranker_active"] is True
    assert stack.metadata["fallback"] is False


def test_qwen_defaults_fall_back_explicitly_when_weights_are_not_local(monkeypatch):
    monkeypatch.setattr(
        "scansci_html.local_evidence_runtime.build_embedding_provider",
        lambda *_args, **_kwargs: _Embedding(),
    )
    monkeypatch.setattr(
        "scansci_html.local_evidence_runtime.build_reranker",
        lambda *_args, **_kwargs: _NeuralReranker(),
    )
    monkeypatch.setattr("scansci_html.local_evidence_runtime.installed_models", lambda: [])

    stack = build_local_evidence_stack(quality_profile="precision")

    assert isinstance(stack.reranker, LexicalReranker)
    assert stack.metadata["requested_quality_profile"] == "precision"
    assert stack.metadata["effective_quality_profile"] == "fast"
    assert stack.metadata["precision_reranker_active"] is False
    assert stack.metadata["fallback"] is True
    assert len(stack.metadata["fallback_reasons"]) == 2
    assert all("unavailable locally" in reason for reason in stack.metadata["fallback_reasons"])


def test_embedding_only_stack_does_not_load_reranker(monkeypatch):
    reranker_calls = []
    embedding = _Embedding()
    embedding.cache_key = "sentence-transformers:Qwen/Qwen3-Embedding-0.6B"

    monkeypatch.setattr(
        "scansci_html.local_evidence_runtime.build_embedding_provider",
        lambda *_args, **_kwargs: embedding,
    )
    monkeypatch.setattr(
        "scansci_html.local_evidence_runtime.build_reranker",
        lambda *_args, **_kwargs: reranker_calls.append(True),
    )
    monkeypatch.setattr(
        "scansci_html.local_evidence_runtime.installed_models",
        lambda: [
            {
                "id": DEFAULT_LOCAL_EMBEDDING_MODEL,
                "path": "D:/models/qwen3-embedding",
                "ready": True,
            }
        ],
    )

    stack = build_local_evidence_stack(load_reranker=False)

    assert reranker_calls == []
    assert isinstance(stack.reranker, LexicalReranker)
    assert stack.metadata["effective_quality_profile"] == "embedding-only"
    assert stack.metadata["qwen_embedding_active"] is True


def test_default_cache_identity_is_qwen(monkeypatch):
    monkeypatch.delenv("SCANSCI_LOCAL_EMBEDDING_MODEL", raising=False)

    identity = default_vector_cache_identity()

    assert identity == {
        "provider": "sentence-transformers:Qwen/Qwen3-Embedding-0.6B",
        "dimensions": 1024,
        "model": "Qwen/Qwen3-Embedding-0.6B",
    }


def test_zero_norm_qwen_embedding_is_rejected_before_cache_use(monkeypatch):
    class BrokenSentenceModel:
        def __getitem__(self, _index):
            return SimpleNamespace(
                auto_model=SimpleNamespace(
                    norm=SimpleNamespace(weight=torch.zeros(4)),
                )
            )

    broken_provider = _Embedding()
    broken_provider.model = BrokenSentenceModel()
    monkeypatch.setattr(
        "scansci_html.local_evidence_runtime.build_embedding_provider",
        lambda *_args, **_kwargs: broken_provider,
    )
    monkeypatch.setattr(
        "scansci_html.local_evidence_runtime.installed_models",
        lambda: [
            {
                "id": DEFAULT_LOCAL_EMBEDDING_MODEL,
                "path": "D:/models/qwen3-embedding",
                "ready": True,
            }
        ],
    )

    stack = build_local_evidence_stack(load_reranker=False)

    assert stack.metadata["local_neural_embedding"] is False
    assert stack.metadata["fallback"] is True
    assert "all zero" in stack.metadata["fallback_reasons"][0]
