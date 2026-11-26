"""Deterministic stage-aware sampler with configuration validation for native training workflows."""

from __future__ import annotations

import bisect
import math
import random
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any


def _is_valid_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_valid_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _validate_stage_name(name: Any, *, label: str = "stage name") -> str:
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return name


def validate_stage_weights(stage_weights: Mapping[str, float]) -> dict[str, float]:
    """Validate and copy stage weights.

    Ensures weights are finite, non-negative real numbers (excluding bool),
    stage names are non-empty strings, and total weight is strictly positive.
    """
    if not isinstance(stage_weights, Mapping) or not stage_weights:
        raise ValueError("stage_weights must be a non-empty mapping")

    validated: dict[str, float] = {}
    for raw_stage, raw_weight in stage_weights.items():
        stage = _validate_stage_name(raw_stage, label="stage name")
        if not _is_valid_number(raw_weight):
            raise ValueError(
                f"stage weight for {stage!r} must be a real number, not {type(raw_weight).__name__}"
            )
        weight = float(raw_weight)
        if not math.isfinite(weight):
            raise ValueError(f"stage weight for {stage!r} must be finite")
        if weight < 0.0:
            raise ValueError(f"stage weight for {stage!r} must be non-negative")
        validated[stage] = weight

    if sum(validated.values()) <= 0.0:
        raise ValueError("total stage weight across stages must be positive")

    return validated


@dataclass(frozen=True)
class StageSamplerConfig:
    """Validated configuration for `StageAwareSampler`."""

    stage_weights: dict[str, float]
    seed: int = 0
    num_samples: int | None = None
    replacement: bool = True
    stage_key: str = "stage"
    batch_size: int | None = None
    drop_last: bool = False
    allow_unconfigured_stages: bool = False
    allow_empty_stages: bool = False

    def __post_init__(self) -> None:
        validated_weights = validate_stage_weights(self.stage_weights)
        object.__setattr__(self, "stage_weights", validated_weights)

        if not _is_valid_int(self.seed):
            raise ValueError("seed must be an integer")
        if self.num_samples is not None:
            if not _is_valid_int(self.num_samples) or self.num_samples <= 0:
                raise ValueError("num_samples must be a positive integer")
        if not isinstance(self.replacement, bool):
            raise ValueError("replacement must be a bool")
        if not isinstance(self.stage_key, str) or not self.stage_key.strip():
            raise ValueError("stage_key must be a non-empty string")
        if self.batch_size is not None:
            if not _is_valid_int(self.batch_size) or self.batch_size <= 0:
                raise ValueError("batch_size must be a positive integer")
        if not isinstance(self.drop_last, bool):
            raise ValueError("drop_last must be a bool")
        if not isinstance(self.allow_unconfigured_stages, bool):
            raise ValueError("allow_unconfigured_stages must be a bool")
        if not isinstance(self.allow_empty_stages, bool):
            raise ValueError("allow_empty_stages must be a bool")


def _extract_item_stage(item: Any, index: int, stage_key: str) -> str:
    if isinstance(item, str):
        return _validate_stage_name(item, label=f"stage at index {index}")
    if isinstance(item, Mapping):
        if stage_key in item:
            return _validate_stage_name(item[stage_key], label=f"record[{stage_key!r}] at index {index}")
        if stage_key == "stage" and "stage_tag" in item:
            return _validate_stage_name(item["stage_tag"], label=f"record['stage_tag'] at index {index}")
        raise ValueError(
            f"record at index {index} is missing required stage field {stage_key!r}"
        )
    if hasattr(item, stage_key):
        return _validate_stage_name(
            getattr(item, stage_key), label=f"record.{stage_key} at index {index}"
        )
    if stage_key == "stage" and hasattr(item, "stage_tag"):
        return _validate_stage_name(
            getattr(item, "stage_tag"), label=f"record.stage_tag at index {index}"
        )
    raise ValueError(
        f"cannot extract stage from item at index {index} using stage_key={stage_key!r}"
    )


