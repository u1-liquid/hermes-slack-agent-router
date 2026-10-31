"""Request-local contextual routing through the official native middleware seam."""

import asyncio
import copy
import logging
import os
import time
from decimal import Decimal
from pathlib import Path

from .bridge import Bridge, Uncertain, canonical_text, composition
from .config import Config, SemanticPolicy
from .jev import JevClient, JevError
from .policy import Thread, identifier
from .semantic import History, SemanticError, Snapshot, assemble, prepare

logger = logging.getLogger(__name__)


class Gate:
    def __init__(self, participants, *, monitoring=(), semantic=None):
        self.participants = tuple(participants)
        self.monitoring = frozenset(tuple(item) for item in monitoring)
        self.disposed = False
        self.semantic = semantic if semantic is not None else SemanticPolicy()
        self.jev = JevClient()

    @staticmethod
    def unresolved(reason):
        # Fixed local reason codes only: no transcript, raw model answer or durable queue.
        logger.warning("thread-assignee unresolved: %s", reason)

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

    async def project(self, body, bound, adapter, deadline):
        event = copy.deepcopy(body["event"])
        if event.get("subtype") == "message_changed":
            event.update(event.get("message") or {})
            event.pop("message", None)
        thread = bound.event.thread
        if not any(self.semantic.permits(thread, kind) for kind in ("fictional", "public-permitted")):
            return self.unresolved("privacy-disabled")
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
            response = await client.conversations_replies(
                channel=thread.channel,
                ts=thread.root,
                latest=bound.source.message_id,
                inclusive=False,
                limit=7,
            )
        except (SlackClientError, OSError, ValueError):
            return self.unresolved("context-fetch-failed")
        messages = response.get("messages", [])
        if (
            response.get("ok") is not True
            or response.get("has_more")
            or not isinstance(messages, list)
            or len(messages) > 7
        ):
            return self.unresolved("incomplete-context")
        history = {}
        for message in messages:
            if message.get("ts") == bound.source.message_id:
                continue
            if message.get("files") or message.get("attachments"):
                return self.unresolved("unsupported-prior-media-or-identity")
            try:
                ts = message["ts"]
                Thread(thread.workspace, thread.channel, ts)
                sender = identifier(message["user"])
                if (
                    Decimal(ts) >= Decimal(bound.source.message_id)
                    or Decimal(ts) < Decimal(thread.root)
                    or (message.get("thread_ts") and message["thread_ts"] != thread.root)
                    or (message.get("channel") and message["channel"] != thread.channel)
                    or (message.get("team") and message["team"] != thread.workspace)
                ):
                    return self.unresolved("foreign-or-future-context")
                prior_text, _ = canonical_text(message)
                prior = History(ts, sender, prior_text, copy.deepcopy(message))
            except (ValueError, KeyError, TypeError):
                return self.unresolved("unsupported-prior-composition")
            if ts in history and history[ts] != prior:
                return self.unresolved("conflicting-context")
            history[ts] = prior
        if len(history) > 6:
            return self.unresolved("incomplete-context")
        if thread.root != bound.source.message_id and thread.root not in history:
            return self.unresolved("missing-root-context")
        source = Snapshot(
            thread,
            bound.event.identity,
            bound.event.sender,
            text,
            tuple(history.values()),
            tuple(r for r in self.participants if r.workspace == thread.workspace),
            self.semantic.policy_revision,
            copy.deepcopy(body["event"]),
            provenance,
        )
        try:
            async with asyncio.timeout_at(deadline):
                plan = assemble(source, await self.jev.ask(prepare(source)))
        except (JevError, SemanticError, TimeoutError):
            return self.unresolved("classifier-failed")
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
            exempt = (key.workspace, key.channel, bound.event.sender) in self.monitoring
            if exempt or bridge.pending(bound):
                return body
            if bound.recipient not in self.participants:
                raise Uncertain("unconfigured receiving runtime")
            if adapter._early_reject_unauthorized(bound.event.sender, key.channel, False, thread_id=key.root):
                return None
            try:
                projected = await self.project(body, bound, adapter, deadline)
            except (Exception, asyncio.CancelledError):
                if bridge.pending(bound):
                    return body
                raise
            if self.disposed or bridge.pending(bound):
                return body
            if adapter._team_bot_user_ids.get(key.workspace) != bound.recipient.bot_user:
                raise Uncertain("native receiver changed")
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
                logger.debug("thread-assignee native exemption or unknown identity/control; pass-through")
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
        path = os.environ.get("HERMES_THREAD_ASSIGNEE_CONFIG")
        if not path or not Path(path).is_absolute():
            raise ValueError(
                "Set HERMES_THREAD_ASSIGNEE_CONFIG to an absolute participant/input-policy config; routing is not active"
            )
        config = Config.load(Path(path))
        gate = Gate(config.participants, monitoring=config.monitoring, semantic=config.semantic)
        gates.append(gate)
        gate.wire(native, adapter)

    ctx.register_platform_handler("slack", wire)
    ctx.on_unload(dispose)
