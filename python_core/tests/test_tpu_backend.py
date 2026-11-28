from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from unittest import mock

PYTHON_CORE = Path(__file__).resolve().parents[1]
REPO_ROOT = PYTHON_CORE.parent
for p in (str(PYTHON_CORE), str(REPO_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from tools.tpu_probe import detect_runtime_accelerator
from v2 import tpu_backend


class FakeDevice(str):
    pass


class TpuBackendTests(unittest.TestCase):
    def test_resolve_prefers_torch_tpu_when_available(self) -> None:
        fake_tpu = types.SimpleNamespace(
            is_available=lambda: True,
            device_count=lambda: 1,
            synchronize=mock.MagicMock(),
        )
        fake_torch = types.SimpleNamespace(
            tpu=fake_tpu,
            cuda=types.SimpleNamespace(is_available=lambda: False),
            device=lambda name: FakeDevice(name),
        )
        with mock.patch.object(tpu_backend, "_import_torch", return_value=fake_torch):
            dev = tpu_backend.resolve_torch_device()
            self.assertEqual(str(dev), "tpu")
            self.assertTrue(tpu_backend.is_tpu_device(dev))
            tpu_backend.tpu_sync_step(dev)
            fake_tpu.synchronize.assert_called_once()

    def test_resolve_falls_back_to_cuda_then_cpu(self) -> None:
        fake_torch_cuda = types.SimpleNamespace(
            cuda=types.SimpleNamespace(is_available=lambda: True),
            device=lambda name: FakeDevice(name),
        )
        with mock.patch.dict(sys.modules, {"torch_xla": None, "torch_xla.core": None, "torch_xla.core.xla_model": None}):
            with mock.patch.object(tpu_backend, "_import_torch", return_value=fake_torch_cuda):
                dev = tpu_backend.resolve_torch_device()
                self.assertEqual(str(dev), "cuda")
                self.assertFalse(tpu_backend.is_tpu_device(dev))

        fake_torch_cpu = types.SimpleNamespace(
            cuda=types.SimpleNamespace(is_available=lambda: False),
            device=lambda name: FakeDevice(name),
        )
        with mock.patch.dict(sys.modules, {"torch_xla": None, "torch_xla.core": None, "torch_xla.core.xla_model": None}):
            with mock.patch.object(tpu_backend, "_import_torch", return_value=fake_torch_cpu):
                dev = tpu_backend.resolve_torch_device()
                self.assertEqual(str(dev), "cpu")

    def test_resolve_supports_torch_xla_when_tpu_unavailable(self) -> None:
        fake_xm = types.SimpleNamespace(
            xla_device=lambda: FakeDevice("xla:0"),
            mark_step=mock.MagicMock(),
        )
        fake_torch = types.SimpleNamespace(
            cuda=types.SimpleNamespace(is_available=lambda: False),
            device=lambda name: FakeDevice(name),
        )
        fake_torch_xla = types.ModuleType("torch_xla")
        fake_core = types.ModuleType("torch_xla.core")
        fake_core.xla_model = fake_xm
        fake_torch_xla.core = fake_core
        with mock.patch.dict(
            sys.modules,
            {
                "torch_xla": fake_torch_xla,
                "torch_xla.core": fake_core,
                "torch_xla.core.xla_model": fake_xm,
            },
        ):
            with mock.patch.object(tpu_backend, "_import_torch", return_value=fake_torch):
                dev = tpu_backend.resolve_torch_device()
                self.assertEqual(str(dev), "xla:0")
                self.assertTrue(tpu_backend.is_tpu_device(dev))
                tpu_backend.tpu_sync_step(dev)
                fake_xm.mark_step.assert_called_once()

    def test_state_dict_to_cpu_detaches_tensors(self) -> None:
        class FakeTensor:
            def __init__(self, val: int) -> None:
                self.val = val
                self.moved = False

            def detach(self):
                return self

            def cpu(self):
                self.moved = True
                return self

        t = FakeTensor(1)
        out = tpu_backend.state_dict_to_cpu({"w": t, "meta": "ok"})
        self.assertTrue(out["w"].moved)
        self.assertEqual(out["meta"], "ok")

    def test_tpu_suite_pure_native_smoke(self) -> None:
        from tools.tpu_suite import run_pure_native_smoke

        res = run_pure_native_smoke()
        self.assertTrue(res["passed"])
        self.assertEqual(res["global_step"], 2)

    def test_tpu_probe_reports_env_pjrt_tpu(self) -> None:
        with mock.patch.dict("os.environ", {"PJRT_DEVICE": "TPU", "TPU_ACCELERATOR_TYPE": "v5e-1"}, clear=False):
            info = detect_runtime_accelerator()
            self.assertEqual(info["accelerator"], "TPU")
            self.assertEqual(info["tpu_accelerator_type"], "v5e-1")
            self.assertTrue(info["pure_native_v2_ready"])

    def test_tpu_probe_survives_xla_abi_mismatch(self) -> None:
        class BrokenXla(types.ModuleType):
            def __getattr__(self, name: str):
                raise ImportError("_XLAC.cpython-313-x86_64-linux-gnu.so: undefined symbol")

        fake_torch = types.SimpleNamespace(
            __version__="2.14.1+cpu",
            cuda=types.SimpleNamespace(is_available=lambda: False),
        )
        broken_mod = BrokenXla("torch_xla")
        with mock.patch.dict(
            sys.modules,
            {
                "torch": fake_torch,
                "torch_xla": broken_mod,
                "torch_xla.runtime": broken_mod,
                "torch_xla.core": broken_mod,
                "torch_xla.core.xla_model": broken_mod,
            },
        ):
            info = detect_runtime_accelerator()
            self.assertEqual(info["torch_version"], "2.14.1+cpu")
            self.assertIn("ImportError", info["xla_error"])
            self.assertTrue(info["pure_native_v2_ready"])

    def test_load_texts_supports_dict_and_gzip(self) -> None:
        import gzip
        import json
        import tempfile
        from tools.resume_v2_lab import load_texts_from_file

        with tempfile.TemporaryDirectory() as tmp:
            p1 = Path(tmp) / "independent_eval_v1.json"
            p1.write_text(json.dumps({"name": "eval", "texts": ["alpha", "beta"]}), encoding="utf-8")
            self.assertEqual(load_texts_from_file(p1), ["alpha", "beta"])

            p2 = Path(tmp) / "transfer.json.gz"
            with gzip.open(p2, "wt", encoding="utf-8") as fh:
                json.dump({"train": [{"text": "t1"}], "val": [{"text": "v1"}]}, fh)
            self.assertEqual(load_texts_from_file(p2, split="val"), ["v1"])
            self.assertEqual(load_texts_from_file(p2, split="train"), ["t1"])


if __name__ == "__main__":
    unittest.main()
