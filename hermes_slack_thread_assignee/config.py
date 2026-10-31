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
    monitoring: tuple[tuple[str, str, str], ...] = ()

    @classmethod
    def load(cls, path: Path):
        try:
            raw = json.loads(Path(path).read_text())
            required = {"database", "database_id", "registry_revision", "participants"}
            if not required <= set(raw) or set(raw) - required - {"monitoring"}:
                raise ValueError("unknown or missing config fields")
            database = Path(raw["database"])
            if not database.is_absolute():
                raise ValueError("database must be absolute")
            participants = tuple(Recipient(**item) for item in raw["participants"])
            if not participants or len(set(participants)) != len(participants):
                raise ValueError("empty or duplicate participant registry")
            monitoring = []
            for item in raw.get("monitoring", []):
                if set(item) != {"workspace", "channel", "sender"}:
                    raise ValueError("monitoring rules require exact workspace/channel/sender")
                monitoring.append(tuple(identifier(item[k]) for k in ("workspace", "channel", "sender")))
            return cls(
                database,
                identifier(raw["database_id"]),
                identifier(raw["registry_revision"]),
                participants,
                tuple(monitoring),
            )
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise ConfigError(str(exc)) from exc

    def store(self):
        from .store import Store

        return Store(self.database, self.database_id, self.registry_revision, self.participants)
