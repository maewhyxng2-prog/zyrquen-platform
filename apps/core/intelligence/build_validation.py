"""Fail-closed interface placeholder; no project build is performed."""


class BuildValidationUnavailable(RuntimeError):
    pass


class BuildValidationInterface:
    def validate(self, specification, manifest):
        raise BuildValidationUnavailable(
            "build validation backend is not implemented; no build was run")
