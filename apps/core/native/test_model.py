import pytest

torch = pytest.importorskip("torch")

from apps.core.native.config import ZyrquenConfig
from apps.core.native.model import ZyrquenModel

CFG = ZyrquenConfig(vocab_size=64, max_seq_len=32, n_layers=2, n_heads=2, d_model=32, d_ff=64)


def test_forward_shape_and_loss():
    model = ZyrquenModel(CFG)
    ids = torch.randint(0, 64, (2, 16))
    logits, loss = model(ids, ids)
    assert logits.shape == (2, 16, 64)
    assert loss is not None and torch.isfinite(loss)


def test_causality():
    model = ZyrquenModel(CFG).eval()
    a = torch.randint(0, 64, (1, 16))
    b = a.clone()
    b[0, -1] = (b[0, -1] + 1) % 64
    la, _ = model(a)
    lb, _ = model(b)
    assert torch.allclose(la[:, :-1], lb[:, :-1], atol=1e-5)


def test_generate_length():
    model = ZyrquenModel(CFG)
    out = model.generate(torch.randint(0, 64, (1, 4)), max_new_tokens=5, temperature=0)
    assert out.shape == (1, 9)


def test_overfits_tiny_batch():
    torch.manual_seed(0)
    model = ZyrquenModel(CFG)
    ids = torch.randint(0, 64, (4, 16))
    opt = torch.optim.AdamW(model.parameters(), lr=3e-3)
    first = model(ids, ids)[1].item()
    for _ in range(60):
        opt.zero_grad()
        loss = model(ids, ids)[1]
        loss.backward()
        opt.step()
    assert loss.item() < first * 0.5


def test_config_validation():
    with pytest.raises(ValueError):
        ZyrquenConfig(d_model=30, n_heads=4)


def test_default_config_is_within_initial_parameter_target():
    model = ZyrquenModel(ZyrquenConfig())
    assert 1_000_000 <= model.num_parameters() <= 5_000_000
    assert model.num_parameters() == model.cfg.estimated_num_parameters