def _build_stage_pools(
    data_source: Sequence[Any] | Mapping[str, Sequence[int]] | int | None,
    *,
    stages: Sequence[str] | None,
    stage_key: str,
) -> tuple[dict[str, list[int]], dict[int, str]]:
    if stages is not None and isinstance(stages, (str, bytes, bytearray)):
        raise ValueError("stages must be a sequence of stage names, not a string or bytes")

    pools: dict[str, list[int]] = {}
    index_to_stage: dict[int, str] = {}

    if isinstance(data_source, Mapping):
        if stages is not None:
            raise ValueError("stages cannot be specified when data_source is already a stage-to-indices mapping")
        if not data_source:
            raise ValueError("data_source mapping must not be empty")
        for raw_stage, raw_indices in data_source.items():
            stage = _validate_stage_name(raw_stage, label="data_source stage key")
            if isinstance(raw_indices, (str, bytes, bytearray)) or not isinstance(raw_indices, Sequence):
                raise ValueError(f"indices for stage {stage!r} must be a sequence of integers")
            stage_indices: list[int] = []
            for idx in raw_indices:
                if not _is_valid_int(idx) or idx < 0:
                    raise ValueError(f"invalid sample index {idx!r} for stage {stage!r}")
                if idx in index_to_stage:
                    raise ValueError(
                        f"sample index {idx} is assigned to multiple stages ({index_to_stage[idx]!r}, {stage!r})"
                    )
                index_to_stage[idx] = stage
                stage_indices.append(idx)
            if stage_indices:
                pools[stage] = stage_indices
        if not index_to_stage:
            raise ValueError("data_source contains zero sample indices")
        return pools, index_to_stage

    if data_source is None:
        if stages is None:
            raise ValueError("either data_source or stages must be provided")
        total_len = len(stages)
        if total_len == 0:
            raise ValueError("stages must not be empty")
        resolved_stages = [
            _validate_stage_name(st, label=f"stages[{i}]") for i, st in enumerate(stages)
        ]
    elif _is_valid_int(data_source):
        total_len = int(data_source)
        if total_len <= 0:
            raise ValueError("data_source length must be positive")
        if stages is None:
            raise ValueError("stages must be provided when data_source is an integer length")
        if len(stages) != total_len:
            raise ValueError(
                f"stages length ({len(stages)}) does not match data_source length ({total_len})"
            )
        resolved_stages = [
            _validate_stage_name(st, label=f"stages[{i}]") for i, st in enumerate(stages)
        ]
    elif isinstance(data_source, (str, bytes, bytearray)) or isinstance(data_source, bool):
        raise ValueError("data_source must be a sequence of records, a stage mapping, or a positive int length")
    else:
        try:
            total_len = len(data_source)  # type: ignore[arg-type]
        except TypeError as exc:
            raise ValueError(
                "data_source must support len() and indexing, or be a stage mapping"
            ) from exc
        if total_len <= 0:
            raise ValueError("data_source must not be empty")
        if stages is not None:
            if len(stages) != total_len:
                raise ValueError(
                    f"stages length ({len(stages)}) does not match data_source length ({total_len})"
                )
            resolved_stages = [
                _validate_stage_name(st, label=f"stages[{i}]") for i, st in enumerate(stages)
            ]
        else:
            resolved_stages = [
                _extract_item_stage(data_source[i], i, stage_key)  # type: ignore[index]
                for i in range(total_len)
            ]

    for idx, stage in enumerate(resolved_stages):
        pools.setdefault(stage, []).append(idx)
        index_to_stage[idx] = stage

    return pools, index_to_stage


