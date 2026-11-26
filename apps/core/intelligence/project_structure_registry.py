"""In-memory project layout metadata; it creates no project files."""
import re
import threading
from dataclasses import dataclass
from pathlib import PurePosixPath

from .workspace_policy import (
    WorkspaceBoundaryPolicy,
    WorkspaceBoundaryViolation,
)

STRUCTURE_ID_PATTERN = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")
FILE_EXTENSION_PATTERN = re.compile(r"\.[a-z0-9]{1,16}\Z")


class ProjectStructureViolation(ValueError):
    pass


@dataclass(frozen=True)
class ProjectStructure:
    structure_id: str
    language: str
    allowed_directories: tuple[str, ...]
    allowed_extensions: tuple[str, ...]


class ProjectStructureRegistry:
    def __init__(self, languages, workspace_policy=None):
        self._languages = languages
        self._workspace = (
            workspace_policy if workspace_policy is not None
            else WorkspaceBoundaryPolicy()
        )
        self._structures = {}
        self._lock = threading.RLock()

    def register(self, structure_id, language, allowed_directories,
                 allowed_extensions):
        if (not isinstance(structure_id, str)
                or STRUCTURE_ID_PATTERN.fullmatch(structure_id) is None):
            raise ProjectStructureViolation("invalid structure_id")
        if not self._languages.contains(language):
            raise ProjectStructureViolation(f"language is not registered: {language}")
        if (not isinstance(allowed_directories, (tuple, list))
                or not isinstance(allowed_extensions, (tuple, list))
                or not allowed_extensions):
            raise ProjectStructureViolation(
                "allowed_directories must be a list or tuple and "
                "allowed_extensions must be a non-empty list or tuple")
        directories = []
        for path in allowed_directories:
            try:
                normalized = self._workspace.require_relative_path(path)
            except WorkspaceBoundaryViolation as error:
                raise ProjectStructureViolation(str(error)) from error
            if normalized.casefold() in {item.casefold() for item in directories}:
                raise ProjectStructureViolation("allowed directories must be unique")
            directories.append(normalized)
        extensions = []
        for extension in allowed_extensions:
            if (not isinstance(extension, str)
                    or FILE_EXTENSION_PATTERN.fullmatch(extension) is None):
                raise ProjectStructureViolation(
                    "extensions must be lowercase suffixes such as .py")
            if extension in extensions:
                raise ProjectStructureViolation("allowed extensions must be unique")
            extensions.append(extension)
        structure = ProjectStructure(
            structure_id, language, tuple(directories), tuple(extensions))
        with self._lock:
            if structure_id in self._structures:
                raise ProjectStructureViolation(
                    f"project structure already registered: {structure_id}")
            self._structures[structure_id] = structure
        return structure

    def contains(self, structure_id):
        with self._lock:
            return isinstance(structure_id, str) and structure_id in self._structures

    def get(self, structure_id):
        with self._lock:
            try:
                return self._structures[structure_id]
            except KeyError:
                raise KeyError(
                    f"project structure is not registered: {structure_id}") from None

    def list_structures(self):
        with self._lock:
            return [self._structures[key] for key in sorted(self._structures)]

    def allows_file(self, structure_id, path):
        structure = self.get(structure_id)
        relative = self._workspace.require_relative_path(path)
        if PurePosixPath(relative).suffix.casefold() not in {
                extension.casefold() for extension in structure.allowed_extensions}:
            return False
        parent = str(PurePosixPath(relative).parent)
        return parent == "." or any(
            parent == directory or parent.startswith(f"{directory}/")
            for directory in structure.allowed_directories)

    def allows_directory(self, structure_id, path):
        structure = self.get(structure_id)
        relative = self._workspace.require_relative_path(path)
        return any(
            relative == directory or relative.startswith(f"{directory}/")
            for directory in structure.allowed_directories)
