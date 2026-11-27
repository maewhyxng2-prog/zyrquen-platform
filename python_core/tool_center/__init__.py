"""
ZYRQUEN Tool Center & Background Autonomous Support Architecture
----------------------------------------------------------------
Ensures `REPO_ROOT` and `PYTHON_CORE_DIR` are on `sys.path` regardless of working
directory, then exposes:
  - Central Tool Center Registry (8 modular Toolkits)
  - Tool Intelligence & Selection + Controlled Parallel Orchestrator
  - Tool Dependency Manager, Context Manager, Resource Manager
  - Isolated Sandbox Execution, Quality Assurance Engine
  - Failure Recovery Engine, Task Memory, Self-Improvement Governance
"""

from __future__ import annotations

import sys
from pathlib import Path

PYTHON_CORE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = PYTHON_CORE_DIR.parent
for _p in (str(REPO_ROOT), str(PYTHON_CORE_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from .context_manager import ContextManager  # noqa: E402
from .contracts import (  # noqa: E402
    CapabilityExecutionResult,
    CapabilityHandle,
    CapabilitySpec,
    ToolkitManifest,
    ToolContractError,
)
from .dependency_manager import ToolDependencyManager  # noqa: E402
from .orchestrator import execute_orchestrated_plan, select_tools_for_goal  # noqa: E402
from .quality_assurance import aggregate_plan_verdict, verify_capability_delivery  # noqa: E402
from .recovery import ERROR_TAXONOMY, classify_error, init_orchestration_schema  # noqa: E402
from .registry import ToolCenterRegistry, get_tool_center_registry, init_tool_center_schema  # noqa: E402
from .resource_manager import ResourceBudget, ResourceManager, get_resource_manager  # noqa: E402
from .sandbox import inspect_sandbox_code_policy, run_python_sandbox, run_workspace_unittest  # noqa: E402
from .software_engineering import (  # noqa: E402
    WorkspaceTransaction,
    compute_unified_diff,
    run_autonomous_repair_loop,
    run_engineering_benchmark,
)
from .app_builder import (  # noqa: E402
    build_and_verify_app,
    manage_workspace_history,
    run_real_project_build,
)
from .autonomous_training import (  # noqa: E402
    run_autonomous_engineering_curriculum,
    run_comprehensive_benchmark,
)
from .self_improvement import (  # noqa: E402
    decide_improvement_proposal,
    init_self_improvement_schema,
    run_self_improvement_evaluation,
)
from .task_memory import (  # noqa: E402
    analyze_failure_patterns,
    init_task_memory_schema,
    record_task_memory,
    retrieve_relevant_memories,
)

__all__ = [
    "CapabilityExecutionResult",
    "CapabilityHandle",
    "CapabilitySpec",
    "ContextManager",
    "ERROR_TAXONOMY",
    "ResourceBudget",
    "ResourceManager",
    "ToolCenterRegistry",
    "ToolContractError",
    "ToolDependencyManager",
    "ToolkitManifest",
    "WorkspaceTransaction",
    "aggregate_plan_verdict",
    "analyze_failure_patterns",
    "build_and_verify_app",
    "classify_error",
    "compute_unified_diff",
    "decide_improvement_proposal",
    "execute_orchestrated_plan",
    "get_resource_manager",
    "get_tool_center_registry",
    "init_orchestration_schema",
    "init_self_improvement_schema",
    "init_task_memory_schema",
    "init_tool_center_schema",
    "inspect_sandbox_code_policy",
    "manage_workspace_history",
    "record_task_memory",
    "retrieve_relevant_memories",
    "run_autonomous_engineering_curriculum",
    "run_autonomous_repair_loop",
    "run_comprehensive_benchmark",
    "run_engineering_benchmark",
    "run_python_sandbox",
    "run_real_project_build",
    "run_self_improvement_evaluation",
    "run_workspace_unittest",
    "select_tools_for_goal",
    "verify_capability_delivery",
]
