"""In-memory programming-language metadata registry; it loads no plugins."""
import re
import threading
from dataclasses import dataclass

LANGUAGE_NAME_PATTERN = re.compile(r"[a-z][a-z0-9_+-]{0,31}\Z")
EXTENSION_PATTERN = re.compile(r"\.[a-z0-9]{1,16}\Z")


class LanguageRegistryViolation(ValueError):
    pass


@dataclass(frozen=True)
class ProgrammingLanguage:
    name: str
    extensions: tuple[str, ...]


class ProgrammingLanguageRegistry:
    def __init__(self):
        self._languages = {}
        self._lock = threading.RLock()
        self.register("python", (".py",))

    def register(self, name, extensions):
        if (not isinstance(name, str)
                or LANGUAGE_NAME_PATTERN.fullmatch(name) is None):
            raise LanguageRegistryViolation(
                "language name must match [a-z][a-z0-9_+-]{0,31}")
        if not isinstance(extensions, (list, tuple)) or not extensions:
            raise LanguageRegistryViolation("extensions must be a non-empty list or tuple")
        if any(not isinstance(extension, str)
               or EXTENSION_PATTERN.fullmatch(extension) is None
               for extension in extensions):
            raise LanguageRegistryViolation(
                "extensions must be lowercase suffixes such as .py")
        normalized = tuple(dict.fromkeys(extensions))
        if len(normalized) != len(extensions):
            raise LanguageRegistryViolation("extensions must not contain duplicates")
        language = ProgrammingLanguage(name, normalized)
        with self._lock:
            if name in self._languages:
                raise LanguageRegistryViolation(f"language already registered: {name}")
            self._languages[name] = language
        return language

    def contains(self, name):
        with self._lock:
            return isinstance(name, str) and name in self._languages

    def get(self, name):
        with self._lock:
            try:
                return self._languages[name]
            except KeyError:
                raise KeyError(f"language is not registered: {name}") from None

    def list_languages(self):
        with self._lock:
            return [self._languages[name] for name in sorted(self._languages)]
