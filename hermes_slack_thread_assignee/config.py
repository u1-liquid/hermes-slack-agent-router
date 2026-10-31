"""Explicit shared configuration; no profile-scoped implicit defaults."""

import json
from dataclasses import dataclass
from pathlib import Path

from .policy import Recipient, identifier


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Config:
    database: Path
    database_id: str
    registry_revision: str
    participants: tuple[Recipient, ...]

    @classmethod
    def load(cls, path: Path):
        try:
            raw = json.loads(Path(path).read_text())
            if set(raw) != {"database", "database_id", "registry_revision", "participants"}:
                raise ValueError("unknown or missing config fields")
            database = Path(raw["database"])
            if not database.is_absolute():
                raise ValueError("database must be absolute")
            participants = tuple(Recipient(**item) for item in raw["participants"])
            if not participants or len(set(participants)) != len(participants):
                raise ValueError("empty or duplicate participant registry")
            return cls(
                database, identifier(raw["database_id"]), identifier(raw["registry_revision"]), participants
            )
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise ConfigError(str(exc)) from exc

    def store(self):
        from .store import Store

        return Store(self.database, self.database_id, self.registry_revision, self.participants)
