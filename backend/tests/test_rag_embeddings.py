"""Tests for embedding provider abstractions and deterministic mock implementations."""

import math

import pytest
from app.rag.embeddings.base import BaseEmbeddingProvider
from app.rag.embeddings.factory import get_embedding_provider
from app.rag.embeddings.mock import MockEmbeddingProvider


def test_mock_embedding_deterministic_output():
    """Verify identical text produces identical float vectors."""
    provider = MockEmbeddingProvider(dimension=1536)
    v1 = provider.get_embedding("What is our net revenue for Q2?")
    v2 = provider.get_embedding("What is our net revenue for Q2?")
    assert v1 == v2
    assert len(v1) == 1536


def test_mock_embedding_l2_normalization():
    """Verify vectors are normalized to unit Euclidean length."""
    provider = MockEmbeddingProvider(dimension=1536)
    v = provider.get_embedding("Deterministic business analytics and unit testing.")
    norm = math.sqrt(sum(x * x for x in v))
    assert pytest.approx(norm, 0.001) == 1.0


def test_mock_embedding_semantic_overlap():
    """Verify overlapping business vocabulary exhibits higher similarity than unrelated text."""
    provider = MockEmbeddingProvider(dimension=1536)
    q = "net revenue and gross sales"
    rel = "reporting net revenue and sales performance"
    unrel = "tropical rainforest biodiversity expedition"

    vq = provider.get_embedding(q)
    v_rel = provider.get_embedding(rel)
    v_unrel = provider.get_embedding(unrel)

    sim_rel = sum(a * b for a, b in zip(vq, v_rel))
    sim_unrel = sum(a * b for a, b in zip(vq, v_unrel))

    assert sim_rel > sim_unrel


def test_embedding_factory_mock_default():
    """Verify default factory returns MockEmbeddingProvider without requiring API keys."""
    provider = get_embedding_provider("mock", force_new=True)
    assert isinstance(provider, BaseEmbeddingProvider)
    assert isinstance(provider, MockEmbeddingProvider)
    assert provider.dimension == 1536


def test_mock_embedding_batch_processing():
    """Verify batch get_embeddings processes multiple texts."""
    provider = MockEmbeddingProvider(dimension=1536)
    texts = ["Gross margin analysis", "Inventory valuation", "Customer RFM segmentation"]
    embeddings = provider.get_embeddings(texts)
    assert len(embeddings) == 3
    for emb in embeddings:
        assert len(emb) == 1536
        norm = math.sqrt(sum(x * x for x in emb))
        assert pytest.approx(norm, 0.001) == 1.0
