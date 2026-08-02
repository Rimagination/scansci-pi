import pytest
import torch
from types import SimpleNamespace

from scansci_html.embeddings import (
    OpenAICompatibleEmbeddingProvider,
    SentenceTransformersEmbeddingProvider,
    build_embedding_provider,
)
from scansci_html.rerankers import (
    CrossEncoderReranker,
    HybridPrefilterReranker,
    JinaReranker,
    LexicalReranker,
    Qwen3Reranker,
    build_reranker,
)


def test_build_embedding_provider_returns_local_hashing_provider():
    provider = build_embedding_provider("local")

    vectors = provider.embed_texts(["cortical activity", "cortical activity"])

    assert vectors[0] == vectors[1]
    assert len(vectors[0]) == 128


def test_openai_compatible_embedding_provider_uses_configured_endpoint():
    calls = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"embedding": [1.0, 0.0]}, {"embedding": [0.0, 1.0]}]}

    class FakeSession:
        def post(self, url, *, headers, json, timeout):
            calls.append((url, headers, json, timeout))
            return FakeResponse()

    provider = OpenAICompatibleEmbeddingProvider(
        base_url="https://example.test/v1",
        api_key="secret",
        model="embed-model",
        session=FakeSession(),
    )

    assert provider.embed_texts(["a", "b"]) == [[1.0, 0.0], [0.0, 1.0]]
    assert calls == [
        (
            "https://example.test/v1/embeddings",
            {"Authorization": "Bearer secret", "Content-Type": "application/json"},
            {"model": "embed-model", "input": ["a", "b"]},
            30.0,
        )
    ]


def test_openai_compatible_embedding_provider_rejects_mismatched_response():
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"embedding": [1.0, 0.0]}]}

    class FakeSession:
        def post(self, *_args, **_kwargs):
            return FakeResponse()

    provider = OpenAICompatibleEmbeddingProvider(
        base_url="https://example.test/v1",
        api_key="secret",
        model="embed-model",
        session=FakeSession(),
    )

    with pytest.raises(RuntimeError, match="1 vectors for a batch of 2"):
        provider.embed_texts(["a", "b"])


def test_openai_compatible_embedding_provider_rejects_oversized_input_before_network():
    calls = 0

    class FakeSession:
        def post(self, *_args, **_kwargs):
            nonlocal calls
            calls += 1
            raise AssertionError("network must not be called")

    provider = OpenAICompatibleEmbeddingProvider(
        base_url="https://example.test/v1",
        api_key="secret",
        model="embed-model",
        session=FakeSession(),
    )

    with pytest.raises(ValueError, match="per-text character limit"):
        provider.embed_texts(["x" * 100_001])

    assert calls == 0


def test_build_embedding_provider_requires_config_for_openai_compatible():
    with pytest.raises(ValueError, match="base_url"):
        build_embedding_provider("openai-compatible", api_key="secret", model="embed-model")


def test_sentence_transformers_embedding_provider_uses_model_encode():
    class FakeSentenceTransformer:
        def encode(self, texts, **kwargs):
            assert texts == ["cortical activity", "biomass response"]
            assert kwargs["batch_size"] == 4
            assert kwargs["normalize_embeddings"] is True
            return [[1.0, 0.0], [0.0, 1.0]]

    provider = SentenceTransformersEmbeddingProvider(
        model=FakeSentenceTransformer(),
        model_name="sentence-transformers/all-MiniLM-L6-v2",
        batch_size=4,
    )

    assert provider.embed_texts(["cortical activity", "biomass response"]) == [
        [1.0, 0.0],
        [0.0, 1.0],
    ]
    assert provider.model_name == "sentence-transformers/all-MiniLM-L6-v2"


def test_sentence_transformers_embedding_provider_uses_query_prompt_when_available():
    calls = []

    class FakeSentenceTransformer:
        prompts = {"query": "Instruct: retrieve relevant passages\nQuery: "}

        def encode(self, texts, **kwargs):
            calls.append((texts, kwargs))
            return [[1.0, 0.0]]

    provider = SentenceTransformersEmbeddingProvider(
        model=FakeSentenceTransformer(),
        model_name="Qwen/Qwen3-Embedding-0.6B",
        batch_size=4,
    )

    assert provider.embed_query("Which evidence supports the claim?") == [1.0, 0.0]
    assert calls == [
        (
            ["Which evidence supports the claim?"],
            {
                "batch_size": 4,
                "normalize_embeddings": True,
                "prompt_name": "query",
            },
        )
    ]


