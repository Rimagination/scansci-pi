"""Lazy local neural retrieval stack used by the desktop research runtime."""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any

from .embeddings import HashingEmbeddingProvider, build_embedding_provider
from .local_model_market import installed_models
from .local_retrieval_runtime import model_device
from .rerankers import (
    CascadeReranker,
    HybridPrefilterReranker,
    LexicalReranker,
    build_reranker,
)


DEFAULT_LOCAL_EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-0.6B"
DEFAULT_LOCAL_EMBEDDING_DIMENSIONS = 1024
DEFAULT_LOCAL_RERANKER_MODEL = "Qwen/Qwen3-Reranker-0.6B"
DEFAULT_PRECISION_RERANKER_MODEL = "Qwen/Qwen3-Reranker-0.6B"
BUILTIN_MODEL_MARKER = "__builtin__"


@dataclass(frozen=True)
class LocalEvidenceStack:
    embedding_provider: Any
    reranker: Any
    metadata: dict[str, Any]


def build_local_evidence_stack(
    *,
    embedding_model: str = "",
    reranker_model: str = "",
    embedding_batch_size: int = 64,
    reranker_batch_size: int = 4,
    embedding_max_seq_length: int = 512,
    reranker_candidate_limit: int = 30,
    quality_profile: str = "balanced",
    precision_reranker_model: str = "",
    precision_candidate_limit: int = 60,
    precision_batch_size: int = 4,
    precision_max_length: int = 2048,
    load_reranker: bool = True,
    embedding_provider_override: Any | None = None,
    reranker_override: Any | None = None,
) -> LocalEvidenceStack:
    """Load real local models and retain explicit, inspectable fallbacks.

    Model weights are loaded lazily when a notebook evidence workflow starts.
    Missing optional dependencies or weights never turn into a silent claim
    that a neural model ran: the returned metadata records the exact fallback.
    """

    resolved_embedding = (
        str(embedding_model or "").strip()
        or os.getenv("SCANSCI_LOCAL_EMBEDDING_MODEL", "").strip()
        or DEFAULT_LOCAL_EMBEDDING_MODEL
    )
    resolved_reranker = (
        str(reranker_model or "").strip()
        or os.getenv("SCANSCI_LOCAL_RERANKER_MODEL", "").strip()
        or DEFAULT_LOCAL_RERANKER_MODEL
    )
    requested_profile = str(quality_profile or "balanced").strip().lower()
    if requested_profile not in {"balanced", "precision"}:
        requested_profile = "balanced"
    resolved_precision_reranker = (
        str(precision_reranker_model or "").strip()
        or os.getenv("SCANSCI_PRECISION_RERANKER_MODEL", "").strip()
        or DEFAULT_PRECISION_RERANKER_MODEL
    )
    embedding_builtin = str(resolved_embedding).casefold() in {"builtin", "local:builtin-evidence", BUILTIN_MODEL_MARKER}
    reranker_builtin = str(resolved_reranker).casefold() in {"builtin", "local:builtin-evidence", BUILTIN_MODEL_MARKER}
    errors: list[str] = []
    if embedding_builtin:
        embedding_provider = HashingEmbeddingProvider()
        embedding_identity = "local-hash-v1"
    elif embedding_provider_override is not None:
        embedding_provider = embedding_provider_override
        embedding_identity = str(
            getattr(embedding_provider, "cache_key", "")
            or f"sentence-transformers:{resolved_embedding}"
        )
    else:
        try:
            embedding_source = _local_model_source(
                resolved_embedding,
                require_local="qwen" in resolved_embedding.casefold(),
            )
            embedding_provider = build_embedding_provider(
                "sentence-transformers",
                model=embedding_source,
                cache_identity=resolved_embedding,
                batch_size=max(1, int(embedding_batch_size)),
                max_seq_length=max(32, int(embedding_max_seq_length)),
            )
            if "qwen3-embedding" in resolved_embedding.casefold():
                _validate_qwen_embedding_provider(embedding_provider)
            embedding_identity = f"sentence-transformers:{resolved_embedding}"
        except Exception as error:  # optional local-model boundary
            embedding_provider = HashingEmbeddingProvider()
            embedding_identity = "local-hash-v1"
            errors.append(f"embedding {type(error).__name__}: {error}"[:500])

    if not load_reranker or reranker_builtin:
        reranker = LexicalReranker()
        reranker_identity = "local-lexical-v1"
        effective_profile = "embedding-only" if not reranker_builtin else "fast"
    else:
        try:
            selected_reranker_model = (
                resolved_precision_reranker if requested_profile == "precision" else resolved_reranker
            )
            provider_name = _reranker_provider(selected_reranker_model)
            if reranker_override is not None:
                neural_reranker = reranker_override
            else:
                reranker_source = _local_model_source(
                    selected_reranker_model,
                    require_local=provider_name == "qwen3",
                )
                neural_reranker = build_reranker(
                    provider_name,
                    model_name=reranker_source,
                    batch_size=(
                        max(1, int(precision_batch_size))
                        if requested_profile == "precision"
                        else max(1, int(reranker_batch_size))
                    ),
                    max_length=max(256, int(precision_max_length)),
                )
            candidate_limit = (
                max(10, int(precision_candidate_limit))
                if requested_profile == "precision"
                else max(10, int(reranker_candidate_limit))
            )
            reranker = CascadeReranker(
                [
                    (HybridPrefilterReranker(), candidate_limit),
                    (neural_reranker, None),
                ]
            )
            reranker_identity = str(
                getattr(neural_reranker, "cache_key", "")
                or f"{provider_name}:{selected_reranker_model}"
            )
            effective_profile = requested_profile
        except Exception as error:  # optional local-model boundary
            reranker = LexicalReranker()
            reranker_identity = "local-lexical-v1"
            effective_profile = "fast"
            errors.append(f"reranker {type(error).__name__}: {error}"[:500])

    embedding_device = str(
        getattr(embedding_provider, "device", "")
        or model_device(getattr(embedding_provider, "model", None))
        or "cpu"
    )
    reranker_devices = [
        str(
            getattr(stage, "device", "")
            or model_device(getattr(stage, "model", None))
            or "cpu"
        )
        for stage, _keep_top in getattr(reranker, "stages", [(reranker, None)])
        if not isinstance(stage, LexicalReranker)
    ]
    reranker_device = ",".join(dict.fromkeys(reranker_devices)) or "cpu"

    return LocalEvidenceStack(
        embedding_provider=embedding_provider,
        reranker=reranker,
        metadata={
            "embedding": embedding_identity,
            "reranker": reranker_identity,
            "requested_embedding_model": resolved_embedding,
            "requested_reranker_model": resolved_reranker,
            "requested_precision_reranker_model": resolved_precision_reranker,
            "requested_quality_profile": requested_profile,
            "effective_quality_profile": effective_profile,
            "embedding_max_seq_length": max(32, int(embedding_max_seq_length)),
            "reranker_candidate_limit": max(10, int(reranker_candidate_limit)),
            "precision_candidate_limit": max(5, int(precision_candidate_limit)),
            "precision_max_length": max(256, int(precision_max_length)),
            "local_neural_embedding": embedding_identity.startswith("sentence-transformers:"),
            "local_neural_reranker": reranker_identity.startswith(("cross-encoder:", "qwen3:")),
            "remote_reranker_active": reranker_identity.startswith("siliconflow:"),
            "qwen_embedding_active": (
                embedding_identity.startswith("sentence-transformers:")
                and resolved_embedding.casefold().startswith("qwen/")
            ),
            "qwen_reranker_active": reranker_identity.startswith("qwen3:"),
            "precision_reranker_active": (
                effective_profile == "precision" and reranker_identity.startswith("qwen3:")
            ),
            "embedding_device": embedding_device,
            "reranker_device": reranker_device,
            "fallback": bool(errors),
            "fallback_reasons": errors,
        },
    )


