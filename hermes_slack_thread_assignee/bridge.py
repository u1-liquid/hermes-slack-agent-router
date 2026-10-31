"""Read-only integration with official Hermes bf0203a794a0 private seams."""

import asyncio
import re
from dataclasses import dataclass

from .policy import Event, Recipient, Thread, addresses


class Uncertain(ValueError):
    """Insufficient evidence: preserve native processing, never guess."""


def composition(event):
    direct = set() if event.get("blocks") else set(addresses(event.get("text", "")))

    def visit(node):
        kind = node.get("type")
        if kind in ("rich_text_quote", "rich_text_preformatted"):
            return
        if kind == "user":
            if not node.get("style", {}).get("code"):
                direct.add(node["user_id"])
        elif kind in ("rich_text", "rich_text_section", "rich_text_list"):
            for child in node.get("elements", []):
                visit(child)
        elif kind not in ("text", "link", "emoji", "broadcast", "channel", "color", "date"):
            raise Uncertain("unrecognized block composition")

    for block in event.get("blocks", []):
        if block.get("type") != "rich_text":
            raise Uncertain("unsupported non-composition block")
        visit(block)
    return tuple(sorted(direct))


@dataclass
class Bound:
    event: Event
    recipient: Recipient
    source: object
    identity: object
    session_key: str


class Bridge:
    def __init__(self, adapter, *, timeout=0.75):
        self.adapter = adapter
        self.timeout = timeout

    async def call(self, awaitable):
        return await asyncio.wait_for(awaitable, self.timeout)

    def pending(self, bound):
        from tools import approval, clarify_gateway, slash_confirm

        runner = self.adapter.gateway_runner
        if runner is None or self.adapter._source_session_key(bound.source) != bound.session_key:
            raise Uncertain("native session identity changed")
        if runner._session_key_for_source(bound.source) != bound.session_key:
            raise Uncertain("adapter/runner key mismatch")
        # Actual native scope keeps pending reads attached to the routed runtime.
        with runner._profile_scope_for_source(bound.source):
            state = runner._peek_session_state(bound.session_key)
            return bool(
                clarify_gateway.get_pending_for_session(bound.session_key, include_choice_prompts=True)
                or slash_confirm.get_pending(bound.session_key)
                or approval.has_blocking_approval(bound.session_key)
                or (state is not None and state.persistent.update_prompt_pending)
            )

    async def bind(self, body):
        adapter = self.adapter
        if body.get("type") != "event_callback":
            raise Uncertain("not an event callback")
        event = body.get("event") or {}
        kind = event.get("type")
        if kind not in ("message", "app_mention", "file_shared"):
            raise Uncertain("native non-message")
        team = body.get("team_id")
        if not team or (event.get("team") and event["team"] != team):
            raise Uncertain("missing or conflicting workspace")
        bot = adapter._team_bot_user_ids.get(team)
        client = adapter._team_clients.get(team)
        if not bot or client is None or adapter.gateway_runner is None:
            raise Uncertain("unbound workspace/receiver/runtime")
        event = dict(event)
        provenance = "message"
        if event.get("subtype") == "message_changed":
            event = {**event, **(event.get("message") or {})}
            event.pop("message", None)
            if not event.get("edited", {}).get("ts"):
                raise Uncertain("edit identity missing")
            provenance = "edit"
        channel = event.get("channel") or event.get("channel_id")
        if not channel:
            raise Uncertain("missing channel")
        channel_type = event.get("channel_type")
        if channel_type is None:
            info = await self.call(client.conversations_info(channel=channel))
            obj = info.get("channel") or {}
            if info.get("ok") is not True or obj.get("id") != channel:
                raise Uncertain("unverified conversation")
            channel_type = "im" if obj.get("is_im") else "mpim" if obj.get("is_mpim") else "channel"
        if channel_type not in ("channel", "group") or adapter._is_ignored_channel(channel):
            raise Uncertain("native conversation exemption")
        if kind == "file_shared":
            file_id = event.get("file_id")
            if not file_id:
                raise Uncertain("missing file id")
            result = await self.call(client.files_info(file=file_id))
            file = result.get("file") or {}
            if result.get("ok") is not True or not file.get("mimetype", "").startswith("video/"):
                raise Uncertain("outside verified video fallback")
            shares = [
                share
                for bucket in (file.get("shares") or {}).values()
                if isinstance(bucket, dict)
                for share in bucket.get(channel, [])
            ]
            if len(shares) != 1 or not shares[0].get("ts"):
                raise Uncertain("missing/ambiguous exact-channel share")
            sender = event.get("user_id") or file.get("user")
            if event.get("user_id") and file.get("user") and event["user_id"] != file["user"]:
                raise Uncertain("conflicting file sender")
            event.update(user=sender, ts=shares[0]["ts"], thread_ts=shares[0].get("thread_ts"), text="")
            provenance = "file_shared"
        sender = event.get("user")
        if not sender or sender == bot or adapter._event_declares_bot_sender(event):
            raise Uncertain("native bot/self/unknown sender")
        payload = await self.call(client.users_info(user=sender))
        user = payload.get("user") or {}
        if payload.get("ok") is not True or user.get("id") != sender or user.get("is_bot") is not False:
            raise Uncertain("no positive human evidence")
        if adapter._parse_users_info(payload, sender)[1]:
            raise Uncertain("native bot identity")
        text = event.get("text", "")
        probe = re.sub(r"^\s*<@" + re.escape(bot) + r">\s*", "", text).lstrip()
        if probe.startswith("/"):
            raise Uncertain("native slash/skill command")
        if probe.startswith("!"):
            from hermes_cli.commands import resolve_command

            if resolve_command(probe[1:].split()[0]) is not None:
                raise Uncertain("native command alias")
        ts = event.get("ts")
        if not isinstance(ts, str):
            raise Uncertain("missing message timestamp")
        root = event.get("thread_ts") or ts
        thread = Thread(team, channel, root)
        source = adapter.build_source(
            chat_id=channel, chat_type="group", user_id=sender, thread_id=root, scope_id=team, message_id=ts
        )
        identity = adapter._canonicalize(source)
        if identity is None or identity.adapter() is not adapter or identity.transport_inferred:
            raise Uncertain("unverified native identity")
        session_key = adapter._source_session_key(source)
        recipient = Recipient(team, bot, identity.runtime_profile)
        event_id = ts + (":" + event["edited"]["ts"] if provenance == "edit" else "")
        return Bound(
            Event(thread, event_id, sender, composition(event), provenance=provenance),
            recipient,
            source,
            identity,
            session_key,
        )
