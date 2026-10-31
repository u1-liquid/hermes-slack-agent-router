"""Request-local contextual routing through the official native middleware seam."""

import asyncio
import copy
import hashlib
import json
import logging
import time
from collections import deque
from decimal import Decimal

from .bridge import Bridge, TopologyError, Uncertain, canonical_text, composition
from .jev import JevClient, JevError
from .policy import Thread, identifier
from .semantic import History, SemanticError, Snapshot, assemble, prepare

logger = logging.getLogger(__name__)


class Gate:
    def __init__(self):
        self.disposed = False
        self.jev = JevClient()

    @staticmethod
    def unresolved(reason):
        # Fixed local reason codes only: no transcript, raw model answer or durable queue.
        logger.warning("agent-router unresolved: %s", reason)

    @staticmethod
    def native_policy(adapter, event, bot):
        """Pure admission intersection; native wake runs exactly once downstream."""
        channel = event["channel"]
        text = event.get("text", "")
        own = {bot, adapter._bot_user_id} - {None, ""}
        mentioned = bool(set(composition(event)) & own) or adapter._slack_message_matches_mention_patterns(
            text
        )
        allowed = adapter._slack_allowed_channels()
        if allowed and channel not in allowed:
            return False
        if (
            adapter._slack_ignore_other_user_mentions()
            and not mentioned
            and adapter._slack_message_addressed_to_other_user(text, own)
        ):
            return False
        free = adapter._slack_is_free_channel(channel)
        return not (
            not mentioned
            and (
                (not free and adapter._slack_strict_mention())
                or (event.get("thread_ts") and adapter._slack_thread_require_mention())
            )
        )

    @staticmethod
    async def history(client, thread, cutoff, deadline):
        """Exhaust ascending cursors before calling the rolling window latest.

        Slack SDK buffers JSON before returning: page caps are post-decode
        acceptance bounds, not socket/RSS limits. Shared SDK retry policy is native.
        """
        if cutoff == thread.root:
            return ()  # The root is CURRENT, never its own prior reference.
        root, cursor = None, None
        recent = deque(maxlen=7)
        seen, cursors = {}, set()
        last = Decimal(thread.root)
        total = 0
        async with asyncio.timeout_at(min(time.monotonic() + 1.0, deadline - 1.3)):
            for _ in range(4):
                args = {
                    "channel": thread.channel,
                    "ts": thread.root,
                    "latest": cutoff,
                    "inclusive": False,
                    "limit": 100,
                }
                if cursor:
                    args["cursor"] = cursor
                response = await client.conversations_replies(**args)
                data = getattr(response, "data", response)
                size = len(json.dumps(data, ensure_ascii=False, allow_nan=False).encode())
                total += size
                messages = data.get("messages")
                metadata = data.get("response_metadata", {})
                if (
                    data.get("ok") is not True
                    or not isinstance(messages, list)
                    or len(messages) > 100
                    or size > 1048576
                    or total > 4194304
                    or not isinstance(metadata, dict)
                    or type(data.get("has_more", False)) is not bool
                ):
                    raise SemanticError("incomplete-context")
                next_cursor = metadata.get("next_cursor", "")
                if (
                    not isinstance(next_cursor, str)
                    or len(next_cursor) > 2048
                    or (data.get("has_more") and not next_cursor)
                    or next_cursor in cursors
                ):
                    raise SemanticError("incomplete-context")
                progress = False
                for message in messages:
                    ts = message["ts"]
                    Thread(thread.workspace, thread.channel, ts)
                    if (
                        Decimal(ts) > Decimal(cutoff)
                        or Decimal(ts) < Decimal(thread.root)
                        or (message.get("thread_ts") and message["thread_ts"] != thread.root)
                        or (message.get("channel") and message["channel"] != thread.channel)
                        or (message.get("team") and message["team"] != thread.workspace)
                    ):
                        raise SemanticError("foreign-or-future-context")
                    if ts == cutoff:
                        continue
                    encoded = json.dumps(
                        message, sort_keys=True, ensure_ascii=False, allow_nan=False
                    ).encode()
                    digest = hashlib.sha256(encoded).digest()
                    if ts in seen:
                        if seen[ts] != digest:
                            raise SemanticError("conflicting-context")
                        continue
                    if Decimal(ts) < last:
                        raise SemanticError("unordered-context")
                    last = Decimal(ts)
                    seen[ts] = digest
                    progress = True
                    recent.append(message)
                    if ts == thread.root:
                        root = message
                if not next_cursor:
                    break
                if not progress:
                    raise SemanticError("incomplete-context")
                cursors.add(next_cursor)
                cursor = next_cursor
            else:
                raise SemanticError("incomplete-context")
        if root is None:
            raise SemanticError("missing-root-context")
        selected = {m["ts"]: m for m in (root, *recent)}
        history = []
        for message in selected.values():
            if message.get("files") or message.get("attachments"):
                raise SemanticError("unsupported-prior-media-or-identity")
            if len(json.dumps(message, ensure_ascii=False).encode()) > 65536:
                raise SemanticError("oversized-prior-context")
            sender = identifier(message["user"])
            text, provenance = canonical_text(message)
            if not isinstance(text, str) or len(text) > 6000:
                raise SemanticError("oversized-prior-context")
            history.append(History(message["ts"], sender, text, copy.deepcopy(message), provenance))
        return tuple(history)

    async def project(self, body, bound, adapter, deadline, bridge, topology):
        event = copy.deepcopy(body["event"])
        if event.get("subtype") == "message_changed":
            event.update(event.get("message") or {})
            event.pop("message", None)
        thread = bound.event.thread

        if bound.event.provenance == "file_shared" or event.get("files") or event.get("attachments"):
            return self.unresolved("unsupported-current-composition")
        try:
            text, provenance = canonical_text(event)
        except (SemanticError, KeyError, TypeError):
            return self.unresolved("unsupported-current-composition")
        if not self.native_policy(adapter, event, bound.recipient.bot_user):
            return None
        client = adapter._team_clients[thread.workspace]
        from slack_sdk.errors import SlackClientError

        try:
            history = await self.history(client, thread, bound.source.message_id, deadline)
        except (SlackClientError, OSError, TimeoutError):
            return self.unresolved("context-fetch-failed")
        except (ValueError, KeyError, TypeError, AttributeError):
            return self.unresolved("incomplete-context")
        if await bridge.participants(bound) != topology:
            return self.unresolved("native-topology-changed")
        source = Snapshot(
            thread,
            bound.event.identity,
            bound.event.sender,
            text,
            history,
            topology[0],
            copy.deepcopy(body["event"]),
            provenance,
        )
        try:
            async with asyncio.timeout_at(deadline):
                # The serving runtime may differ from the receiving adapter's profile.
                async with adapter.gateway_runner._async_profile_scope_for_source(bound.source):
                    plan = assemble(source, await self.jev.ask(prepare(source)))
        except (JevError, SemanticError, TimeoutError):
            return self.unresolved("classifier-failed")
        if await bridge.participants(bound) != topology:
            return self.unresolved("native-topology-changed")
        if plan.status != "ready":
            return self.unresolved("coverage-or-grounding-unresolved")
        text = plan.view(bound.recipient)
        if not text:
            return None
        projected = copy.deepcopy(body)
        target = projected["event"]
        if target.get("subtype") == "message_changed":
            target["text"] = text
            target = target["message"]
        target["text"] = text
        for field in ("blocks", "attachments", "files"):
            target.pop(field, None)
            projected["event"].pop(field, None)
        current = "".join(
            plan.source[u.start : u.end]
            for u in plan.units
            if u.disposition == "action" and bound.recipient in u.recipients
        )
        admission = {**event, "text": current}
        admission.pop("blocks", None)
        if not self.native_policy(adapter, admission, bound.recipient.bot_user):
            return None
        return projected

    def dispose(self):
        self.disposed = True

    def wire(self, native, adapter):
        from slack_bolt.response import BoltResponse

        bridge = Bridge(adapter)

        async def evaluate(body, deadline):
            bound = await bridge.bind(body)
            key = bound.event.thread
            if bridge.pending(bound):
                return body
            if adapter._early_reject_unauthorized(bound.event.sender, key.channel, False, thread_id=key.root):
                return None
            try:
                topology = await bridge.participants(bound)
                projected = await self.project(body, bound, adapter, deadline, bridge, topology)
            except (Exception, asyncio.CancelledError):
                if bridge.pending(bound):
                    return body
                raise
            if self.disposed or bridge.pending(bound):
                return body
            if adapter._team_bot_user_ids.get(key.workspace) != bound.recipient.bot_user:
                return self.unresolved("native-receiver-changed")
            return projected

        async def middleware(body, next, req):
            if self.disposed:
                return await next()
            try:
                deadline = time.monotonic() + 2.5
                async with asyncio.timeout_at(deadline):
                    projected = await evaluate(body, deadline)
                if projected is None:
                    return BoltResponse(status=200, body="")
                req.body = projected
            except Uncertain:
                logger.debug("agent-router native exemption or unknown identity/control; pass-through")
            except TopologyError:
                self.unresolved("native-topology-unresolved")
                return BoltResponse(status=200, body="")
            except Exception:  # noqa: BLE001 - fail closed at ingress without logging untrusted payloads
                self.unresolved("ingress-failed")
                return BoltResponse(status=200, body="")
            return await next()

        native.use(middleware)


def register(ctx):
    gates = []
    disposed = False

    def dispose():
        nonlocal disposed
        disposed = True
        for gate in gates:
            gate.dispose()

    def wire(native, adapter):
        if disposed:
            return
        gate = Gate()
        gates.append(gate)
        gate.wire(native, adapter)

    ctx.register_platform_handler("slack", wire)
    ctx.on_unload(dispose)
