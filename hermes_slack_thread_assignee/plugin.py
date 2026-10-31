"""Official native factory/global middleware; no listener or transport replacement."""

import asyncio
import copy
import logging
import os
import time
from pathlib import Path

from .bridge import Bridge, Uncertain, canonical_text, composition
from .config import Config
from .jev import JevClient
from .plans import PlanStore
from .semantic import History, Plan, SemanticError, Snapshot

logger = logging.getLogger(__name__)


class Gate:
    def __init__(self, store, *, monitoring=(), semantic=None):
        self.store = store
        self.monitoring = frozenset(tuple(item) for item in monitoring)
        self.disposed = False
        self.semantic = semantic
        self.jev = JevClient()

    @staticmethod
    def native_policy(adapter, event, bot):
        """Pure admission intersection; native wake runs exactly once downstream."""
        channel = event["channel"]
        text = event.get("text", "")
        own = {bot, adapter._bot_user_id} - {None, ""}
        mentioned = bool(set(composition(event)) & own)
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
        assert self.semantic is not None
        plans = PlanStore(self.store)
        event = copy.deepcopy(body["event"])
        if event.get("subtype") == "message_changed":
            event.update(event.get("message") or {})
            event.pop("message", None)
        main, revision = await asyncio.to_thread(self.store.show, bound.event.thread)
        source = Snapshot(
            bound.event.thread,
            bound.event.identity,
            bound.event.sender,
            event.get("text", ""),
            (),
            tuple(r for r in self.store.participants if r.workspace == bound.event.thread.workspace),
            self.store.metadata["registry_revision"],
            self.semantic.policy_revision,
            revision,
            main,
        )

        async def unresolved(reason):
            claim = await asyncio.to_thread(plans.claim, source)
            if claim.owner:
                await asyncio.to_thread(
                    plans.publish,
                    source,
                    claim.fence,
                    Plan(source.binding, "unresolved", reason, source.text),
                )

        classes = next(
            (
                classes
                for workspace, channel, classes in self.semantic.scopes
                if workspace == source.thread.workspace and channel == source.thread.channel
            ),
            (),
        )
        if not any(self.semantic.permits(source.thread, kind) for kind in classes):
            return await unresolved("privacy-disabled")
        if event.get("files") or event.get("attachments"):
            return await unresolved("unsupported-current-composition")
        try:
            text, provenance = canonical_text(event)
        except (SemanticError, KeyError, TypeError):
            return await unresolved("unsupported-current-composition")
        from dataclasses import replace

        source = replace(source, text=text, provenance=provenance)
        if not self.native_policy(adapter, event, bound.recipient.bot_user):
            await asyncio.to_thread(plans.record, source, bound.recipient, "native-not-admitted-original")
            return None
        client = adapter._team_clients[source.thread.workspace]
        from slack_sdk.errors import SlackClientError

        try:
            response = await client.conversations_replies(
                channel=source.thread.channel,
                ts=source.thread.root,
                latest=bound.source.message_id,
                inclusive=False,
                limit=7,
            )
        except asyncio.CancelledError:
            await asyncio.shield(unresolved("context-deadline-or-cancelled"))
            raise
        except (SlackClientError, OSError, ValueError):
            return await unresolved("context-fetch-failed")
        messages = response.get("messages", [])
        if response.get("ok") is not True or response.get("has_more") or len(messages) > 6:
            return await unresolved("incomplete-context")
        if source.thread.root != bound.source.message_id and not any(
            item.get("ts") == source.thread.root for item in messages
        ):
            return await unresolved("missing-root-context")
        history = []
        for message in messages:
            if message.get("ts") == bound.source.message_id:
                continue
            if (
                message.get("files")
                or message.get("attachments")
                or not message.get("ts")
                or not message.get("user")
            ):
                return await unresolved("unsupported-prior-media-or-identity")
            try:
                prior_text, _ = canonical_text(message)
            except (SemanticError, KeyError, TypeError):
                return await unresolved("unsupported-prior-composition")
            history.append(
                History(
                    message["ts"],
                    message["user"],
                    prior_text,
                    "prior-" + message["ts"],
                    copy.deepcopy(message),
                )
            )

        source = replace(source, history=tuple(history), original=copy.deepcopy(body["event"]))
        plan = await plans.resolve(source, self.jev, budget=max(0, deadline - time.monotonic()))
        if await asyncio.to_thread(self.store.show, source.thread) != (main, revision):
            return await unresolved("stale-main")
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
        admission = {**event, "text": text}
        admission.pop("blocks", None)
        if not self.native_policy(adapter, admission, bound.recipient.bot_user):
            await asyncio.to_thread(plans.record, source, bound.recipient, "native-not-admitted")
            return None
        await asyncio.to_thread(plans.record, source, bound.recipient, "selected-projected-not-delivery")
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
            if self.semantic is not None:
                try:
                    projected = await self.project(body, bound, adapter, deadline)
                except (Exception, asyncio.CancelledError):
                    if bridge.pending(bound):
                        return body
                    raise
                if self.disposed or bridge.pending(bound):
                    return body
                return projected
            decision = await asyncio.to_thread(self.store.decide, bound.event, bound.recipient)
            if decision.action == "drop" and not self.disposed and not bridge.pending(bound):
                return None
            return body

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
            except Uncertain as exc:
                logger.debug("thread-assignee native pass-through: %s", exc)
            except Exception:
                if self.semantic is not None:
                    logger.warning("thread-assignee semantic unresolved; no native inference", exc_info=True)
                    return BoltResponse(status=200, body="")
                logger.warning("thread-assignee classification failed; native pass-through", exc_info=True)
            return await next()

        native.use(middleware)


def register(ctx):
    from .cli import parser, run

    ctx.register_cli_command("thread-assignee", "Inspect or administer shared Slack assignments", parser, run)
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
        if not path:
            raise ValueError(
                "Set HERMES_THREAD_ASSIGNEE_CONFIG to an absolute shared JSON config; routing is not active"
            )
        config = Config.load(Path(path))
        gate = Gate(config.store(), monitoring=config.monitoring, semantic=config.semantic)
        gates.append(gate)
        gate.wire(native, adapter)

    ctx.register_platform_handler("slack", wire)
    ctx.on_unload(dispose)
