"""Phase 10.4 — Native Model Loader, Registry, Integrity, Inference, Streaming & Context Window Tests.

Pure-Python loader, registry, SHA-256, tokenizer fingerprint, and config/vocab mismatch tests
can run directly without torch or pydantic. Torch + Pydantic inference/streaming/runtime tests
run in CI or any workspace with torch and pydantic installed.
"""
import asyncio
import hashlib
import json
import sys
import tempfile
from pathlib import Path

from apps.core.exceptions import ModelLoadError, ModelNotFoundError, ResourceLimitExceeded
from apps.core.model_loader import (
    ARTIFACT_MANIFEST_SCHEMA,
    NativeModelLoader,
    validate_native_model_version,
)
from apps.core.native.config import ZyrquenConfig
from apps.core.native.dataset import PrepConfig, Source, prepare_dataset
from apps.core.native.registry import ModelRegistry
from apps.core.native.tokenizer import BASE_VOCAB, N_SPECIAL, ZyrquenTokenizer
from apps.core.training_infrastructure.recovery.checkpoint_recovery import CheckpointManager


def _sha256_bytes(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_save(obj, path: str) -> None:
    Path(path).write_text(json.dumps(obj), encoding="utf-8")


def _json_load(path: str):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _build_pure_python_registry_fixture(
    root: Path,
    *,
    version: str = "ZYRQUEN-Native-0.1.0",
    vocab_size_override: int | None = None,
    step: int = 0,
    config_payload: dict | None = None,
    metrics: dict | None = None,
    promote: bool = True,
) -> tuple[Path, ZyrquenTokenizer, ZyrquenConfig]:
    root.mkdir(parents=True, exist_ok=True)
    src = root / "corpus.jsonl"
    docs = [
        {"text": f"hello world test zyrquen hi sample {i} สวัสดี"}
        for i in range(40)
    ]
    src.write_text(
        "\n".join(json.dumps(doc, ensure_ascii=False) for doc in docs),
        encoding="utf-8",
    )
    ds_dir = root / "dataset"
    prepare_dataset(
        [Source(str(src), "test-fixture")],
        ds_dir,
        PrepConfig(val_fraction=0.1, test_fraction=0.1, version="0.1.0"),
    )

    tok = ZyrquenTokenizer.train(
        [doc["text"] for doc in docs],
        BASE_VOCAB + 24,
        version="0.1.0",
    )
    tok_path = root / "tokenizer.json"
    tok.save(tok_path)

    cfg = ZyrquenConfig(
        vocab_size=vocab_size_override if vocab_size_override is not None else tok.vocab_size,
        max_seq_len=32,
        n_layers=2,
        n_heads=2,
        d_model=32,
        d_ff=64,
    )
    ckpt_dir = root / "checkpoints"
    mgr = CheckpointManager(ckpt_dir, save_fn=_json_save, load_fn=_json_load)
    ckpt_state = {
        "model": {"embed.weight": [[0.0]]},
        "step": step,
        "model_config": cfg.to_dict(),
        "tokenizer_sha256": tok.fingerprint(),
        "dataset_version": "0.1.0",
    }
    if config_payload is not None:
        ckpt_state["config"] = config_payload
    mgr.save(step, ckpt_state)

    reg_root = root / "registry"
    registry = ModelRegistry(reg_root, load_fn=_json_load)
    registry.register(version, ckpt_dir, tok_path, ds_dir, metrics=metrics or {})
    if promote:
        registry.promote(version)
    return reg_root, tok, cfg


def _assert_raises(exc_types, fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except exc_types:
        return
    raise AssertionError(f"Expected {exc_types} to be raised by {fn}")


def test_01_not_configured_when_env_unset_and_missing_registry(tmp_path: Path | None = None):
    if tmp_path is None:
        with tempfile.TemporaryDirectory() as td:
            return test_01_not_configured_when_env_unset_and_missing_registry(Path(td))
    missing = tmp_path / "missing-registry"
    loader = NativeModelLoader(registry_root=missing)
    assert loader.is_configured() is False
    assert loader.health_state() == "not_configured"
    assert loader.is_ready() is False
    _assert_raises(ModelNotFoundError, loader.load)
    assert loader.health_state() == "not_configured"


def test_02_registry_without_active_version_is_not_configured(tmp_path: Path | None = None):
    if tmp_path is None:
        with tempfile.TemporaryDirectory() as td:
            return test_02_registry_without_active_version_is_not_configured(Path(td))
    reg_root, _, _ = _build_pure_python_registry_fixture(tmp_path, promote=False)
    loader = NativeModelLoader(registry_root=reg_root, load_fn=_json_load)
    assert loader.is_configured() is False
    assert loader.health_state() == "not_configured"
    _assert_raises(ModelNotFoundError, loader.load)
    assert loader.health_state() == "not_configured"


def test_03_non_native_artifact_directory_rejected_as_degraded(tmp_path: Path | None = None):
    if tmp_path is None:
        with tempfile.TemporaryDirectory() as td:
            return test_03_non_native_artifact_directory_rejected_as_degraded(Path(td))
    external_dir = tmp_path / "external-model-dir"
    external_dir.mkdir(parents=True)
    (external_dir / "config.json").write_text('{"model_type": "external"}', encoding="utf-8")
    (external_dir / "tokenizer_config.json").write_text('{"tokenizer_class": "External"}', encoding="utf-8")

    loader = NativeModelLoader(model_path=external_dir)
    assert loader.is_configured() is True
    _assert_raises(ModelLoadError, loader.load)
    assert loader.is_ready() is False
    assert loader.health_state() == "degraded"


def test_04_semantic_version_format_enforced(tmp_path: Path | None = None):
    if tmp_path is None:
        with tempfile.TemporaryDirectory() as td:
            return test_04_semantic_version_format_enforced(Path(td))
    assert validate_native_model_version("ZYRQUEN-Native-0.1.0") == "ZYRQUEN-Native-0.1.0"
    _assert_raises(ModelLoadError, validate_native_model_version, "v1")
    _assert_raises(ModelLoadError, validate_native_model_version, "0.1.0")
    _assert_raises(ModelLoadError, validate_native_model_version, "ZYRQUEN-Native-01.0.0")

    reg_root, _, _ = _build_pure_python_registry_fixture(tmp_path, version="v1", promote=True)
    loader = NativeModelLoader(registry_root=reg_root, load_fn=_json_load)
    _assert_raises(ModelLoadError, loader.load)
    assert loader.health_state() == "degraded"


def test_05_checkpoint_sha256_tamper_rejected(tmp_path: Path | None = None):
    if tmp_path is None:
        with tempfile.TemporaryDirectory() as td:
            return test_05_checkpoint_sha256_tamper_rejected(Path(td))
    reg_root, _, _ = _build_pure_python_registry_fixture(tmp_path, promote=True)
    ckpt_file = reg_root / "artifacts" / "ZYRQUEN-Native-0.1.0" / "checkpoint.pt"
    ckpt_file.write_text('{"tampered": true}', encoding="utf-8")

    called = False

    def fail_if_loaded(_path: str):
        nonlocal called
        called = True
        return {}

    loader = NativeModelLoader(registry_root=reg_root, load_fn=fail_if_loaded)
    _assert_raises(ModelLoadError, loader.load)
    assert called is False
    assert loader.health_state() == "degraded"


def test_06_tokenizer_fingerprint_tamper_rejected(tmp_path: Path | None = None):
    if tmp_path is None:
        with tempfile.TemporaryDirectory() as td:
            return test_06_tokenizer_fingerprint_tamper_rejected(Path(td))
    reg_root, _, _ = _build_pure_python_registry_fixture(tmp_path, promote=True)
    tok_file = reg_root / "artifacts" / "ZYRQUEN-Native-0.1.0" / "tokenizer.json"
    tok_data = json.loads(tok_file.read_text(encoding="utf-8"))
    tok_data["merges"].pop()
    tok_data["vocab_size"] -= 1
    tok_data["sha256"] = ZyrquenTokenizer([tuple(m) for m in tok_data["merges"]]).fingerprint()
    tok_file.write_text(json.dumps(tok_data), encoding="utf-8")

    loader = NativeModelLoader(registry_root=reg_root, load_fn=_json_load)
    _assert_raises(ModelLoadError, loader.load)
    assert loader.health_state() == "degraded"


def test_07_config_vocab_size_mismatch_rejected(tmp_path: Path | None = None):
    if tmp_path is None:
        with tempfile.TemporaryDirectory() as td:
            return test_07_config_vocab_size_mismatch_rejected(Path(td))
    reg_root, tok, _ = _build_pure_python_registry_fixture(
        tmp_path,
        vocab_size_override=BASE_VOCAB + 99,
        promote=True,
    )
    assert tok.vocab_size != BASE_VOCAB + 99
    loader = NativeModelLoader(registry_root=reg_root, load_fn=_json_load)
    _assert_raises(ModelLoadError, loader.load)
    assert loader.health_state() == "degraded"


def test_08_registry_vs_checkpoint_config_mismatch_rejected(tmp_path: Path | None = None):
    if tmp_path is None:
        with tempfile.TemporaryDirectory() as td:
            return test_08_registry_vs_checkpoint_config_mismatch_rejected(Path(td))
    reg_root, _, _ = _build_pure_python_registry_fixture(tmp_path, promote=True)
    reg_file = reg_root / "registry.json"
    reg_data = json.loads(reg_file.read_text(encoding="utf-8"))
    reg_data["versions"]["ZYRQUEN-Native-0.1.0"]["model_config"]["n_layers"] = 99
    reg_file.write_text(json.dumps(reg_data), encoding="utf-8")

    loader = NativeModelLoader(registry_root=reg_root, load_fn=_json_load)
    _assert_raises(ModelLoadError, loader.load)


def _require_runtime_deps():
    try:
        import pydantic  # noqa: F401
        import torch
        return torch
    except ImportError:
        return None


def _build_torch_registry_fixture(
    root: Path,
    *,
    version: str = "ZYRQUEN-Native-0.1.0",
    max_seq_len: int = 32,
    force_eos_after_prefix: bool = False,
    step: int = 0,
    metrics: dict | None = None,
) -> tuple[Path, ZyrquenTokenizer, ZyrquenConfig]:
    import torch
    from apps.core.native.model import ZyrquenModel

    src = root / "corpus.jsonl"
    docs = [
        {"text": f"hello world test zyrquen hi sample {i} สวัสดี"}
        for i in range(40)
    ]
    src.write_text(
        "\n".join(json.dumps(doc, ensure_ascii=False) for doc in docs),
        encoding="utf-8",
    )
    ds_dir = root / "dataset"
    prepare_dataset(
        [Source(str(src), "test-fixture")],
        ds_dir,
        PrepConfig(val_fraction=0.1, test_fraction=0.1, version="0.1.0"),
    )

    tok = ZyrquenTokenizer.train(
        [doc["text"] for doc in docs],
        BASE_VOCAB + 24,
        version="0.1.0",
    )
    tok_path = root / "tokenizer.json"
    tok.save(tok_path)

    torch.manual_seed(7)
    cfg = ZyrquenConfig(
        vocab_size=tok.vocab_size,
        max_seq_len=max_seq_len,
        n_layers=2,
        n_heads=2,
        d_model=32,
        d_ff=64,
    )
    model = ZyrquenModel(cfg)
    with torch.no_grad():
        if force_eos_after_prefix:
            model.embed.weight.zero_()
            model.embed.weight[tok.eos_id].fill_(5.0)
            model.final_norm.weight.fill_(1.0)
        else:
            model.embed.weight[:N_SPECIAL].zero_()

    ckpt_dir = root / "checkpoints"
    ckpt_payload = {
        "model": model.state_dict(),
        "step": step,
        "model_config": cfg.to_dict(),
        "tokenizer_sha256": tok.fingerprint(),
        "dataset_version": "0.1.0",
    }
    if step > 0:
        ckpt_payload["config"] = {"max_steps": step}
    CheckpointManager(ckpt_dir).save(step, ckpt_payload)

    reg_root = root / "registry"
    registry = ModelRegistry(reg_root)
    registry.register(version, ckpt_dir, tok_path, ds_dir, metrics=metrics or {})
    registry.promote(version)
    return reg_root, tok, cfg


def test_09_registry_active_version_baseline_not_marked_trained(tmp_path: Path | None = None):
    if _require_runtime_deps() is None:
        return
    if tmp_path is None:
        with tempfile.TemporaryDirectory() as td:
            return test_09_registry_active_version_baseline_not_marked_trained(Path(td))
    from apps.core.runtime import NativeRuntime

    reg_root, tok, cfg = _build_torch_registry_fixture(tmp_path, step=0, metrics={})
    loader = NativeModelLoader(registry_root=reg_root)
    rt = NativeRuntime(loader=loader)
    assert rt.initialize() is True
    assert loader.model_version == "ZYRQUEN-Native-0.1.0"
    assert loader.is_trained is False
    assert loader.evidence["capability_status"] == "untrained_baseline"
    assert loader.tokenizer_sha256 == tok.fingerprint()
    assert loader.model_config == cfg
    health = rt.get_health_status()
    assert health["runtime_status"] == "ready"
    assert health["is_trained"] is False
    assert health["max_seq_len"] == 32


def test_10_standalone_native_artifact_dir_loads_with_manifest(tmp_path: Path | None = None):
    if _require_runtime_deps() is None:
        return
    if tmp_path is None:
        with tempfile.TemporaryDirectory() as td:
            return test_10_standalone_native_artifact_dir_loads_with_manifest(Path(td))

    reg_root, tok, cfg = _build_torch_registry_fixture(tmp_path)
    art_dir = reg_root / "artifacts" / "ZYRQUEN-Native-0.1.0"
    ds_manifest = json.loads((art_dir / "dataset_manifest.json").read_text(encoding="utf-8"))
    (art_dir / "artifact_manifest.json").write_text(
        json.dumps(
            {
                "schema": ARTIFACT_MANIFEST_SCHEMA,
                "model_version": "ZYRQUEN-Native-0.1.0",
                "checkpoint": {
                    "file": "checkpoint.pt",
                    "sha256": _sha256_bytes(art_dir / "checkpoint.pt"),
                    "step": 0,
                },
                "tokenizer": {
                    "file": "tokenizer.json",
                    "sha256": tok.fingerprint(),
                    "file_sha256": _sha256_bytes(art_dir / "tokenizer.json"),
                },
                "dataset": {
                    "version": ds_manifest["version"],
                    "content_sha256": ds_manifest["content_sha256"],
                    "manifest_file": "dataset_manifest.json",
                },
                "model_config": cfg.to_dict(),
                "metrics": {},
            }
        ),
        encoding="utf-8",
    )

    loader = NativeModelLoader(model_path=art_dir)
    loader.load()
    assert loader.is_ready() is True
    assert loader.artifact_origin == "native_artifact_dir"
    assert loader.model_version == "ZYRQUEN-Native-0.1.0"


def test_11_native_inference_and_token_counting(tmp_path: Path | None = None):
    if _require_runtime_deps() is None:
        return
    if tmp_path is None:
        with tempfile.TemporaryDirectory() as td:
            return test_11_native_inference_and_token_counting(Path(td))
    from apps.core.context import InferenceContext
    from apps.core.inference import NativeInferenceEngine

    reg_root, tok, _ = _build_torch_registry_fixture(tmp_path)
    loader = NativeModelLoader(registry_root=reg_root)
    loader.load()
    engine = NativeInferenceEngine(loader)

    prompt = "hello world สวัสดี"
    expected_in = len(tok.encode(prompt))
    assert engine.count_tokens(prompt) == expected_in

    ctx = InferenceContext(
        user_id="00000000-0000-0000-0000-000000000001",
        prompt=prompt,
        max_tokens=5,
        temperature=0.0,
    )
    res = asyncio.run(engine.generate_with_usage(ctx))
    assert res.input_tokens == expected_in
    assert 1 <= res.output_tokens <= 5
    assert res.model_version == "ZYRQUEN-Native-0.1.0"
    assert res.text.strip() != ""


def test_12_streaming_stops_at_eos(tmp_path: Path | None = None):
    if _require_runtime_deps() is None:
        return
    if tmp_path is None:
        with tempfile.TemporaryDirectory() as td:
            return test_12_streaming_stops_at_eos(Path(td))
    from apps.core.context import InferenceContext
    from apps.core.streaming import StreamingInferenceEngine

    reg_root, tok, _ = _build_torch_registry_fixture(
        tmp_path,
        force_eos_after_prefix=True,
    )
    loader = NativeModelLoader(registry_root=reg_root)
    loader.load()
    stream_engine = StreamingInferenceEngine(loader)

    ctx = InferenceContext(
        user_id="00000000-0000-0000-0000-000000000001",
        prompt="hello",
        max_tokens=6,
        temperature=0.0,
    )

    async def collect():
        return [chunk async for chunk in stream_engine.stream(ctx)]

    chunks = asyncio.run(collect())
    assert len(chunks) == 1
    assert chunks[0].is_final is True
    assert chunks[0].output_tokens == 0
    assert chunks[0].input_tokens == len(tok.encode("hello"))


def test_13_context_window_boundary(tmp_path: Path | None = None):
    if _require_runtime_deps() is None:
        return
    if tmp_path is None:
        with tempfile.TemporaryDirectory() as td:
            return test_13_context_window_boundary(Path(td))
    from apps.core.context import InferenceContext
    from apps.core.inference import NativeInferenceEngine
    from apps.core.streaming import StreamingInferenceEngine

    reg_root, tok, cfg = _build_torch_registry_fixture(tmp_path, max_seq_len=16)
    loader = NativeModelLoader(registry_root=reg_root)
    loader.load()
    engine = NativeInferenceEngine(loader)
    stream_engine = StreamingInferenceEngine(loader)

    exact_prompt = ""
    for ch in "abcdefghijklmnopqrstuvwxyz":
        cand = exact_prompt + ch
        if len(tok.encode(cand)) <= cfg.max_seq_len:
            exact_prompt = cand
        if len(tok.encode(exact_prompt)) == cfg.max_seq_len:
            break
    assert len(tok.encode(exact_prompt)) == cfg.max_seq_len

    boundary_ctx = InferenceContext(
        user_id="00000000-0000-0000-0000-000000000001",
        prompt=exact_prompt,
        max_tokens=4,
        temperature=0.0,
    )
    boundary_res = asyncio.run(engine.generate_with_usage(boundary_ctx))
    assert boundary_res.input_tokens == cfg.max_seq_len
    assert boundary_res.output_tokens >= 1

    overflow_prompt = exact_prompt + "!"
    assert len(tok.encode(overflow_prompt)) > cfg.max_seq_len
    overflow_ctx = InferenceContext(
        user_id="00000000-0000-0000-0000-000000000001",
        prompt=overflow_prompt,
        max_tokens=2,
        temperature=0.0,
    )
    _assert_raises(ResourceLimitExceeded, asyncio.run, engine.execute(overflow_ctx))

    async def run_stream_overflow():
        async for _ in stream_engine.stream(overflow_ctx):
            pass

    _assert_raises(ResourceLimitExceeded, asyncio.run, run_stream_overflow())


def test_14_symlink_and_path_traversal_rejected(tmp_path: Path | None = None):
    if tmp_path is None:
        with tempfile.TemporaryDirectory() as td:
            return test_14_symlink_and_path_traversal_rejected(Path(td))
    import os

    reg_root, _, _ = _build_pure_python_registry_fixture(tmp_path / "sym", promote=True)
    ckpt_file = reg_root / "artifacts" / "ZYRQUEN-Native-0.1.0" / "checkpoint.pt"
    outside = tmp_path / "outside.pt"
    outside.write_bytes(ckpt_file.read_bytes())
    ckpt_file.unlink()
    os.symlink(outside, ckpt_file)

    loader = NativeModelLoader(registry_root=reg_root, load_fn=_json_load)
    _assert_raises(ModelLoadError, loader.load)
    assert loader.health_state() == "degraded"

    reg_root2, _, _ = _build_pure_python_registry_fixture(tmp_path / "trav", promote=True)
    reg_file2 = reg_root2 / "registry.json"
    reg_data2 = json.loads(reg_file2.read_text(encoding="utf-8"))
    reg_data2["versions"]["ZYRQUEN-Native-0.1.0"]["checkpoint"]["path"] = "../../outside.pt"
    reg_file2.write_text(json.dumps(reg_data2), encoding="utf-8")

    loader2 = NativeModelLoader(registry_root=reg_root2, load_fn=_json_load)
    _assert_raises(ModelLoadError, loader2.load)
    assert loader2.health_state() == "degraded"


def test_15_safe_torch_load_uses_weights_only_true():
    import inspect
    from apps.core.model_loader import _safe_torch_load

    source = inspect.getsource(_safe_torch_load)
    assert "weights_only=True" in source
    loader = NativeModelLoader()
    assert loader._load_fn is _safe_torch_load


def test_16_checkpoint_dataset_version_mismatch_rejected(tmp_path: Path | None = None):
    if tmp_path is None:
        with tempfile.TemporaryDirectory() as td:
            return test_16_checkpoint_dataset_version_mismatch_rejected(Path(td))
    reg_root, _, _ = _build_pure_python_registry_fixture(tmp_path, promote=True)
    reg_file = reg_root / "registry.json"
    reg_data = json.loads(reg_file.read_text(encoding="utf-8"))
    reg_data["versions"]["ZYRQUEN-Native-0.1.0"]["dataset"]["version"] = "9.9.9"
    reg_file.write_text(json.dumps(reg_data), encoding="utf-8")

    loader = NativeModelLoader(registry_root=reg_root, load_fn=_json_load)
    _assert_raises(ModelLoadError, loader.load)
    assert loader.health_state() == "degraded"


def test_17_atomic_version_reservation_and_multiprocess_concurrency(tmp_path: Path | None = None):
    if tmp_path is None:
        with tempfile.TemporaryDirectory() as td:
            return test_17_atomic_version_reservation_and_multiprocess_concurrency(Path(td))
    import subprocess
    from concurrent.futures import ThreadPoolExecutor
    from apps.core.native.registry import ModelRegistry, RegistryError

    src = tmp_path / "corpus.jsonl"
    docs = [{"text": f"hello world zyrquen concurrency {i}"} for i in range(40)]
    src.write_text("\n".join(json.dumps(d) for d in docs), encoding="utf-8")
    ds_dir = tmp_path / "dataset"
    prepare_dataset([Source(str(src), "test-fixture")], ds_dir, PrepConfig(val_fraction=0.1, test_fraction=0.1, version="0.1.0"))
    tok = ZyrquenTokenizer.train([d["text"] for d in docs], BASE_VOCAB + 24, version="0.1.0")
    tok_path = tmp_path / "tokenizer.json"
    tok.save(tok_path)
    cfg = ZyrquenConfig(vocab_size=tok.vocab_size, max_seq_len=32, n_layers=2, n_heads=2, d_model=32, d_ff=64)
    ckpt_dir = tmp_path / "checkpoints"
    CheckpointManager(ckpt_dir, save_fn=_json_save, load_fn=_json_load).save(
        1,
        {
            "model": {"embed.weight": [[0.0]]},
            "step": 1,
            "config": {"max_steps": 1},
            "model_config": cfg.to_dict(),
            "tokenizer_sha256": tok.fingerprint(),
            "dataset_version": "0.1.0",
        },
    )

    reg_root = tmp_path / "registry"
    reg = ModelRegistry(reg_root, load_fn=_json_load)
    res0 = reg.reserve_next_native_version(training_run_id="run-0")
    assert res0.version == "ZYRQUEN-Native-0.1.0"
    _assert_raises(RegistryError, reg.register, res0.version, ckpt_dir, tok_path, ds_dir)
    _assert_raises(RegistryError, reg.register, res0.version, ckpt_dir, tok_path, ds_dir, reservation_token="bad")
    assert reg.release_reservation(res0.version, res0.token) is True

    def thread_worker(idx: int):
        worker_reg = ModelRegistry(reg_root, load_fn=_json_load)
        return worker_reg.register_next_native_version(
            ckpt_dir,
            tok_path,
            ds_dir,
            notes=f"training_run_id=thread-{idx}",
            training_run_id=f"thread-{idx}",
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        thread_records = list(pool.map(thread_worker, range(4)))
    assert sorted(r["version"] for r in thread_records) == [
        "ZYRQUEN-Native-0.1.0",
        "ZYRQUEN-Native-0.1.1",
        "ZYRQUEN-Native-0.1.2",
        "ZYRQUEN-Native-0.1.3",
    ]

    # Real multi-process OS concurrency via subprocess workers sharing the same registry root.
    worker_code = (
        "import json, sys; from pathlib import Path; "
        "from apps.core.native.registry import ModelRegistry; "
        "load = lambda p: json.loads(Path(p).read_text(encoding='utf-8')); "
        "r = ModelRegistry(sys.argv[1], load_fn=load); "
        "rec = r.register_next_native_version(sys.argv[2], sys.argv[3], sys.argv[4], notes=f'training_run_id=proc-{sys.argv[5]}', training_run_id=f'proc-{sys.argv[5]}'); "
        "print(rec['version'])"
    )
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", worker_code, str(reg_root), str(ckpt_dir), str(tok_path), str(ds_dir), str(i)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for i in range(4)
    ]
    proc_versions = []
    for p in procs:
        out, err = p.communicate(timeout=20)
        assert p.returncode == 0, f"subprocess failed: {err}"
        proc_versions.append(out.strip())

    all_versions = [r["version"] for r in thread_records] + proc_versions
    assert sorted(all_versions) == [f"ZYRQUEN-Native-0.1.{i}" for i in range(8)]
    assert reg.active_version() is None
    for i, ver in enumerate(sorted(all_versions)):
        assert reg.verify(ver)
        expected_parent = None if i == 0 else f"ZYRQUEN-Native-0.1.{i - 1}"
        assert reg.get(ver)["parent"] == expected_parent


def test_18_train_checkpoint_payload_loads_with_weights_only_true(tmp_path: Path | None = None):
    if tmp_path is None:
        with tempfile.TemporaryDirectory() as td:
            return test_18_train_checkpoint_payload_loads_with_weights_only_true(Path(td))
    import random
    import torch
    from apps.core.native.model import ZyrquenModel
    from apps.core.native.registry import ModelRegistry
    from apps.core.native.train import TrainConfig
    from apps.core.training_infrastructure.recovery.checkpoint_recovery import capture_rng_state

    src = tmp_path / "corpus.jsonl"
    docs = [{"text": f"hello world zyrquen checkpoint payload {i}"} for i in range(40)]
    src.write_text("\n".join(json.dumps(d) for d in docs), encoding="utf-8")
    ds_dir = tmp_path / "dataset"
    prepare_dataset([Source(str(src), "test-fixture")], ds_dir, PrepConfig(val_fraction=0.1, test_fraction=0.1, version="0.1.0"))
    tok = ZyrquenTokenizer.train([d["text"] for d in docs], BASE_VOCAB + 24, version="0.1.0")
    tok_path = tmp_path / "tokenizer.json"
    tok.save(tok_path)

    cfg = ZyrquenConfig(vocab_size=tok.vocab_size, max_seq_len=32, n_layers=2, n_heads=2, d_model=32, d_ff=64)
    model = ZyrquenModel(cfg)
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
    tcfg = TrainConfig(block_size=16, batch_size=2, max_steps=10, warmup_steps=2)
    rng = random.Random(tcfg.seed)

    ckpt_dir = tmp_path / "checkpoints"
    CheckpointManager(ckpt_dir).save(
        1,
        {
            "model": model.state_dict(),
            "optimizer": optimizer.state_dict(),
            "step": 1,
            "batch_rng": rng.getstate(),
            "rng": capture_rng_state(),
            "config": tcfg.__dict__,
            "model_config": model.cfg.to_dict(),
            "tokenizer_sha256": tok.fingerprint(),
            "dataset_version": "0.1.0",
        },
    )

    reg_root = tmp_path / "registry"
    registry = ModelRegistry(reg_root)
    record = registry.register_next_native_version(
        ckpt_dir, tok_path, ds_dir, metrics={"val_loss": 2.5}, notes="train-format-check"
    )
    registry.promote(record["version"])

    loader = NativeModelLoader(registry_root=reg_root)
    loader.load()
    assert loader.is_ready() is True
    assert loader.model_version == "ZYRQUEN-Native-0.1.0"
    assert loader.is_trained is True


def test_19_checkpoint_recovery_security_boundary_and_rng_resume(tmp_path: Path | None = None):
    if tmp_path is None:
        with tempfile.TemporaryDirectory() as td:
            return test_19_checkpoint_recovery_security_boundary_and_rng_resume(Path(td))
    import inspect
    import os
    import random
    from apps.core.native.registry import ModelRegistry
    from apps.core.training_infrastructure.recovery.checkpoint_recovery import (
        CheckpointManager,
        _safe_torch_load,
        capture_rng_state,
        restore_rng_state,
    )

    mgr = CheckpointManager(tmp_path / "default")
    assert mgr._load is _safe_torch_load
    assert mgr._allow_unsafe_pickle is False
    assert "weights_only=True" in inspect.getsource(_safe_torch_load)

    reg = ModelRegistry(tmp_path / "reg")
    assert reg._load is _safe_torch_load

    called = []
    sym_mgr = CheckpointManager(
        tmp_path / "sym",
        save_fn=_json_save,
        load_fn=lambda p: called.append(p) or _json_load(p),
    )
    ckpt = sym_mgr.save(1, {"step": 1})
    outside = tmp_path / "outside.pt"
    outside.write_bytes(ckpt.read_bytes())
    ckpt.unlink()
    os.symlink(outside, ckpt)
    assert sym_mgr.latest_valid() is None
    assert sym_mgr.load_latest() is None
    assert called == []

    rng_state = capture_rng_state()
    expected = random.random()
    restore_rng_state(rng_state)
    assert random.random() == expected
    v, internal, gauss = rng_state["python"]
    restore_rng_state({"python": [v, list(internal), gauss]})
    assert random.random() == expected


def test_20_phase10_8_config_and_dependency_remediation():
    import ast
    import inspect

    repo_root = Path(__file__).resolve().parents[2]
    compose_text = (repo_root / "docker-compose.yml").read_text(encoding="utf-8")
    assert "ZYRQUEN_MODEL_PATH" not in compose_text
    assert "ZYRQUEN_MODEL_REGISTRY_ROOT" in compose_text

    req_lines = [
        line.strip().lower()
        for line in (repo_root / "apps" / "api" / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert "transformers" not in req_lines
    assert "tokenizers" not in req_lines

    ops_path = repo_root / "apps" / "api" / "operations.py"
    ops_tree = ast.parse(ops_path.read_text(encoding="utf-8"), filename=str(ops_path))
    imported = {
        alias.asname or alias.name
        for node in ast.walk(ops_tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert "JSONResponse" in imported
    called_names = {
        node.func.id
        for node in ast.walk(ops_tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "JSONResponse" in called_names


if __name__ == "__main__":
    pure_tests = [
        test_01_not_configured_when_env_unset_and_missing_registry,
        test_02_registry_without_active_version_is_not_configured,
        test_03_non_native_artifact_directory_rejected_as_degraded,
        test_04_semantic_version_format_enforced,
        test_05_checkpoint_sha256_tamper_rejected,
        test_06_tokenizer_fingerprint_tamper_rejected,
        test_07_config_vocab_size_mismatch_rejected,
        test_08_registry_vs_checkpoint_config_mismatch_rejected,
        test_14_symlink_and_path_traversal_rejected,
        test_15_safe_torch_load_uses_weights_only_true,
        test_16_checkpoint_dataset_version_mismatch_rejected,
        test_17_atomic_version_reservation_and_multiprocess_concurrency,
        test_19_checkpoint_recovery_security_boundary_and_rng_resume,
        test_20_phase10_8_config_and_dependency_remediation,
    ]
    torch_tests = [
        test_09_registry_active_version_baseline_not_marked_trained,
        test_10_standalone_native_artifact_dir_loads_with_manifest,
        test_11_native_inference_and_token_counting,
        test_12_streaming_stops_at_eos,
        test_13_context_window_boundary,
        test_18_train_checkpoint_payload_loads_with_weights_only_true,
    ]
    passed = 0
    skipped = 0
    for fn in pure_tests:
        fn()
        passed += 1
    if _require_runtime_deps() is not None:
        for fn in torch_tests:
            fn()
            passed += 1
    else:
        skipped = len(torch_tests)
    print(f"test_native_runtime: passed={passed} skipped_no_runtime_deps={skipped}")
    sys.exit(0)
