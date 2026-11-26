"""Contracts for planned project files; manifests are never written to disk."""
from pathlib import PurePosixPath

from .workspace_policy import WorkspaceBoundaryPolicy

FILE_MANIFEST_KEYS = frozenset({"application_id", "structure_id", "entries"})
MANIFEST_ENTRY_KEYS = frozenset({"path", "kind"})
ALLOWED_ENTRY_KINDS = frozenset({"file", "directory"})


class FileManifestViolation(ValueError):
    pass


def analyze_file_manifest(manifest, specification, structures,
                          workspace_policy=None):
    if not isinstance(manifest, dict):
        return {"status": "invalid_manifest", "problems": ["manifest must be a dict"]}
    if not isinstance(specification, dict):
        return {
            "status": "invalid_manifest",
            "problems": ["specification must be a dict"],
        }
    workspace_policy = (
        workspace_policy if workspace_policy is not None
        else WorkspaceBoundaryPolicy()
    )
    problems = []
    missing = FILE_MANIFEST_KEYS - set(manifest)
    extra = set(manifest) - FILE_MANIFEST_KEYS
    if missing:
        problems.append(f"missing manifest keys: {sorted(map(repr, missing))}")
    if extra:
        problems.append(f"unknown manifest keys: {sorted(map(repr, extra))}")
    structure_id = manifest.get("structure_id")
    if structure_id != specification.get("structure_id"):
        problems.append("structure_id does not match application specification")
    if manifest.get("application_id") != specification.get("application_id"):
        problems.append("application_id does not match application specification")
    structure = None
    if not isinstance(structure_id, str) or not structures.contains(structure_id):
        problems.append("structure_id is not registered")
    else:
        structure = structures.get(structure_id)
    entries = manifest.get("entries")
    if not isinstance(entries, list) or not entries:
        problems.append("entries must be a non-empty list")
    else:
        seen = set()
        file_paths = set()
        has_file = False
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                problems.append(f"entries[{index}] must be a dict")
                continue
            missing_entry = MANIFEST_ENTRY_KEYS - set(entry)
            extra_entry = set(entry) - MANIFEST_ENTRY_KEYS
            if missing_entry:
                problems.append(
                    f"entries[{index}] missing keys: {sorted(map(repr, missing_entry))}")
            if extra_entry:
                problems.append(
                    f"entries[{index}] unknown keys: {sorted(map(repr, extra_entry))}")
            path = entry.get("path")
            boundary = workspace_policy.analyze_path(path)
            if boundary["status"] != "valid_relative_path":
                problems.extend(
                    f"entries[{index}]: {problem}" for problem in boundary["problems"])
                continue
            normalized = path.casefold()
            if normalized in seen:
                problems.append(f"duplicate manifest path: {path!r}")
            seen.add(normalized)
            kind = entry.get("kind")
            if not isinstance(kind, str) or kind not in ALLOWED_ENTRY_KINDS:
                problems.append(f"entries[{index}].kind is invalid")
            elif structure is not None:
                try:
                    if kind == "file":
                        allowed = structures.allows_file(structure_id, path)
                        has_file = True
                        file_paths.add(normalized)
                    else:
                        allowed = structures.allows_directory(structure_id, path)
                except ValueError as error:
                    problems.append(f"entries[{index}]: {error}")
                else:
                    if not allowed:
                        problems.append(
                            f"entries[{index}] is not allowed by project structure")
        if not has_file:
            problems.append("manifest must include at least one file")
        for path in file_paths:
            parts = PurePosixPath(path).parts
            for end in range(1, len(parts)):
                ancestor = "/".join(parts[:end]).casefold()
                if ancestor in file_paths:
                    problems.append(
                        f"file path conflicts with descendant: {ancestor!r}")
    return {
        "status": "valid_manifest" if not problems else "invalid_manifest",
        "problems": problems,
        "filesystem_accessed": False,
    }


def validate_file_manifest(manifest, specification, structures,
                           workspace_policy=None):
    result = analyze_file_manifest(
        manifest, specification, structures, workspace_policy)
    if result["status"] != "valid_manifest":
        raise FileManifestViolation("; ".join(result["problems"]))
    return manifest