def test_build_embedding_provider_accepts_sentence_transformers_model(monkeypatch):
    class FakeSentenceTransformer:
        def encode(self, texts, **kwargs):
            return [[0.5, 0.5] for _text in texts]

    monkeypatch.setattr(
        "scansci_html.embeddings._load_sentence_transformer_model",
        lambda model_name: FakeSentenceTransformer(),
    )

    provider = build_embedding_provider(
        "sentence-transformers",
        model="sentence-transformers/all-MiniLM-L6-v2",
    )

    assert isinstance(provider, SentenceTransformersEmbeddingProvider)
    assert provider.embed_texts(["test"]) == [[0.5, 0.5]]


def test_build_embedding_provider_passes_sentence_transformers_batch_size(monkeypatch):
    class FakeSentenceTransformer:
        def encode(self, texts, **kwargs):
            assert kwargs["batch_size"] == 4
            return [[0.5, 0.5] for _text in texts]

    monkeypatch.setattr(
        "scansci_html.embeddings._load_sentence_transformer_model",
        lambda model_name: FakeSentenceTransformer(),
    )

    provider = build_embedding_provider(
        "sentence-transformers",
        model="Qwen/Qwen3-Embedding-0.6B",
        batch_size=4,
    )

    assert provider.embed_texts(["test"]) == [[0.5, 0.5]]


def test_build_embedding_provider_sets_sentence_transformers_max_seq_length(monkeypatch):
    loaded_models = []

    class FakeSentenceTransformer:
        max_seq_length = 8192

        def encode(self, texts, **kwargs):
            return [[0.5, 0.5] for _text in texts]

    def fake_load(_model_name):
        model = FakeSentenceTransformer()
        loaded_models.append(model)
        return model

    monkeypatch.setattr("scansci_html.embeddings._load_sentence_transformer_model", fake_load)

    provider = build_embedding_provider(
        "sentence-transformers",
        model="Qwen/Qwen3-Embedding-0.6B",
        max_seq_length=512,
    )

    assert isinstance(provider, SentenceTransformersEmbeddingProvider)
    assert provider.max_seq_length == 512
    assert loaded_models[0].max_seq_length == 512


def test_build_reranker_returns_local_lexical_reranker():
    assert isinstance(build_reranker("local"), LexicalReranker)


def test_hybrid_prefilter_preserves_dense_cross_language_hits_and_deduplicates_text():
    reranker = HybridPrefilterReranker()
    ranked = reranker.rerank(
        "氮素如何影响植物生长？",
        [
            {
                "evidence_id": "reference-a",
                "text": "Reich PB, Peterson DW.",
                "fts_score": 0.9,
                "dense_score": 0.1,
            },
            {
                "evidence_id": "answer-a",
                "text": "Nitrogen availability increased plant growth across the fertility gradient.",
                "fts_score": 0.0,
                "dense_score": 0.92,
            },
            {
                "evidence_id": "answer-duplicate",
                "text": "Nitrogen availability increased plant growth across the fertility gradient.",
                "fts_score": 0.0,
                "dense_score": 0.91,
            },
        ],
    )

    assert [item["evidence_id"] for item in ranked] == ["answer-a", "reference-a"]
    assert all("hybrid-prefilter" in item["routes"] for item in ranked)


def test_cross_encoder_reranker_uses_model_scores_and_preserves_metadata():
    class FakeCrossEncoder:
        def predict(self, pairs, **kwargs):
            assert pairs == [
                ("cortical activity", "Cortical activity was unchanged."),
                ("cortical activity", "Cortical activity increased in language regions."),
            ]
            assert kwargs["batch_size"] == 4
            return [0.1, 0.9]

    reranker = CrossEncoderReranker(model=FakeCrossEncoder(), batch_size=4)
    ranked = reranker.rerank(
        "cortical activity",
        [
            {
                "evidence_id": "doc1.s0001",
                "text": "Cortical activity was unchanged.",
                "matched_terms": [],
                "fts_score": 0.5,
            },
            {
                "evidence_id": "doc2.s0001",
                "text": "Cortical activity increased in language regions.",
                "matched_terms": [],
                "dense_score": 0.2,
            },
        ],
    )

    assert [hit["evidence_id"] for hit in ranked] == ["doc2.s0001", "doc1.s0001"]
    assert ranked[0]["cross_encoder_score"] == 0.9
    assert ranked[0]["score"] == 0.9
    assert ranked[0]["matched_terms"] == ["cortical", "activity"]
    assert ranked[0]["routes"] == ["cross-encoder"]
    assert ranked[1]["cross_encoder_score"] == 0.1


