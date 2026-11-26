"""ZYRQUEN Ω∞ P1-1 Native AI Core Capability Benchmark Suite."""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "BENCHMARK_SCHEMA",
    "FIXTURES_PATH",
    "format_p1_1_markdown_report",
    "load_benchmark_fixtures",
    "run_p1_1_benchmark",
]


def __getattr__(name: str) -> Any:
    if name in __all__:
        mod = import_module(".p1_1_runner", __name__)
        return getattr(mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
