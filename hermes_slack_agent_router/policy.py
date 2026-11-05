"""Immutable native source identities."""

import re
from dataclasses import dataclass

_TS = re.compile(r"[0-9]+\.[0-9]+\Z")


@dataclass(frozen=True)
class Recipient:
    workspace: str
    bot_user: str
    runtime_profile: str


@dataclass(frozen=True)
class Thread:
    workspace: str
    channel: str
    root: str

    def __post_init__(self):
        if not isinstance(self.root, str) or not _TS.fullmatch(self.root):
            raise ValueError("thread timestamp must be an opaque decimal string")


@dataclass(frozen=True)
class Event:
    thread: Thread
    identity: str
    sender: str
    provenance: str = "message"
