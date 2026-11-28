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


if __name__ == "__main__":
    unittest.main()
