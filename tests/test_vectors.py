from __future__ import annotations

import builtins
import os
import sqlite3
import sys
from types import SimpleNamespace

import numpy as np

from scholaraio.core.config import _build_config
from scholaraio.services import vectors
from scholaraio.stores import explore


def test_load_model_sets_hf_endpoint_before_sentence_transformers_import(tmp_path, monkeypatch):
    monkeypatch.delenv("SCHOLARAIO_HF_ENDPOINT", raising=False)
    monkeypatch.delenv("HF_ENDPOINT", raising=False)

    cfg = _build_config(
        {
            "embed": {
                "source": "huggingface",
                "hf_endpoint": "https://hf-mirror.example",
                "device": "cpu",
                "model": "test-model",
            }
        },
        tmp_path,
    )

    seen: dict[str, str | None] = {}

    class FakeSentenceTransformer:
        def __init__(self, model_name: str, device: str):
            self.model_name = model_name
            self.device = device

    def fake_import_module(name: str):
        assert name == "sentence_transformers"
        seen["hf_endpoint_at_import"] = os.environ.get("HF_ENDPOINT")
        return SimpleNamespace(SentenceTransformer=FakeSentenceTransformer)

    monkeypatch.setattr(vectors.importlib, "import_module", fake_import_module)
    monkeypatch.setattr(vectors, "_resolve_model_path", lambda *args: None)
    monkeypatch.setattr(vectors, "_remote_model_download_available", lambda *_args, **_kwargs: True)
    vectors._model_cache.clear()

    prev_hf_endpoint = os.environ.get("HF_ENDPOINT")
    try:
        model = vectors._load_model(cfg)
    finally:
        if prev_hf_endpoint is None:
            monkeypatch.delenv("HF_ENDPOINT", raising=False)
        else:
            monkeypatch.setenv("HF_ENDPOINT", prev_hf_endpoint)

    assert seen["hf_endpoint_at_import"] == "https://hf-mirror.example"
    assert model.model_name == "test-model"
    assert model.device == "cpu"


def test_load_model_overrides_modelscope_cache_from_cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("MODELSCOPE_CACHE", "/preexisting-cache")
    cfg = _build_config(
        {
            "embed": {
                "source": "modelscope",
                "cache_dir": str(tmp_path / "cfg-cache"),
                "device": "cpu",
                "model": "test-model",
            }
        },
        tmp_path,
    )

    class FakeSentenceTransformer:
        def __init__(self, model_name: str, device: str):
            self.model_name = model_name
            self.device = device

    monkeypatch.setattr(
        vectors.importlib,
        "import_module",
        lambda name: SimpleNamespace(SentenceTransformer=FakeSentenceTransformer),
    )
    monkeypatch.setattr(vectors, "_resolve_model_path", lambda *args: None)
    monkeypatch.setattr(vectors, "_remote_model_download_available", lambda *_args, **_kwargs: True)
    vectors._model_cache.clear()

    prev_modelscope_cache = os.environ.get("MODELSCOPE_CACHE")
    try:
        vectors._load_model(cfg)
        assert os.environ.get("MODELSCOPE_CACHE") == str(tmp_path / "cfg-cache")
    finally:
        if prev_modelscope_cache is None:
            monkeypatch.delenv("MODELSCOPE_CACHE", raising=False)
        else:
            monkeypatch.setenv("MODELSCOPE_CACHE", prev_modelscope_cache)


def test_resolve_model_path_prefers_existing_local_modelscope_cache(tmp_path, monkeypatch):
    model_dir = tmp_path / "Qwen" / "Qwen3-Embedding-0___6B"
    model_dir.mkdir(parents=True)
    for name in ("modules.json", "model.safetensors", "config_sentence_transformers.json"):
        (model_dir / name).write_text("ok", encoding="utf-8")

    monkeypatch.delitem(os.environ, "HF_ENDPOINT", raising=False)

    path = vectors._resolve_model_path("Qwen/Qwen3-Embedding-0.6B", str(tmp_path), "modelscope")

    assert path == str(model_dir)


