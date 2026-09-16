"""Private media storage boundary for the current local-persistent backend."""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class StorageBackend(ABC):
    @abstractmethod
    def path_for(self, asset_id: str, suffix: str = '') -> Path:
        """Resolve a stable private path for one asset id."""

    @abstractmethod
    def resolve(self, stored_name: str) -> Path:
        """Resolve a stored relative name without escaping the private root."""


class LocalStorageBackend(StorageBackend):
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, asset_id: str, suffix: str = '') -> Path:
        safe_id = str(asset_id).strip()
        safe_suffix = str(suffix).strip()
        if not safe_id or Path(safe_id).name != safe_id:
            raise ValueError('asset_id must be a non-empty path-safe identifier')
        if safe_suffix and (not safe_suffix.startswith('.') or Path(safe_suffix).name != safe_suffix):
            raise ValueError('asset suffix must be a path-safe extension')
        return self.root / f'{safe_id}{safe_suffix}'

    def resolve(self, stored_name: str) -> Path:
        candidate = (self.root / str(stored_name)).resolve()
        if candidate.parent != self.root:
            raise ValueError('stored asset path escapes the private media directory')
        return candidate
