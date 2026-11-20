# Phase 4.2 - ของจริงเท่านั้น ห้ามจำลอง
# ไม่มี env ปลอม ไม่มี WORLD_SIZE ปลอม ไม่มี process group ปลอม
# ใช้ os.environ จริงบนเครื่องนี้เท่านั้น
import os
from apps.core.training_infrastructure.distributed.trainer import DistConfig, init_distributed, shutdown_distributed

def test_real_default_config():
    cfg = DistConfig()
    assert cfg.rank == 0
    assert cfg.world_size == 1
    assert cfg.local_rank == 0
    assert cfg.is_distributed is False
    assert cfg.is_main is True

def test_real_from_env_matches_machine():
    cfg = DistConfig.from_env()
    assert cfg.rank == int(os.environ.get("RANK", 0))
    assert cfg.world_size == int(os.environ.get("WORLD_SIZE", 1))
    assert cfg.local_rank == int(os.environ.get("LOCAL_RANK", 0))
    assert cfg.is_distributed == (cfg.world_size > 1)
    assert cfg.is_main == (cfg.rank == 0)

def test_real_init_shutdown_single_process_noop():
    cfg = DistConfig.from_env()
    # บนเครื่องนี้ single-process ต้อง return เฉยๆ ห้ามสร้าง process group จริง
    assert init_distributed(cfg) is None
    assert shutdown_distributed(cfg) is None

def test_real_config_logic_from_real_cfg():
    cfg = DistConfig.from_env()
    assert cfg.is_distributed == (cfg.world_size > 1)
    assert cfg.is_main == (cfg.rank == 0)
