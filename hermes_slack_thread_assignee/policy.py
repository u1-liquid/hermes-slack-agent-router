"""Pure, immutable identities and direct-composition recipient evidence."""

import re
from dataclasses import asdict, dataclass

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

    def as_dict(self):
        return asdict(self)


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
    direct: tuple[str, ...] = ()
    sender_kind: str = "human"
    provenance: str = "message"

    def __post_init__(self):
        identifier(self.sender)
        if not self.identity or len(self.identity) > 256:
            raise ValueError("invalid event identity")
        if self.provenance not in ("message", "edit", "file_shared"):
            raise ValueError("invalid provenance")
        for value in self.direct:
            identifier(value)
        object.__setattr__(self, "direct", tuple(sorted(set(self.direct))))


@dataclass(frozen=True)
class Decision:
    action: str
    reason: str
    revision: int | None = None


def addresses(text: str) -> tuple[str, ...]:
    """Parse flat Slack composition only; rich blocks need bridge validation."""
    visible = []
    fenced = False
    inline = False
    for line in text.splitlines():
        if line.lstrip().startswith(">>>"):
            break
        if line.lstrip().startswith(">"):
            continue
        parts = re.split(r"(```|`)", line)
        for part in parts:
            if part == "```":
                fenced = not fenced
            elif part == "`" and not fenced:
                inline = not inline
            elif not fenced and not inline:
                visible.append(part)
    return tuple(sorted(set(re.findall(r"<@([A-Z0-9]+)>", "\n".join(visible)))))
