"""Contracts for coding tasks and generated source bundles."""
from pathlib import PurePosixPath

from .language_registry import ProgrammingLanguageRegistry

CODE_TASK_KEYS = frozenset({"task_id", "objective", "language", "requirements"})
CODE_OUTPUT_KEYS = frozenset({"task_id", "language", "files"})
CODE_FILE_KEYS = frozenset({"path", "content"})


class CodeContractViolation(ValueError):
    pass


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _unknown_keys(value, expected):
    return sorted(map(repr, set(value) - expected))


def analyze_code_task(task, languages):
    if not isinstance(task, dict):
        return {"status": "invalid_task", "problems": ["task must be a dict"]}
    problems = []
    missing = CODE_TASK_KEYS - set(task)
    extra = _unknown_keys(task, CODE_TASK_KEYS)
    if missing:
        problems.append(f"missing task keys: {sorted(map(repr, missing))}")
    if extra:
        problems.append(f"unknown task keys: {extra}")
    if "task_id" in task and not _text(task["task_id"]):
        problems.append("task_id must be non-empty text")
    if "objective" in task and not _text(task["objective"]):
        problems.append("objective must be non-empty text")
    language = task.get("language")
    if not _text(language):
        problems.append("language must be non-empty text")
    elif not languages.contains(language):
        problems.append(f"language is not registered: {language}")
    requirements = task.get("requirements")
    if (not isinstance(requirements, list) or not requirements
            or any(not _text(item) for item in requirements)):
        problems.append("requirements must be a non-empty list of non-empty text")
    return {
        "status": "valid_task" if not problems else "invalid_task",
        "problems": problems,
    }


def validate_code_task(task, languages):
    result = analyze_code_task(task, languages)
    if result["status"] != "valid_task":
        raise CodeContractViolation("; ".join(result["problems"]))
    return task


def _validate_output_path(path, extensions, index):
    if not _text(path):
        return [f"files[{index}].path must be non-empty text"]
    if "\\" in path or "\x00" in path:
        return [f"files[{index}].path must use a safe relative POSIX path"]
    posix_path = PurePosixPath(path)
    if (posix_path.is_absolute() or str(posix_path) != path
            or ".." in posix_path.parts
            or (posix_path.parts and len(posix_path.parts[0]) >= 2
                and posix_path.parts[0][1] == ":")):
        return [f"files[{index}].path must be normalized and workspace-relative"]
    if posix_path.suffix.casefold() not in {
            extension.casefold() for extension in extensions}:
        return [f"files[{index}].path extension does not match language"]
    return []


def analyze_code_output(output, languages, expected_task_id=None):
    if not isinstance(output, dict):
        return {"status": "invalid_output", "problems": ["output must be a dict"]}
    problems = []
    missing = CODE_OUTPUT_KEYS - set(output)
    extra = _unknown_keys(output, CODE_OUTPUT_KEYS)
    if missing:
        problems.append(f"missing output keys: {sorted(map(repr, missing))}")
    if extra:
        problems.append(f"unknown output keys: {extra}")
    task_id = output.get("task_id")
    if not _text(task_id):
        problems.append("task_id must be non-empty text")
    elif expected_task_id is not None and task_id != expected_task_id:
        problems.append("task_id does not match requested task")
    language = output.get("language")
    language_definition = None
    if not _text(language):
        problems.append("language must be non-empty text")
    elif not languages.contains(language):
        problems.append(f"language is not registered: {language}")
    else:
        language_definition = languages.get(language)
    files = output.get("files")
    if not isinstance(files, list) or not files:
        problems.append("files must be a non-empty list")
    else:
        seen_paths = set()
        for index, file in enumerate(files):
            if not isinstance(file, dict):
                problems.append(f"files[{index}] must be a dict")
                continue
            missing_file_keys = CODE_FILE_KEYS - set(file)
            extra_file_keys = _unknown_keys(file, CODE_FILE_KEYS)
            if missing_file_keys:
                problems.append(
                    f"files[{index}] missing keys: "
                    f"{sorted(map(repr, missing_file_keys))}")
            if extra_file_keys:
                problems.append(f"files[{index}] unknown keys: {extra_file_keys}")
            path = file.get("path")
            if language_definition is not None:
                problems.extend(_validate_output_path(
                    path, language_definition.extensions, index))
            elif not _text(path):
                problems.append(f"files[{index}].path must be non-empty text")
            if _text(path):
                normalized = path.casefold()
                if normalized in seen_paths:
                    problems.append(f"duplicate output path: {path!r}")
                seen_paths.add(normalized)
            if not isinstance(file.get("content"), str) or not file["content"].strip():
                problems.append(f"files[{index}].content must be non-empty text")
    return {
        "status": "valid_output" if not problems else "invalid_output",
        "problems": problems,
    }


def validate_code_output(output, languages, expected_task_id=None):
    result = analyze_code_output(output, languages, expected_task_id)
    if result["status"] != "valid_output":
        raise CodeContractViolation("; ".join(result["problems"]))
    return output
