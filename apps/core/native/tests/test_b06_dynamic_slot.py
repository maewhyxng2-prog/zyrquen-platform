"""B-06 regression tests for ephemeral slots and stage-aware sampling.

The StageAwareSampler tests define the public contract required by B-06.
They intentionally fail until the sampler is implemented in native/train.py.
No test in this module starts training or imports PyTorch.
"""

import random

import pytest

from apps.core.native import train as train_module
from apps.core.native.sft import bind_ephemeral_slots, restore_ephemeral_slots


def test_dynamic_slots_bind_prompt_and_target_consistently():
    prompt = "Connect TR_E00001 to node_tr_00002, then revisit TR_E00001."
    target = "The result is node_tr_00002 via TR_E00001."

    bound_prompt, bound_target, binding = bind_ephemeral_slots(
        prompt, target, permute_slots=False
    )

    assert bound_prompt.count("<slot_0>") == 2
    assert "<slot_1>" in bound_prompt
    assert bound_target is not None
    assert bound_target == "The result is <slot_1> via <slot_0>."
    assert binding.surface_to_slot == {
        "TR_E00001": "<slot_0>",
        "node_tr_00002": "<slot_1>",
    }
    assert restore_ephemeral_slots(bound_prompt, binding) == prompt
    assert restore_ephemeral_slots(bound_target, binding) == target


def test_dynamic_slots_are_ephemeral_and_seed_reproducible():
    prompt = "TR_E00001 relates to VA_E00002 and OO_E00003."

    first = bind_ephemeral_slots(
        prompt, permute_slots=True, rng=random.Random(1337)
    )
    second = bind_ephemeral_slots(
        prompt, permute_slots=True, rng=random.Random(1337)
    )
    third = bind_ephemeral_slots(
        prompt, permute_slots=True, rng=random.Random(2026)
    )

    assert first == second
    assert first[0] != third[0]
    assert set(first[2].surface_to_slot.values()).issubset(
        {f"<slot_{index}>" for index in range(32)}
    )


def test_dynamic_slots_do_not_rewrite_unrecognized_identifiers():
    prompt = "TR_E00001 is linked to USER_DEFINED_42 and node_tr_00002."
    bound, _, binding = bind_ephemeral_slots(prompt)

    assert "USER_DEFINED_42" in bound
    assert "TR_E00001" not in bound
    assert "node_tr_00002" not in bound
    assert len(binding.surface_to_slot) == 2


def test_dynamic_slots_reject_capacity_overflow():
    prompt = "TR_E00001 and TR_E00002 and TR_E00003"
    with pytest.raises(ValueError, match="slot capacity"):
        bind_ephemeral_slots(prompt, max_slots=2)


def _stage_sampler():
    sampler_type = getattr(train_module, "StageAwareSampler", None)
    assert sampler_type is not None, (
        "B-06 gap: apps.core.native.train.StageAwareSampler is not implemented"
    )
    return sampler_type


def _records():
    return [
        {"id": "a1", "stage_tag": "stage_1_foundation"},
        {"id": "a2", "stage_tag": "stage_1_foundation"},
        {"id": "b1", "stage_tag": "stage_2_relational"},
        {"id": "c1", "stage_tag": "stage_3_planning"},
    ]


def test_stage_sampler_is_deterministic_for_same_seed():
    sampler_type = _stage_sampler()
    weights = {
        "stage_1_foundation": 1.0,
        "stage_2_relational": 2.0,
        "stage_3_planning": 3.0,
    }

    left = sampler_type(_records(), stage_weights=weights, seed=1337)
    right = sampler_type(_records(), stage_weights=weights, seed=1337)

    assert left.sample_indices(64) == right.sample_indices(64)


def test_stage_sampler_respects_stage_weights_statistically():
    sampler_type = _stage_sampler()
    weights = {
        "stage_1_foundation": 1.0,
        "stage_2_relational": 3.0,
        "stage_3_planning": 0.0,
    }
    sampler = sampler_type(_records(), stage_weights=weights, seed=7)

    indices = sampler.sample_indices(6000)
    assert len(indices) == 6000
    assert all(0 <= index < len(_records()) for index in indices)

    # The third stage is explicitly disabled; the 1:3 stage ratio should
    # remain approximately 25%:75%, regardless of per-stage record counts.
    stage_counts = {"stage_1_foundation": 0, "stage_2_relational": 0}
    rows = _records()
    for index in indices:
        stage_counts[rows[index]["stage_tag"]] += 1
    total = sum(stage_counts.values())
    assert total == len(indices)
    assert stage_counts["stage_1_foundation"] / total == pytest.approx(
        0.25, abs=0.04
    )
    assert stage_counts["stage_2_relational"] / total == pytest.approx(
        0.75, abs=0.04
    )
    assert not any(rows[index]["stage_tag"] == "stage_3_planning" for index in indices)


def test_stage_sampler_rejects_unknown_stages_and_invalid_weights():
    sampler_type = _stage_sampler()

    with pytest.raises(ValueError, match="stage"):
        sampler_type(
            _records(),
            stage_weights={"stage_1_foundation": 1.0},
            seed=1,
        )

    with pytest.raises(ValueError, match="weight"):
        sampler_type(
            _records(),
            stage_weights={
                "stage_1_foundation": -1.0,
                "stage_2_relational": 1.0,
                "stage_3_planning": 1.0,
            },
            seed=1,
        )


def test_stage_sampler_rejects_empty_or_zero_probability_configuration():
    sampler_type = _stage_sampler()

    with pytest.raises(ValueError):
        sampler_type([], stage_weights={}, seed=1)

    with pytest.raises(ValueError, match="positive"):
        sampler_type(
            _records(),
            stage_weights={
                "stage_1_foundation": 0.0,
                "stage_2_relational": 0.0,
                "stage_3_planning": 0.0,
            },
            seed=1,
        )
