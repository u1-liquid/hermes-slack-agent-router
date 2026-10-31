"""Read-only integration with official Hermes bf0203a794a0 private seams."""

import asyncio
import re
from dataclasses import dataclass

from .policy import Event, Recipient, Thread, addresses


class Uncertain(ValueError):
    """Insufficient evidence: preserve native processing, never guess."""


class TopologyError(ValueError):
    """An ordinary request lacks a stable, authoritative native candidate view."""


def canonical_text(event, *, prior=False):
    """Flatten supported source fields, preserving exact leaf paths and ranges.

    Human CURRENT composition remains rich_text-only. Prior Slack bot responses
    also use native markdown and text-only section blocks; their notification
    fallback is not a substitute for the visible authored source.
    """
    from .semantic import SemanticError

    if not event.get("blocks"):
        text = event.get("text", "")
        return text, (
            {
                "field": "text",
                "start": 0,
                "end": len(text),
                "kind": "authored",
                "raw": text,
                "source_start": 0,
                "source_end": len(text),
                "mapping": "literal",
            },
        )
    pieces, provenance = [], []
    offset = 0

    def append(text, path, kind, *, raw=None, mapping="literal"):
        nonlocal offset
        structural = kind == "separator"
        raw = text if raw is None and not structural else raw
        pieces.append(text)
        provenance.append(
            {
                "field": None if structural else path,
                "start": offset,
                "end": offset + len(text),
                "kind": kind,
                "raw": raw,
                "mapping": "separator" if structural else mapping,
                "source_start": None if structural else 0,
                "source_end": None if structural else len(raw),
            }
        )
        offset += len(text)

    def visit(node, path, kind="authored"):
        tag = node.get("type")
        if tag in (
            "rich_text",
            "rich_text_section",
            "rich_text_list",
            "rich_text_quote",
            "rich_text_preformatted",
        ):
            if tag in ("rich_text_quote", "rich_text_preformatted"):
                kind = "reference"
            children = node.get("elements", [])
            for i, child in enumerate(children):
                if i and tag in ("rich_text", "rich_text_list"):
                    append("\n", path, "separator")
                visit(child, f"{path}.elements[{i}]", kind)
        elif tag == "text":
            append(node["text"], path + ".text", "reference" if node.get("style", {}).get("code") else kind)
        elif tag == "user":
            append(
                "<@" + node["user_id"] + ">",
                path + ".user_id",
                kind,
                raw=node["user_id"],
                mapping="slack-user",
            )
        elif tag == "link":
            append(node.get("text") or node["url"], path + (".text" if node.get("text") else ".url"), kind)
        elif tag == "emoji":
            append(":" + node["name"] + ":", path + ".name", kind, raw=node["name"], mapping="emoji")
        else:
            raise SemanticError("unsupported authored rich_text element")

    for i, block in enumerate(event["blocks"]):
        path = f"blocks[{i}]"
        if i:
            append("\n", "blocks", "separator")
        if block.get("type") == "rich_text":
            visit(block, path)
        elif prior and block.get("type") == "markdown" and isinstance(block.get("text"), str):
            append(block["text"], path + ".text", "authored")
        elif (
            prior
            and block.get("type") == "section"
            and not (set(block) - {"type", "block_id", "text", "expand"})
            and isinstance(block.get("text"), dict)
            and block["text"].get("type") in ("mrkdwn", "plain_text")
            and isinstance(block["text"].get("text"), str)
        ):
            append(block["text"]["text"], path + ".text.text", "authored")
        else:
            raise SemanticError("unsupported prior block" if prior else "unsupported current block")
    result = "".join(pieces)
    for part in provenance:
        mapping = part["mapping"]
        if mapping == "separator":
            continue
        raw = part["raw"]
        rendered = (
            "<@" + raw + ">" if mapping == "slack-user" else ":" + raw + ":" if mapping == "emoji" else raw
        )
        if result[part["start"] : part["end"]] != rendered:
            raise SemanticError("canonical source provenance does not roundtrip")
    return result, tuple(provenance)


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

    async def participants(self, bound):
        """Resolve this event on each live local transport, without retaining a registry."""
        from gateway.config import Platform

        runner = self.adapter.gateway_runner
        if runner is None or getattr(runner, "_draining", False):
            raise TopologyError("native runner unavailable")
        authorities = runner.session_authorities
        primary = runner._primary_profile_name
        maps = [(primary, runner._primary_adapters())]
        maps.extend(runner._profile_adapters_map().items())
        slots = tuple((name, mapping.get(Platform.SLACK)) for name, mapping in maps)
        seen, result, observed = {}, [], []
        team = bound.event.thread.workspace

        def authority(home, name):
            value = authorities.for_home(home)
            if value is None or getattr(value, "retiring", False):
                raise TopologyError("unserved native runtime")
            registered = authorities.profile_name(value) or primary
            if registered != name:
                raise TopologyError("native runtime name/home mismatch")
            return value

        def identity_for(adapter):
            # Native identities pin their source. Rebuild it to observe route changes.
            thread = bound.event.thread
            source = adapter.build_source(
                chat_id=thread.channel,
                chat_type="group",
                user_id=bound.event.sender,
                thread_id=thread.root,
                scope_id=team,
                message_id=bound.source.message_id,
            )
            return adapter._canonicalize(source)

        for owner, adapter in slots:
            if adapter is None:
                continue
            if id(adapter) in seen:
                if seen[id(adapter)] != owner:
                    raise TopologyError("ambiguous native transport owner")
                continue
            seen[id(adapter)] = owner

            bot = adapter._team_bot_user_ids.get(team)
            client = adapter._team_clients.get(team)
            if not bot and client is None:
                continue  # Another workspace is not a source of participating identities.
            if not bot or client is None or adapter.gateway_runner is not runner:
                raise TopologyError("incomplete native workspace identity")
            task = adapter._socket_mode_task
            if not adapter.is_connected or task is None or task.done() or adapter._message_handler is None:
                continue
            app, handler = adapter._app, adapter._handler
            connected = await self.call(adapter._socket_transport_connected())
            if connected is None:
                raise TopologyError("unknown native socket state")
            if not connected or adapter._socket_ping_pong_stale():
                continue
            identity = identity_for(adapter)
            if (
                identity is None
                or identity.adapter() is not adapter
                or identity.transport_inferred
                or identity.transport_profile != owner
            ):
                raise TopologyError("unresolved native participant")
            transport = authority(identity.authorization_home, owner)
            runtime = authority(identity.runtime_home, identity.runtime_profile)
            recipient = Recipient(team, bot, identity.runtime_profile)
            witness = (
                id(adapter),
                owner,
                id(app),
                id(client),
                id(handler),
                id(task),
                identity,
                id(transport),
                id(runtime),
            )
            result.append((recipient, witness))
            observed.append((adapter, bot, client, app, handler, task, identity, transport, runtime))
        # Socket inspection can await. Validate every captured generation together
        # after the last await; otherwise a peer can change during the final check.
        for adapter, bot, client, app, handler, task, identity, transport, runtime in observed:
            if (
                getattr(runner, "_draining", False)
                or adapter._team_bot_user_ids.get(team) != bot
                or adapter._team_clients.get(team) is not client
                or adapter._app is not app
                or adapter._handler is not handler
                or adapter._socket_mode_task is not task
                or task.done()
                or not adapter.is_connected
                or adapter._message_handler is None
                or identity_for(adapter) != identity
                or authority(identity.authorization_home, identity.transport_profile) is not transport
                or authority(identity.runtime_home, identity.runtime_profile) is not runtime
            ):
                raise TopologyError("native participant changed during discovery")
        current = [(primary, runner._primary_adapters())]
        current.extend(runner._profile_adapters_map().items())
        if slots != tuple((name, mapping.get(Platform.SLACK)) for name, mapping in current):
            raise TopologyError("native transports changed during discovery")
        result.sort(key=lambda item: (item[0].workspace, item[0].bot_user, item[0].runtime_profile))
        recipients = tuple(item[0] for item in result)
        if (
            bound.recipient not in recipients
            or not 1 <= len(recipients) <= 4
            or len({r.bot_user for r in recipients}) != len(recipients)
        ):
            raise TopologyError("missing or ambiguous native participants")
        return recipients, tuple(item[1] for item in result)

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
            raise TopologyError("unverified native identity")
        session_key = adapter._source_session_key(source)
        recipient = Recipient(team, bot, identity.runtime_profile)
        event_id = ts + (":" + event["edited"]["ts"] if provenance == "edit" else "")
        try:
            direct = composition(event)
        except Uncertain:
            # A verified ordinary human with unknown composition is not a native control exemption.
            # Semantic ingress validates it before any native listener, without retaining content.
            direct = addresses(event.get("text", ""))
        return Bound(
            Event(thread, event_id, sender, direct, provenance=provenance),
            recipient,
            source,
            identity,
            session_key,
        )