def test_build_reranker_accepts_injected_cross_encoder_model():
    class FakeCrossEncoder:
        def predict(self, pairs, **kwargs):
            return [1.0 for _pair in pairs]

    reranker = build_reranker("cross-encoder", model=FakeCrossEncoder(), batch_size=2)

    assert isinstance(reranker, CrossEncoderReranker)


def test_build_reranker_uses_canonical_minilm_cross_encoder_by_default():
    class FakeCrossEncoder:
        def predict(self, pairs, **kwargs):
            return [1.0 for _pair in pairs]

    reranker = build_reranker("cross-encoder", model=FakeCrossEncoder())

    assert isinstance(reranker, CrossEncoderReranker)
    assert reranker.model_name == "cross-encoder/ms-marco-MiniLM-L6-v2"


def test_jina_reranker_uses_official_rerank_api_and_preserves_metadata():
    class FakeJinaModel:
        def rerank(self, query, documents, *, top_n):
            assert query == "cortical activity"
            assert documents == [
                "Cortical activity was unchanged.",
                "Cortical activity increased in language regions.",
            ]
            assert top_n == 2
            return [
                {"index": 1, "relevance_score": 0.9},
                {"index": 0, "relevance_score": 0.1},
            ]

    reranker = JinaReranker(model=FakeJinaModel())
    ranked = reranker.rerank(
        "cortical activity",
        [
            {
                "evidence_id": "doc1.s0001",
                "text": "Cortical activity was unchanged.",
                "matched_terms": [],
            },
            {
                "evidence_id": "doc2.s0001",
                "text": "Cortical activity increased in language regions.",
                "matched_terms": [],
            },
        ],
    )

    assert [hit["evidence_id"] for hit in ranked] == ["doc2.s0001", "doc1.s0001"]
    assert ranked[0]["jina_score"] == 0.9
    assert ranked[0]["score"] == 0.9
    assert ranked[0]["matched_terms"] == ["cortical", "activity"]
    assert ranked[0]["routes"] == ["jina-reranker"]


def test_build_reranker_accepts_injected_jina_model():
    class FakeJinaModel:
        def rerank(self, query, documents, *, top_n):
            return [{"index": index, "relevance_score": 1.0} for index, _document in enumerate(documents)]

    reranker = build_reranker("jina", model=FakeJinaModel())

    assert isinstance(reranker, JinaReranker)
    assert reranker.model_name == "jinaai/jina-reranker-v3"


def test_qwen3_reranker_uses_yes_no_logits_instead_of_flat_cross_encoder_scores():
    class FakeTokenizer:
        def encode(self, _text, *, add_special_tokens):
            assert add_special_tokens is False
            return [1]

        def convert_tokens_to_ids(self, token):
            return {"yes": 3, "no": 4}[token]

        def __call__(self, values, **_kwargs):
            if isinstance(values, str):
                return SimpleNamespace(input_ids=[self.convert_tokens_to_ids(values)])
            return {
                "input_ids": [
                    [5] if "Beijing" in value else [6]
                    for value in values
                ]
            }

        def pad(self, payload, **_kwargs):
            return {"input_ids": torch.tensor(payload["input_ids"], dtype=torch.long)}

    class FakeModel:
        device = torch.device("cpu")

        def __init__(self):
            self.model = SimpleNamespace(norm=SimpleNamespace(weight=torch.ones(1)))

        def __call__(self, *, input_ids):
            logits = torch.zeros((len(input_ids), input_ids.shape[1], 8), dtype=torch.float32)
            for index, row in enumerate(input_ids):
                relevant = 5 in row.tolist()
                logits[index, -1, 3] = 5.0 if relevant else 0.0
                logits[index, -1, 4] = 0.0 if relevant else 5.0
            return SimpleNamespace(logits=logits)

    reranker = Qwen3Reranker(
        tokenizer=FakeTokenizer(),
        model=FakeModel(),
        batch_size=2,
        max_length=256,
    )
    ranked = reranker.rerank(
        "What is the capital of China?",
        [
            {"evidence_id": "relevant", "text": "The capital is Beijing."},
            {"evidence_id": "irrelevant", "text": "Gravity attracts bodies."},
        ],
    )

    assert [row["evidence_id"] for row in ranked] == ["relevant", "irrelevant"]
    assert ranked[0]["qwen3_score"] > 0.99
    assert ranked[1]["qwen3_score"] < 0.01
    assert ranked[0]["routes"] == ["qwen3-reranker"]


def test_build_reranker_rejects_unknown_provider():
    with pytest.raises(ValueError, match="Unsupported reranker provider"):
        build_reranker("unknown")
