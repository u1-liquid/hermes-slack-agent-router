"""Immutable native source identities."""

import re
from dataclasses import dataclass

_ID = re.compile(r"[A-Za-z0-9_-]+\Z")
_TS = re.compile(r"[0-9]+\.[0-9]+\Z")


def identifier(value: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError("invalid identity")
    return value


@dataclass(frozen=True)
class Recipient:
    workspace: str
    bot_user: str
    runtime_profile: str

    def __post_init__(self):
        for value in (self.workspace, self.bot_user, self.runtime_profile):
            identifier(value)


@dataclass(frozen=True)
class Thread:
    workspace: str
    channel: str
    root: str

    def __post_init__(self):
        identifier(self.workspace)
        identifier(self.channel)
        if not isinstance(self.root, str) or not _TS.fullmatch(self.root):
            raise ValueError("thread timestamp must be an opaque decimal string")


@dataclass(frozen=True)
class Event:
    thread: Thread
    identity: str
    sender: str
    provenance: str = "message"

    def __post_init__(self):
        identifier(self.sender)
        if not self.identity or len(self.identity) > 256:
            raise ValueError("invalid event identity")
        if self.provenance not in ("message", "edit", "file_shared"):
            raise ValueError("invalid provenance")