def test_load_model_fast_fails_when_remote_download_is_unreachable(tmp_path, monkeypatch):
    cfg = _build_config(
        {
            "embed": {
                "source": "huggingface",
                "device": "cpu",
                "model": "test-model",
            }
        },
        tmp_path,
    )

    class FakeSentenceTransformer:
        def __init__(self, model_name: str, device: str):
            raise AssertionError("remote loader should not be attempted when preflight fails")

    monkeypatch.setattr(
        vectors.importlib,
        "import_module",
        lambda name: SimpleNamespace(SentenceTransformer=FakeSentenceTransformer),
    )
    monkeypatch.setattr(vectors, "_resolve_model_path", lambda *args: None)
    monkeypatch.setattr(vectors, "_remote_model_download_available", lambda *_args, **_kwargs: False)
    vectors._model_cache.clear()

    try:
        vectors._load_model(cfg)
    except RuntimeError as exc:
        assert "HuggingFace" in str(exc) or "Hugging Face" in str(exc)
    else:
        raise AssertionError("expected _load_model to fail fast when remote preflight is unreachable")


def test_build_vectors_auto_rebuild_on_signature_change(tmp_papers, tmp_db, tmp_path, monkeypatch):
    monkeypatch.setattr(vectors, "_embed_batch", lambda texts, cfg=None: [[0.1, 0.2, 0.3] for _ in texts])

    cfg_local = _build_config(
        {
            "embed": {
                "provider": "local",
                "model": "local-test-model",
                "source": "huggingface",
                "device": "cpu",
            }
        },
        tmp_path,
    )
    n1 = vectors.build_vectors(tmp_papers, tmp_db, cfg=cfg_local)
    assert n1 == 2

    with sqlite3.connect(tmp_db) as conn:
        sig1 = conn.execute("SELECT value FROM vector_metadata WHERE key='embed_signature'").fetchone()[0]
        count1 = conn.execute("SELECT COUNT(*) FROM paper_vectors").fetchone()[0]
    assert sig1.startswith("local::local-test-model::")
    assert count1 == 2

    cfg_cloud = _build_config(
        {
            "embed": {
                "provider": "openai-compat",
                "model": "text-embedding-3-small",
                "api_base": "https://api.example.com/v1",
                "api_key": "embed-key",
            }
        },
        tmp_path,
    )
    n2 = vectors.build_vectors(tmp_papers, tmp_db, cfg=cfg_cloud)
    assert n2 == 2  # full rebuild after signature change

    with sqlite3.connect(tmp_db) as conn:
        sig2 = conn.execute("SELECT value FROM vector_metadata WHERE key='embed_signature'").fetchone()[0]
        count2 = conn.execute("SELECT COUNT(*) FROM paper_vectors").fetchone()[0]
    assert sig2 == "openai-compat::text-embedding-3-small::https://api.example.com/v1"
    assert count2 == 2


def test_build_vectors_provider_none_clears_vectors(tmp_papers, tmp_db, tmp_path, monkeypatch):
    monkeypatch.setattr(vectors, "_embed_batch", lambda texts, cfg=None: [[0.1, 0.2, 0.3] for _ in texts])

    cfg_local = _build_config(
        {
            "embed": {
                "provider": "local",
                "model": "local-test-model",
                "source": "huggingface",
                "device": "cpu",
            }
        },
        tmp_path,
    )
    assert vectors.build_vectors(tmp_papers, tmp_db, cfg=cfg_local) == 2

    cfg_none = _build_config({"embed": {"provider": "none"}}, tmp_path)
    assert vectors.build_vectors(tmp_papers, tmp_db, cfg=cfg_none) == 0

    with sqlite3.connect(tmp_db) as conn:
        count = conn.execute("SELECT COUNT(*) FROM paper_vectors").fetchone()[0]
        sig = conn.execute("SELECT value FROM vector_metadata WHERE key='embed_signature'").fetchone()[0]

    assert count == 0
    assert sig == "none"


def test_build_vectors_skips_faiss_append_when_cache_missing(tmp_papers, tmp_db, tmp_path, monkeypatch):
    monkeypatch.setattr(vectors, "_embed_batch", lambda texts, cfg=None: [[0.1, 0.2, 0.3] for _ in texts])

    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "faiss":
            raise ModuleNotFoundError("No module named 'faiss'")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    cfg_local = _build_config(
        {
            "embed": {
                "provider": "local",
                "model": "local-test-model",
                "source": "huggingface",
                "device": "cpu",
            }
        },
        tmp_path,
    )

    assert vectors.build_vectors(tmp_papers, tmp_db, cfg=cfg_local) == 2

    index_path, ids_path = vectors._faiss_paths(tmp_db)
    assert not index_path.exists()
    assert not ids_path.exists()


