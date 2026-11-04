"""Request-local contextual routing through the official native middleware seam."""

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field, replace
from decimal import Decimal

from .bridge import Bridge, TopologyError, Uncertain, message_content
from .jev import JevClient, JevError, serialize_request
from .policy import Thread, identifier
from .semantic import History, SemanticError, Snapshot, prepare

logger = logging.getLogger(__name__)


@dataclass(eq=False)
class Evaluation:
    sender: str
    root: str
    revision: Decimal
    tasks: set = field(default_factory=set)
    invalidated: bool = False


class Gate:
    def __init__(self):
        self.disposed = False
        self.jev = JevClient()
        self.active = {}

    @staticmethod
    def unresolved(reason):
        # Fixed local reason codes only: no transcript, raw model answer or durable queue.
        logger.warning("agent-router unresolved: %s", reason)
        return False

    @staticmethod
    async def history(client, thread, cutoff) -> tuple[History, ...]:
        """Read newest replies, following older cursors only to fill a short tail.

        Selection is newest-before-cutoff; order inside each page is ascending.
        SDK JSON buffering/retry behavior remains native; caps are post-decode.
        """
        if cutoff == thread.root:
            return ()  # The root is CURRENT, never its own prior reference.
        root = None
        recent, seen = [], {}
        cursor, cursors = "", set()

        def records(response, limit, extra_root=False):
            data = getattr(response, "data", response)
            size = len(json.dumps(data, ensure_ascii=False, allow_nan=False).encode())
            messages = data.get("messages")
            metadata = data.get("response_metadata", {})
            if (
                data.get("ok") is not True
                or not isinstance(messages, list)
                or len(messages) > limit + int(extra_root)
                or (
                    len(messages) > limit
                    and sum(isinstance(m, dict) and m.get("ts") == thread.root for m in messages) != 1
                )
                or size > 1048576
                or not isinstance(metadata, dict)
                or type(data.get("has_more", False)) is not bool
            ):
                raise SemanticError("incomplete-context")
            cursor = metadata.get("next_cursor", "")
            if (
                not isinstance(cursor, str)
                or len(cursor) > 2048
                or (extra_root and data.get("has_more") and not cursor)
            ):
                raise SemanticError("incomplete-context")
            return messages, cursor

        def validate(message):
            ts = message["ts"]
            Thread(thread.workspace, thread.channel, ts)
            if (
                Decimal(ts) > Decimal(cutoff)
                or Decimal(ts) < Decimal(thread.root)
                or ("thread_ts" in message and message["thread_ts"] != thread.root)
                or ("channel" in message and message["channel"] != thread.channel)
                or ("team" in message and message["team"] != thread.workspace)
            ):
                raise SemanticError("foreign-or-future-context")
            return ts

        # At most four SDK calls/4 MiB decoded, INCLUDING optional exact root.
        for page in range(4):
            args: dict = {
                "channel": thread.channel,
                "ts": thread.root,
                "latest": cutoff,
                "inclusive": False,
                "limit": 7,
            }
            if cursor:
                args["cursor"] = cursor
            response = await client.conversations_replies(**args)
            messages, next_cursor = records(response, 7, extra_root=True)
            last = Decimal(thread.root)
            ceiling = Decimal(recent[0]["ts"]) if recent else Decimal(cutoff)
            for message in messages:
                ts = validate(message)
                if ts == cutoff:
                    continue
                if ts != thread.root:
                    if Decimal(ts) < last:
                        raise SemanticError("unordered-context")
                    last = Decimal(ts)
                encoded = json.dumps(message, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
                digest = hashlib.sha256(encoded).digest()
                if ts in seen:
                    if seen[ts] != digest:
                        raise SemanticError("conflicting-context")
                    continue
                seen[ts] = digest
                if ts == thread.root:
                    root = message  # Known ID, independent of page placement/count.
                else:
                    if page and Decimal(ts) >= ceiling:
                        raise SemanticError("unordered-context")
                    recent.append(message)
            recent = sorted(recent, key=lambda m: Decimal(m["ts"]))[-7:]
            if len(recent) == 7 or not next_cursor:
                break  # Complete bounded tail, or proven genuinely short thread.
            if next_cursor in cursors:
                raise SemanticError("incomplete-context")
            cursors.add(next_cursor)
            cursor = next_cursor  # Opaque older continuation, even on empty/filtered pages.
        else:
            raise SemanticError("incomplete-context")
        if root is None:
            if page == 3:
                raise SemanticError("incomplete-context")
            # Slack's documented exact-known-message lookup; never scan channel history.
            response = await client.conversations_history(
                channel=thread.channel, oldest=thread.root, inclusive=True, limit=1
            )
            messages, _ = records(response, 1)
            if len(messages) != 1 or validate(messages[0]) != thread.root:
                raise SemanticError("missing-root-context")
            root = messages[0]
        history = []
        for message in (root, *recent):
            if message.get("files") or message.get("attachments"):
                raise SemanticError("unsupported-prior-media-or-identity")
            sender = identifier(message["user"])
            text, blocks = message_content(message)
            if not isinstance(text, str):
                raise SemanticError("unsupported-prior-composition")
            history.append(History(message["ts"], sender, text, blocks))
        return tuple(history)

    @staticmethod
    def fit(source, recipient):
        """Fit the actual wire request by shedding only whole oldest non-root priors."""
        dropped = 0
        while True:
            batch = prepare(source, recipient)
            try:
                raw = serialize_request(batch)
            except JevError as exc:
                if exc.diagnostic[0] != "request-oversized":
                    raise
                oldest = next((h for h in source.history if h.identity != source.thread.root), None)
                if oldest is None:
                    raise JevError("unsupported request size", size=exc.size, dropped=dropped) from None
                history = tuple(h for h in source.history if h is not oldest)
                people = {
                    source.sender,
                    *(h.sender for h in history),
                    *(r.bot_user for r in source.recipients),
                }
                source = replace(
                    source,
                    history=history,
                    context_people=tuple(
                        (user, row) for user, row in source.context_people if user in people
                    ),
                )
                dropped += 1
            else:
                if dropped:
                    logger.info("agent-router request-fit stage=fit bytes=%d dropped=%d", len(raw), dropped)
                return source, batch

    async def excludes(self, bound, adapter, bridge, topology):
        event = dict(bound.native_event)
        thread = bound.event.thread
        event.update(team=thread.workspace, channel=thread.channel)

        if bound.event.provenance == "file_shared" or event.get("files") or event.get("attachments"):
            return self.unresolved("unsupported-current-composition")
        try:
            text, blocks = message_content(event)
        except (SemanticError, KeyError, TypeError):
            return self.unresolved("unsupported-current-composition")
        client = adapter._team_clients[thread.workspace]
        from slack_sdk.errors import SlackApiError, SlackClientError

        try:
            # Independent request-owned acquisitions; cancel and drain the sibling
            # on failure/caller cancellation, without imposing an elapsed cutoff.
            requests = [
                asyncio.create_task(self.history(client, thread, bound.source.message_id)),
                asyncio.create_task(bridge.recipient_metadata(bound, topology)),
            ]
            try:
                history, whoami = await asyncio.gather(*requests)
            finally:
                for request in requests:
                    request.cancel()
                await asyncio.gather(*requests, return_exceptions=True)
        except SlackApiError as exc:
            code = exc.response.get("error")
            if code in {
                "missing_scope",
                "not_allowed_token_type",
                "no_permission",
                "access_denied",
                "not_authed",
                "invalid_auth",
                "token_expired",
                "token_revoked",
                "account_inactive",
                "channel_not_found",
                "team_access_not_granted",
            }:
                return self.unresolved("context-fetch-not-permitted")
            if code in {"ratelimited", "rate_limited"}:
                return self.unresolved("context-fetch-rate-limited")
            return self.unresolved("context-fetch-api-failed")
        except TimeoutError:
            return self.unresolved("context-fetch-transport-timeout")
        except (SlackClientError, OSError):
            return self.unresolved("context-fetch-failed")
        except SemanticError as exc:
            # Never log arbitrary exceptions/SDK bodies. Only these source-owned codes.
            code = str(exc)
            return self.unresolved(
                code
                if code
                in {
                    "incomplete-context",
                    "foreign-or-future-context",
                    "conflicting-context",
                    "unordered-context",
                    "missing-root-context",
                    "unsupported-prior-media-or-identity",
                }
                else "unsupported-prior-composition"
            )
        except (ValueError, KeyError, TypeError, AttributeError):
            return self.unresolved("incomplete-context")
        if await bridge.participants(bound) != topology:
            return self.unresolved("native-topology-changed")
        people = await bridge.context_people(bound, history, whoami)
        source = Snapshot(
            thread,
            bound.event.identity,
            bound.event.sender,
            text,
            history,
            topology[0],
            blocks,
            recipient_whoami=whoami,
            context_people=people,
        )
        started, stage, questions = time.monotonic(), "credential-scope", 0
        try:
            # The serving runtime may differ from the receiving adapter's profile.
            async with adapter.gateway_runner._async_profile_scope_for_source(bound.source):
                if (
                    self.disposed
                    or getattr(adapter.gateway_runner, "_draining", False)
                    or await bridge.participants(bound) != topology
                ):
                    return False
                stage = "fit"
                source, batch = self.fit(source, bound.recipient)
                questions = len(batch["questions"])
                stage = "inference"
                response, confidence = await self.jev.ask(batch)
        except (JevError, SemanticError, TimeoutError) as exc:
            reason, status = (
                exc.diagnostic
                if isinstance(exc, JevError)
                else ("transport-timeout" if isinstance(exc, TimeoutError) else "semantic-invalid", 0)
            )
            # Source-owned codes and numeric measurements, never exception payloads.
            logger.warning(
                "agent-router unresolved: classifier-failed stage=%s reason=%s status=%d "
                "elapsed_ms=%d questions=%d bytes=%d dropped=%d",
                stage,
                reason,
                status,
                (time.monotonic() - started) * 1000,
                questions,
                exc.size if isinstance(exc, JevError) else 0,
                exc.dropped if isinstance(exc, JevError) else 0,
            )
            return False
        if await bridge.participants(bound) != topology:
            return self.unresolved("native-topology-changed")
        return response == "no" and confidence > 0.5

    def dispose(self):
        self.disposed = True

    @staticmethod
    def coordinates(body):
        """Structural source/revision only, before any awaited identity lookup."""
        event = body.get("event") or {}
        if body.get("type") != "event_callback" or event.get("type") not in ("message", "app_mention"):
            return None
        changed = event.get("subtype") == "message_changed"
        message = event.get("message") if changed else event
        if not isinstance(message, dict):
            return None
        team = body.get("team_id")
        channel = message.get("channel") or event.get("channel")
        ts, sender = message.get("ts"), message.get("user")
        if (
            not isinstance(team, str)
            or not isinstance(channel, str)
            or not isinstance(ts, str)
            or not isinstance(sender, str)
        ):
            return None
        for item in (event, message):
            if (item.get("team") and item["team"] != team) or (
                item.get("channel") and item["channel"] != channel
            ):
                raise SemanticError("conflicting revision source")
        Thread(team, channel, ts)
        identifier(sender)
        root = message.get("thread_ts") or ts
        Thread(team, channel, root)
        edit = message.get("edited")
        if changed and (not isinstance(edit, dict) or not edit.get("ts")):
            return None  # An unfurl/delivery event_ts is not an edit revision.
        revision = ts
        if edit is not None:
            if not isinstance(edit, dict) or not isinstance(edit.get("ts"), str):
                raise SemanticError("invalid edit revision")
            revision = edit["ts"]
            Thread(team, channel, revision)
            if Decimal(revision) <= Decimal(ts):
                raise SemanticError("invalid edit revision")
        return (team, channel, ts), sender, root, Decimal(revision)

    def wire(self, native, adapter):
        from slack_bolt.response import BoltResponse

        bridge = Bridge(adapter)

        async def evaluate(body):
            bound = await bridge.bind(body)
            if bridge.pending(bound):
                return False
            topology = await bridge.participants(bound)
            excluded = await self.excludes(bound, adapter, bridge, topology)
            if bridge.pending(bound):
                return False
            return bool(excluded)

        async def middleware(body, next, req):
            entry = task = key = None
            excluded = False
            try:
                if getattr(adapter.gateway_runner, "_draining", False):
                    return BoltResponse(status=200, body="")
                coordinates = self.coordinates(body)
                if coordinates is not None:
                    key, sender, root, revision = coordinates
                    previous = self.active.get(key)
                    if previous is not None:
                        if (previous.sender, previous.root) != (sender, root):
                            raise SemanticError("conflicting revision source")
                        if revision < previous.revision:
                            return BoltResponse(status=200, body="")
                    if previous is None or revision > previous.revision:
                        retiring = set(previous.tasks) if previous is not None else set()
                        if previous is not None:
                            previous.invalidated = True
                        entry = Evaluation(sender, root, revision, set(retiring))
                        self.active[key] = entry  # Invalidate BEFORE awaiting old cleanup.
                        for old in retiring:
                            if not old.cancelling():
                                old.cancel()
                        if retiring:
                            await asyncio.gather(*retiring, return_exceptions=True)
                            entry.tasks.difference_update(retiring)
                        if self.active.get(key) is not entry or entry.invalidated:
                            return BoltResponse(status=200, body="")
                    else:
                        entry = previous  # Equal-revision duplicate, not a cancellation.
                if getattr(adapter.gateway_runner, "_draining", False):
                    return BoltResponse(status=200, body="")
                if not self.disposed:
                    task = asyncio.create_task(evaluate(body))
                    adapter._background_tasks.add(task)
                    task.add_done_callback(adapter._background_tasks.discard)
                    if entry is not None:
                        entry.tasks.add(task)
                    try:
                        excluded = await task
                    except Uncertain:
                        logger.debug(
                            "agent-router native exemption or unknown identity/control; pass-through"
                        )
                    except asyncio.CancelledError:
                        current = asyncio.current_task()
                        if current is not None and current.cancelling():
                            raise  # Caller cancellation is terminal.
                        if entry is None or not entry.invalidated:
                            raise  # Native adapter shutdown is terminal.
                        return BoltResponse(status=200, body="")
                    if task.cancelling() and (entry is None or not entry.invalidated):
                        raise asyncio.CancelledError
            except TopologyError:
                self.unresolved("native-topology-unresolved")
            except Exception:  # noqa: BLE001 - fixed diagnostics, no untrusted payload
                self.unresolved("ingress-failed")
            finally:
                if task is not None:
                    if not task.done():
                        task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                if entry is not None:
                    entry.tasks.difference_update(t for t in tuple(entry.tasks) if t.done())
                    if self.active.get(key) is entry and not entry.tasks:
                        self.active.pop(key, None)
            if (
                (excluded and not self.disposed)
                or getattr(adapter.gateway_runner, "_draining", False)
                or (entry is not None and entry.invalidated)
            ):
                return BoltResponse(status=200, body="")
            return await next()  # Outside classifier catch; native failures are never retried.

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