class StageAwareSampler:
    """Deterministic weighted sampler across curriculum/training stages.

    Supports PyTorch-compatible `__iter__` / `__len__` protocols without requiring
    PyTorch at import time, preserves exact determinism for a given `(seed, epoch)`,
    samples stages according to normalized `stage_weights`, and validates inputs strictly.
    """

    def __init__(
        self,
        data_source: Sequence[Any] | Mapping[str, Sequence[int]] | int | None = None,
        stage_weights: Mapping[str, float] | None = None,
        *,
        weights: Mapping[str, float] | None = None,
        stages: Sequence[str] | None = None,
        num_samples: int | None = None,
        seed: int = 0,
        replacement: bool = True,
        stage_key: str = "stage",
        batch_size: int | None = None,
        drop_last: bool = False,
        allow_unconfigured_stages: bool = False,
        allow_empty_stages: bool = False,
        config: StageSamplerConfig | None = None,
    ) -> None:
        if config is not None:
            if not isinstance(config, StageSamplerConfig):
                raise ValueError("config must be a StageSamplerConfig instance")
            resolved_weights = config.stage_weights
            seed = config.seed
            num_samples = config.num_samples if num_samples is None else num_samples
            replacement = config.replacement
            stage_key = config.stage_key
            batch_size = config.batch_size if batch_size is None else batch_size
            drop_last = config.drop_last
            allow_unconfigured_stages = config.allow_unconfigured_stages
            allow_empty_stages = config.allow_empty_stages
        else:
            if stage_weights is not None and weights is not None and dict(stage_weights) != dict(weights):
                raise ValueError("pass either stage_weights or weights, not conflicting mappings")
            chosen_weights = stage_weights if stage_weights is not None else weights
            if chosen_weights is None:
                raise ValueError("stage_weights must be provided")
            resolved_weights = chosen_weights

        # Validate all sampler config parameters first
        validated_cfg = StageSamplerConfig(
            stage_weights=dict(resolved_weights),
            seed=seed,
            num_samples=num_samples,
            replacement=replacement,
            stage_key=stage_key,
            batch_size=batch_size,
            drop_last=drop_last,
            allow_unconfigured_stages=allow_unconfigured_stages,
            allow_empty_stages=allow_empty_stages,
        )

        pools, index_to_stage = _build_stage_pools(
            data_source,
            stages=stages,
            stage_key=validated_cfg.stage_key,
        )

        self._pools: dict[str, list[int]] = pools
        self._index_to_stage: dict[int, str] = index_to_stage
        self._stage_key = validated_cfg.stage_key
        self._seed = validated_cfg.seed
        self._replacement = validated_cfg.replacement
        self._batch_size = validated_cfg.batch_size
        self._drop_last = validated_cfg.drop_last
        self._allow_unconfigured_stages = validated_cfg.allow_unconfigured_stages
        self._allow_empty_stages = validated_cfg.allow_empty_stages
        self._epoch = 0

        self._raw_weights: dict[str, float] = {}
        self._normalized_weights: dict[str, float] = {}
        self._active_stages: tuple[str, ...] = ()
        self._cumulative_probs: tuple[float, ...] = ()
        self._eligible_count: int = 0

        self._apply_stage_weights(validated_cfg.stage_weights)

        if validated_cfg.num_samples is not None:
            if not self._replacement and validated_cfg.num_samples > self._eligible_count:
                raise ValueError(
                    f"num_samples ({validated_cfg.num_samples}) exceeds available eligible samples "
                    f"({self._eligible_count}) when replacement=False"
                )
            self._num_samples = validated_cfg.num_samples
        else:
            self._num_samples = self._eligible_count

    @classmethod
    def from_config(
        cls,
        config: StageSamplerConfig,
        data_source: Sequence[Any] | Mapping[str, Sequence[int]] | int | None = None,
        *,
        stages: Sequence[str] | None = None,
    ) -> "StageAwareSampler":
        return cls(data_source=data_source, stages=stages, config=config)

    def _apply_stage_weights(self, candidate_weights: Mapping[str, float]) -> None:
        validated = validate_stage_weights(candidate_weights)

        if not self._allow_unconfigured_stages:
            unknown = sorted(st for st in self._pools if st not in validated)
            if unknown:
                raise ValueError(
                    f"dataset contains unconfigured stage(s): {', '.join(unknown)}"
                )

        if not self._allow_empty_stages:
            empty_weighted = sorted(
                st for st, w in validated.items() if w > 0.0 and not self._pools.get(st)
            )
            if empty_weighted:
                raise ValueError(
                    f"stage(s) with positive weight have no backing samples: {', '.join(empty_weighted)}"
                )

        active_items = [
            (st, float(w))
            for st, w in validated.items()
            if w > 0.0 and len(self._pools.get(st, ())) > 0
        ]
        if not active_items:
            raise ValueError("no active stage has both positive weight and backing samples")

        total_active_weight = sum(w for _, w in active_items)
        if total_active_weight <= 0.0:
            raise ValueError("total active stage weight must be positive")

        normalized: dict[str, float] = {st: 0.0 for st in validated}
        active_stages: list[str] = []
        cumulative: list[float] = []
        running = 0.0
        for st, w in active_items:
            prob = w / total_active_weight
            normalized[st] = prob
            active_stages.append(st)
            running += prob
            cumulative.append(running)
        cumulative[-1] = 1.0

        eligible_count = sum(len(self._pools[st]) for st in active_stages)

        self._raw_weights = dict(validated)
        self._normalized_weights = normalized
        self._active_stages = tuple(active_stages)
        self._cumulative_probs = tuple(cumulative)
        self._eligible_count = eligible_count

    def update_stage_weights(self, new_weights: Mapping[str, float]) -> None:
        """Atomically validate and apply updated stage weights."""
        if not self._replacement and self._num_samples > 0:
            # Validate weight update first before updating _num_samples check
            old_state = (
                self._raw_weights,
                self._normalized_weights,
                self._active_stages,
                self._cumulative_probs,
                self._eligible_count,
            )
            try:
                self._apply_stage_weights(new_weights)
                if self._num_samples > self._eligible_count:
                    raise ValueError(
                        f"num_samples ({self._num_samples}) exceeds eligible samples "
                        f"({self._eligible_count}) after stage weight update"
                    )
            except Exception:
                (
                    self._raw_weights,
                    self._normalized_weights,
                    self._active_stages,
                    self._cumulative_probs,
                    self._eligible_count,
                ) = old_state
                raise
            return

        self._apply_stage_weights(new_weights)

    @property
    def seed(self) -> int:
        return self._seed

    @property
    def epoch(self) -> int:
        return self._epoch

    @property
    def num_samples(self) -> int:
        return self._num_samples

    @property
    def replacement(self) -> bool:
        return self._replacement

    @property
    def stage_weights(self) -> dict[str, float]:
        return dict(self._raw_weights)

    @property
    def normalized_weights(self) -> dict[str, float]:
        return dict(self._normalized_weights)

    @property
    def stage_counts(self) -> dict[str, int]:
        return {stage: len(indices) for stage, indices in self._pools.items()}

    def get_normalized_weights(self) -> dict[str, float]:
        return dict(self._normalized_weights)

    def set_epoch(self, epoch: int) -> None:
        if not _is_valid_int(epoch) or epoch < 0:
            raise ValueError("epoch must be a non-negative integer")
        self._epoch = int(epoch)

    def _make_rng(self, seed: int, epoch: int) -> random.Random:
        # Derive a reproducible per-(seed, epoch) state without mutating global random
        return random.Random(f"zyrquen.stage_sampler:{seed}:{epoch}")

    def _sample_with_replacement(self, count: int, rng: random.Random) -> list[int]:
        stages = self._active_stages
        cdf = self._cumulative_probs
        pools = self._pools
        result: list[int] = []
        n_stages = len(stages)

        if n_stages == 1:
            pool = pools[stages[0]]
            pool_len = len(pool)
            for _ in range(count):
                result.append(pool[rng.randrange(pool_len)])
            return result

        for _ in range(count):
            pos = bisect.bisect_right(cdf, rng.random())
            if pos >= n_stages:
                pos = n_stages - 1
            pool = pools[stages[pos]]
            result.append(pool[rng.randrange(len(pool))])
        return result

    def _sample_without_replacement(self, count: int, rng: random.Random) -> list[int]:
        if count > self._eligible_count:
            raise ValueError(
                f"requested count ({count}) exceeds available eligible samples "
                f"({self._eligible_count}) when replacement=False"
            )

        remaining_pools: dict[str, list[int]] = {}
        remaining_weights: dict[str, float] = {}
        for st in self._active_stages:
            shuffled = list(self._pools[st])
            rng.shuffle(shuffled)
            remaining_pools[st] = shuffled
            remaining_weights[st] = self._raw_weights[st]

        result: list[int] = []
        active = list(self._active_stages)
        for _ in range(count):
            total_w = sum(remaining_weights[st] for st in active)
            pick = rng.random() * total_w
            acc = 0.0
            chosen_stage = active[-1]
            for st in active:
                acc += remaining_weights[st]
                if pick < acc:
                    chosen_stage = st
                    break
            pool = remaining_pools[chosen_stage]
            result.append(pool.pop())
            if not pool:
                active.remove(chosen_stage)
        return result

    def sample_indices(
        self,
        num_samples: int | None = None,
        *,
        epoch: int | None = None,
        seed: int | None = None,
    ) -> list[int]:
        """Deterministically sample `num_samples` dataset indices respecting `stage_weights`."""
        count = self._num_samples if num_samples is None else num_samples
        if not _is_valid_int(count) or count <= 0:
            raise ValueError("num_samples must be a positive integer")

        resolved_epoch = self._epoch if epoch is None else epoch
        if not _is_valid_int(resolved_epoch) or resolved_epoch < 0:
            raise ValueError("epoch must be a non-negative integer")

        resolved_seed = self._seed if seed is None else seed
        if not _is_valid_int(resolved_seed):
            raise ValueError("seed must be an integer")

        rng = self._make_rng(int(resolved_seed), int(resolved_epoch))
        if self._replacement:
            return self._sample_with_replacement(int(count), rng)
        return self._sample_without_replacement(int(count), rng)

    def sample_batches(
        self,
        batch_size: int | None = None,
        *,
        num_samples: int | None = None,
        drop_last: bool | None = None,
        epoch: int | None = None,
        seed: int | None = None,
    ) -> Iterator[list[int]]:
        """Yield deterministic batches of stage-weighted indices."""
        resolved_batch_size = self._batch_size if batch_size is None else batch_size
        if not _is_valid_int(resolved_batch_size) or resolved_batch_size <= 0:
            raise ValueError("batch_size must be a positive integer")

        resolved_drop_last = self._drop_last if drop_last is None else drop_last
        if not isinstance(resolved_drop_last, bool):
            raise ValueError("drop_last must be a bool")

        indices = self.sample_indices(num_samples=num_samples, epoch=epoch, seed=seed)
        step = int(resolved_batch_size)
        for start in range(0, len(indices), step):
            batch = indices[start : start + step]
            if resolved_drop_last and len(batch) < step:
                break
            yield batch

    def measure_stage_distribution(self, indices: Sequence[int]) -> dict[str, float]:
        """Compute empirical stage proportions for a sequence of sampled indices."""
        if not indices:
            raise ValueError("indices must not be empty")
        counts: dict[str, int] = {st: 0 for st in self._raw_weights}
        for idx in indices:
            if not _is_valid_int(idx) or idx not in self._index_to_stage:
                raise ValueError(f"unknown sample index: {idx!r}")
            st = self._index_to_stage[idx]
            counts[st] = counts.get(st, 0) + 1
        total = len(indices)
        return {st: count / total for st, count in counts.items()}

    def state_dict(self) -> dict[str, Any]:
        return {
            "seed": self._seed,
            "epoch": self._epoch,
            "num_samples": self._num_samples,
            "replacement": self._replacement,
            "stage_key": self._stage_key,
            "stage_weights": dict(self._raw_weights),
            "normalized_weights": dict(self._normalized_weights),
        }

    def load_state_dict(self, state: Mapping[str, Any]) -> None:
        if not isinstance(state, Mapping):
            raise ValueError("state must be a mapping")
        if "stage_weights" in state:
            self.update_stage_weights(state["stage_weights"])
        if "epoch" in state:
            self.set_epoch(state["epoch"])
        if "seed" in state:
            if not _is_valid_int(state["seed"]):
                raise ValueError("seed in state_dict must be an integer")
            self._seed = int(state["seed"])
        if "num_samples" in state:
            n = state["num_samples"]
            if not _is_valid_int(n) or n <= 0:
                raise ValueError("num_samples in state_dict must be a positive integer")
            if not self._replacement and n > self._eligible_count:
                raise ValueError(
                    f"num_samples ({n}) exceeds eligible samples ({self._eligible_count}) when replacement=False"
                )
            self._num_samples = int(n)

    def __iter__(self) -> Iterator[int]:
        return iter(self.sample_indices())

    def __len__(self) -> int:
        return self._num_samples


__all__ = [
    "StageAwareSampler",
    "StageSamplerConfig",
    "validate_stage_weights",
]
