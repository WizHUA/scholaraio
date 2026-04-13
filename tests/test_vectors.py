from __future__ import annotations

import os
from types import SimpleNamespace

from scholaraio import vectors
from scholaraio.config import _build_config


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
