import pytest
from fastapi.testclient import TestClient
from apps.api.main import app
from apps.core.runtime import runtime
from apps.core.model_loader import (
    NativeModelLoader,
)
from apps.core.inference import (
    NativeInferenceEngine,
)
from apps.api.test_inference_api import (
    _make_tiny_model_dir,
    _init_loader,
)
from apps.core.production_client import (
    ProductionClient,
    ProductionError,
)
import tempfile
from apps.api.security import get_current_user
from types import SimpleNamespace
from uuid import UUID
from pathlib import Path

@pytest.fixture
def pclient():
    tmp = Path(tempfile.mkdtemp()) / "tiny-prod"
    mdir = _make_tiny_model_dir(tmp)
    loader = NativeModelLoader(
        model_path=str(mdir)
    )
    _init_loader(loader)
    old_loader = runtime.loader
    old_engine = runtime.engine
    old_init = runtime._initialized
    runtime.loader = loader
    runtime.engine = NativeInferenceEngine(
        loader
    )
    runtime._initialized = True
    fake = SimpleNamespace(id=UUID("00000000-0000-0000-0000-000000000001"))
    app.dependency_overrides[get_current_user] = lambda: fake
    c = ProductionClient(TestClient(app))
    yield c
    app.dependency_overrides.clear()
    runtime.loader = old_loader
    runtime.engine = old_engine
    runtime._initialized = old_init

def test_01_health(pclient):
    assert pclient.health() is True

def test_02_infer(pclient):
    out = pclient.infer(
        "hello world",
        max_tokens=8,
        temperature=0.0,
    )
    assert isinstance(out, str)
    assert out.strip() != ""

def test_03_stream(pclient):
    toks = list(
        pclient.infer_stream(
            "hello world",
            max_tokens=8,
            temperature=0.7,
            top_k=5,
            top_p=0.9,
        )
    )
    assert len(toks) >= 1
    assert len(toks) <= 8
    assert "".join(toks).strip() != ""

def test_04_validation_error(pclient):
    with pytest.raises(ProductionError):
        pclient.infer(
            "hello world",
            max_tokens=8,
            temperature=0.7,
            top_p=1.5,
        )
