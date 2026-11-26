"""Lexical workspace path checks; this policy never accesses the filesystem."""
from pathlib import PurePosixPath


class WorkspaceBoundaryViolation(ValueError):
    pass


class WorkspaceBoundaryPolicy:
    def analyze_path(self, path):
        problems = []
        if not isinstance(path, str) or not path.strip():
            problems.append("path must be non-empty text")
        elif path != path.strip():
            problems.append("path must not have surrounding whitespace")
        elif "\\" in path or "\x00" in path or ":" in path:
            problems.append("path contains a forbidden character")
        else:
            posix_path = PurePosixPath(path)
            if (posix_path.is_absolute() or not posix_path.parts
                    or str(posix_path) != path
                    or ".." in posix_path.parts):
                problems.append("path must be a normalized relative path")
        return {
            "status": "invalid_relative_path" if problems else "valid_relative_path",
            "path": None if problems else path,
            "problems": problems,
            "filesystem_accessed": False,
        }

    def require_relative_path(self, path):
        result = self.analyze_path(path)
        if result["status"] != "valid_relative_path":
            raise WorkspaceBoundaryViolation("; ".join(result["problems"]))
        return result["path"]
