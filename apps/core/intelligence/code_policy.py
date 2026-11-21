"""Fixed Phase 9.7 policy: no code execution or environment access."""

FORBIDDEN_CODE_OPERATIONS = frozenset({
    "execute_generated_code",
    "read_file",
    "write_file",
    "install_package",
    "network_access",
    "spawn_process",
})


class ExecutionSafetyPolicy:
    def evaluate(self, operation):
        if not isinstance(operation, str) or operation not in FORBIDDEN_CODE_OPERATIONS:
            raise ValueError(f"unknown code operation: {operation!r}")
        return {
            "status": "blocked",
            "operation": operation,
            "allowed": False,
            "code_executed": False,
            "reason": "disabled_in_phase_9_7",
        }
