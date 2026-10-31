"""Explicit shared configuration; no profile-scoped implicit defaults."""

import json
from dataclasses import dataclass
from pathlib import Path

from .policy import Recipient, identifier


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class SemanticPolicy:
    enabled: bool = False
    policy_revision: str = "disabled"
    scopes: tuple[tuple[str, str, tuple[str, ...]], ...] = ()

    def permits(self, thread, data_class):
        return self.enabled and any(
            workspace == thread.workspace and channel == thread.channel and data_class in classes
            for workspace, channel, classes in self.scopes
        )

    @classmethod
    def parse(cls, raw):
        if raw is None:
            return cls()
        if (
            not isinstance(raw, dict)
            or set(raw) != {"enabled", "policy_revision", "scopes"}
            or type(raw["enabled"]) is not bool
            or not isinstance(raw["scopes"], list)
        ):
            raise ValueError("semantic policy requires explicit enabled/revision/scopes")
        scopes = []
        for scope in raw["scopes"]:
            if set(scope) != {"workspace", "channel", "data_classes"}:
                raise ValueError("semantic scope must be exact")
            classes = scope["data_classes"]
            if (
                not isinstance(classes, list)
                or not classes
                or any(item not in ("fictional", "public-permitted") for item in classes)
            ):
                raise ValueError("only explicitly fictional/public-permitted data classes supported")
            scopes.append((identifier(scope["workspace"]), identifier(scope["channel"]), tuple(classes)))
        return cls(raw["enabled"], identifier(raw["policy_revision"]), tuple(scopes))


@dataclass(frozen=True)
class Config:
    database: Path
    database_id: str
    registry_revision: str
    participants: tuple[Recipient, ...]
    monitoring: tuple[tuple[str, str, str], ...] = ()
    semantic: SemanticPolicy = SemanticPolicy()

    @classmethod
    def load(cls, path: Path):
        try:
            raw = json.loads(Path(path).read_text())
            required = {"database", "database_id", "registry_revision", "participants"}
            if not required <= set(raw) or set(raw) - required - {"monitoring", "semantic"}:
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
                SemanticPolicy.parse(raw.get("semantic")),
            )
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise ConfigError(str(exc)) from exc

    def store(self):
        from .store import Store

        return Store(self.database, self.database_id, self.registry_revision, self.participants)
