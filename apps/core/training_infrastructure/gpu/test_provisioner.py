# Phase 4.1 - ของจริงเท่านั้น ห้ามจำลอง
# ไม่มี runner ปลอม ไม่มี GPU ปลอม ไม่มี Machine สร้างเอง
from apps.core.training_infrastructure.gpu.provisioner import LocalProvider, ProvisioningError
from apps.core.training_infrastructure.gpu.resource_manager import ResourceManager

def test_real_list_gpus():
    gpus = ResourceManager().list_gpus()
    assert isinstance(gpus, list)
    for g in gpus:
        assert g.memory_total_mb >= g.memory_used_mb
        assert g.memory_total_mb >= 0

def test_real_select_device_matches_list():
    rm = ResourceManager()
    if rm.list_gpus():
        assert rm.select_device() == "cuda"
    else:
        assert rm.select_device() == "cpu"

def test_real_free_memory():
    rm = ResourceManager()
    for g in rm.list_gpus():
        assert rm.free_memory_mb(g.index) == g.memory_total_mb - g.memory_used_mb
    assert rm.free_memory_mb(9999) is None

def test_real_provision_and_release_only_if_real_gpu():
    rm = ResourceManager()
    p = LocalProvider(resources=rm, min_gpus=1)
    try:
        m = p.provision()
    except ProvisioningError:
        assert rm.list_gpus() == []
        return
    assert m.provider == "local"
    assert m.status == "ready"
    assert len(m.gpus) >= 1
    r = p.release(m)
    assert r.status == "released"
    assert r.gpus == m.gpus