def test_vsearch_embeds_query_before_loading_faiss_index(tmp_db, monkeypatch):
    with sqlite3.connect(tmp_db) as conn:
        conn.execute(
            "CREATE TABLE paper_vectors (paper_id TEXT PRIMARY KEY, embedding BLOB NOT NULL, content_hash TEXT)"
        )
        conn.execute(
            "INSERT INTO paper_vectors (paper_id, embedding, content_hash) VALUES (?, ?, ?)",
            ("seed-paper", b"\x00\x00\x00\x00", ""),
        )
        conn.commit()

    order: list[str] = []

    class FakeIndex:
        ntotal = 1

        def search(self, q_vec, fetch_k):
            order.append("search")
            return np.array([[0.9]], dtype="float32"), np.array([[0]], dtype="int64")

    monkeypatch.setitem(sys.modules, "faiss", SimpleNamespace(normalize_L2=lambda arr: order.append("faiss_normalize")))
    monkeypatch.setattr(vectors, "_embed_text", lambda query, cfg=None: order.append("embed") or [1.0, 0.0])

    def fake_build_index(db_path):
        assert order == ["embed"], f"expected query embedding before FAISS index load, got {order}"
        order.append("build_index")
        return FakeIndex(), ["paper-1"]

    monkeypatch.setattr(vectors, "_build_faiss_index", fake_build_index)

    results = vectors.vsearch("turbulence", tmp_db, top_k=1)

    assert results[0]["paper_id"] == "paper-1"
    assert order[:3] == ["embed", "build_index", "search"]


def test_vsearch_does_not_embed_when_vector_table_is_empty(tmp_db, monkeypatch):
    with sqlite3.connect(tmp_db) as conn:
        conn.execute(
            "CREATE TABLE paper_vectors (paper_id TEXT PRIMARY KEY, embedding BLOB NOT NULL, content_hash TEXT)"
        )
        conn.commit()

    monkeypatch.setattr(
        vectors,
        "_embed_text",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("embedding should not run for empty vector store")
        ),
    )

    with np.testing.assert_raises_regex(FileNotFoundError, "Vector index is empty"):
        vectors.vsearch("turbulence", tmp_db, top_k=1)


def test_explore_vsearch_embeds_query_before_loading_faiss_index(tmp_path, monkeypatch):
    order: list[str] = []
    cfg = _build_config({}, tmp_path)
    db_path = cfg.explore_root / "demo" / "explore.db"
    db_path.parent.mkdir(parents=True)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE paper_vectors (paper_id TEXT PRIMARY KEY, embedding BLOB NOT NULL, content_hash TEXT)"
        )
        conn.execute(
            "INSERT INTO paper_vectors (paper_id, embedding, content_hash) VALUES (?, ?, ?)",
            ("seed-paper", b"\x00\x00\x00\x00", ""),
        )
        conn.commit()

    class FakeIndex:
        ntotal = 1

    monkeypatch.setattr(vectors, "_embed_text", lambda query, cfg=None: order.append("embed") or [1.0, 0.0])

    def fake_build_index(name, cfg=None):
        assert order == ["embed"], f"expected query embedding before FAISS index load, got {order}"
        order.append("build_index")
        return FakeIndex(), ["10.1234/demo"]

    monkeypatch.setattr(explore, "_build_faiss_index", fake_build_index)
    monkeypatch.setattr(
        vectors,
        "_vsearch_faiss",
        lambda *_args, **_kwargs: [("10.1234/demo", 0.88)],
    )
    monkeypatch.setattr(
        explore,
        "iter_papers",
        lambda name, cfg=None: [
            {
                "title": "Demo paper",
                "doi": "10.1234/demo",
                "authors": ["Alice"],
                "year": 2024,
            }
        ],
    )

    results = explore.explore_vsearch("demo", "turbulence", top_k=1, cfg=cfg)

    assert results[0]["doi"] == "10.1234/demo"
    assert order[:2] == ["embed", "build_index"]


def test_explore_vsearch_does_not_embed_when_vector_table_is_empty(tmp_path, monkeypatch):
    cfg = _build_config({}, tmp_path)
    db_path = cfg.explore_root / "demo" / "explore.db"
    db_path.parent.mkdir(parents=True)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE paper_vectors (paper_id TEXT PRIMARY KEY, embedding BLOB NOT NULL, content_hash TEXT)"
        )
        conn.commit()

    monkeypatch.setattr(
        vectors,
        "_embed_text",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("embedding should not run for empty vector store")
        ),
    )

    with np.testing.assert_raises_regex(FileNotFoundError, "Vector store is empty"):
        explore.explore_vsearch("demo", "turbulence", top_k=1, cfg=cfg)