def _installed_model_path(model_id: str) -> str:
    wanted = str(model_id or "").strip().casefold()
    if not wanted:
        return ""
    for item in installed_models():
        if str(item.get("id", "")).casefold() == wanted and bool(item.get("ready")):
            return str(item.get("path", "") or "")
    return ""


def _local_model_source(model_id: str, *, require_local: bool = False) -> str:
    """Load installed weights by path while retaining a machine-stable cache identity."""

    candidate = str(model_id or "").strip()
    if not candidate:
        return candidate
    if os.path.exists(candidate):
        return candidate
    installed_path = _installed_model_path(candidate)
    if installed_path:
        return installed_path
    if require_local:
        raise RuntimeError(f"model unavailable locally: {candidate}")
    return candidate


def _reranker_provider(model_id: str) -> str:
    return "qwen3" if "qwen3-reranker" in str(model_id or "").casefold() else "cross-encoder"


def _validate_qwen_embedding_provider(provider: Any) -> None:
    """Reject the known zero-norm corruption mode before it can poison a cache."""

    sentence_model = getattr(provider, "model", None)
    if sentence_model is None:
        return
    try:
        transformer = sentence_model[0]
        auto_model = transformer.auto_model
        final_norm = getattr(auto_model, "norm", None)
        if final_norm is None:
            final_norm = auto_model.model.norm
        maximum = float(final_norm.weight.detach().float().abs().max().cpu())
    except (AttributeError, IndexError, KeyError, TypeError, ValueError) as error:
        raise RuntimeError("Qwen3 embedding model is missing its final normalization weights") from error
    if maximum <= 0.0:
        raise RuntimeError(
            "Qwen3 embedding weights failed integrity validation: "
            "final normalization weights are all zero"
        )


def default_vector_cache_identity() -> dict[str, Any]:
    """Return the production cache contract without loading model weights."""

    model_id = (
        os.getenv("SCANSCI_LOCAL_EMBEDDING_MODEL", "").strip()
        or DEFAULT_LOCAL_EMBEDDING_MODEL
    )
    return {
        "provider": f"sentence-transformers:{model_id}",
        "dimensions": (
            DEFAULT_LOCAL_EMBEDDING_DIMENSIONS
            if model_id.casefold() == DEFAULT_LOCAL_EMBEDDING_MODEL.casefold()
            else 0
        ),
        "model": model_id,
    }
