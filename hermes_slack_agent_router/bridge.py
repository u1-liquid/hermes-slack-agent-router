"""Read-only integration with qualified official Hermes native seams."""

import asyncio
import copy
import re
from dataclasses import dataclass

from .policy import Event, Recipient, Thread


class Uncertain(ValueError):
    """Insufficient evidence: preserve native processing, never guess."""


class TopologyError(ValueError):
    """Native participant context is unavailable or exceeds its acquisition bound."""


def message_content(event):
    """Validate complete supported content, retaining Slack quote/code structure.

    Unsupported composition skips inference, never ordinary native delivery.
    This is not a renderer, source selector or per-fragment intent check.
    """
    from .semantic import SemanticError

    def invalid():
        raise SemanticError("unsupported message composition")

    def leaf(node):
        if not isinstance(node, dict):
            invalid()
        tag = node.get("type")
        if tag in {
            "rich_text",
            "rich_text_section",
            "rich_text_list",
            "rich_text_quote",
            "rich_text_preformatted",
        }:
            if not isinstance(node.get("elements"), list) or not node["elements"]:
                invalid()
            for child in node["elements"]:
                leaf(child)
        elif tag in {"text", "mrkdwn", "plain_text"}:
            if not isinstance(node.get("text"), str):
                invalid()
            style = node.get("style", {})
            if not isinstance(style, dict) or any(type(v) is not bool for v in style.values()):
                invalid()
        elif tag == "user":
            if not isinstance(node.get("user_id"), str):
                invalid()
        elif tag in {"link", "emoji"}:
            if not isinstance(node.get("url" if tag == "link" else "name"), str):
                invalid()
            if "text" in node and not isinstance(node["text"], str):
                invalid()
        else:
            invalid()

    text, blocks = event.get("text", ""), event.get("blocks", [])
    if not isinstance(text, str) or not isinstance(blocks, list):
        invalid()
    for block in blocks:
        if not isinstance(block, dict):
            invalid()
        tag = block.get("type")
        if tag == "rich_text":
            leaf(block)
        elif tag == "markdown" and isinstance(block.get("text"), str):
            if set(block) - {"type", "block_id", "text"}:
                invalid()
        elif tag == "section" and not (set(block) - {"type", "block_id", "text", "expand"}):
            leaf(block.get("text"))
        elif tag == "context" and not (set(block) - {"type", "block_id", "elements"}):
            if not isinstance(block.get("elements"), list) or not block["elements"]:
                invalid()
            for child in block["elements"]:
                if not isinstance(child, dict) or child.get("type") not in {"mrkdwn", "plain_text"}:
                    invalid()
                leaf(child)
        else:
            invalid()
    return text, tuple(copy.deepcopy(blocks))


def contextual_person(user_id, payload):
    """Bound name fields from the selected native client's SDK response."""
    result = {
        "user_id": user_id,
        "username": None,
        "display_name": None,
        "real_name": None,
    }
    user = payload.get("user") if callable(getattr(payload, "get", None)) else None
    if not (
        isinstance(user, dict) and payload.get("ok") is True and isinstance(user.get("profile", {}), dict)
    ):
        raise Uncertain("invalid contextual identity metadata")
    profile = user.get("profile", {})

    def field(value):
        if value is not None and (
            not isinstance(value, str) or len(value) > 128 or any(ord(c) < 32 for c in value)
        ):
            raise Uncertain("invalid contextual identity field")
        return value

    result.update(
        username=field(user.get("name")),
        display_name=field(profile.get("display_name")),
        real_name=field(profile["real_name"] if "real_name" in profile else user.get("real_name")),
    )
    return result


@dataclass
class Bound:
    event: Event
    recipient: Recipient
    source: object
    identity: object
    session_key: str
    native_event: dict


class Bridge:
    def __init__(self, adapter):
        self.adapter = adapter

    async def recipient_metadata(self, bound, topology):
        """Request-local, separately named Slack identity fields.

        A display-name cache may contain real-name fallbacks, so never reinterpret
        it as display_name. auth.test's bot username is the only warm fallback.
        """
        team = bound.event.thread.workspace

        async def resolve(recipient, adapter):
            handle = adapter._team_bot_names.get(team)
            username = (
                handle
                if isinstance(handle, str) and len(handle) <= 128 and not any(ord(c) < 32 for c in handle)
                else None
            )
            response = await adapter._team_clients[team].users_info(user=recipient.bot_user)
            person = contextual_person(recipient.bot_user, response)
            if "name" not in response["user"]:
                person["username"] = username
            return recipient.bot_user, person

        async with asyncio.TaskGroup() as group:
            lookups = [group.create_task(resolve(r, adapter)) for r, adapter in zip(*topology)]
        return tuple(task.result() for task in lookups)

    async def context_people(self, bound, history, whoami):
        """Exact source-window people, via serving client only; never eligibility."""
        team = bound.event.thread.workspace
        client = self.adapter._team_clients[team]
        people = dict(whoami)
        authors = {bound.event.sender, *(h.sender for h in history)}

        async def resolve(user):
            payload = await client.users_info(user=user)
            return user, contextual_person(user, payload)

        async with asyncio.TaskGroup() as group:
            tasks = [group.create_task(resolve(user)) for user in sorted(authors - set(people))]
        people.update(task.result() for task in tasks)
        return tuple(sorted(people.items()))

    async def participants(self, bound):
        """Resolve this event on each live local transport, without retaining a registry."""
        from gateway.config import Platform

        runner = self.adapter.gateway_runner
        if runner is None or getattr(runner, "_draining", False):
            raise TopologyError("native runner unavailable")
        maps = [runner._primary_adapters(), *runner._profile_adapters_map().values()]
        seen, result = set(), []
        team = bound.event.thread.workspace
        for mapping in maps:
            adapter = mapping.get(Platform.SLACK)
            if adapter is None or adapter in seen:
                continue
            seen.add(adapter)
            if team not in adapter._team_clients or team not in adapter._team_bot_user_ids:
                continue  # Select only this workspace's native transport.
            if not adapter.is_connected:
                continue
            source = adapter.build_source(
                chat_id=bound.event.thread.channel,
                chat_type="group",
                user_id=bound.event.sender,
                thread_id=adapter._session_thread_ts(bound.native_event, bound.source.message_id, False, {}),
                scope_id=team,
                message_id=bound.source.message_id,
            )
            identity = adapter._canonicalize(source)
            result.append(
                (Recipient(team, adapter._team_bot_user_ids[team], identity.runtime_profile), adapter)
            )
        result.sort(key=lambda item: (item[0].workspace, item[0].bot_user, item[0].runtime_profile))
        if len(result) > 4:
            raise TopologyError("native participant context exceeds bound")
        return tuple(item[0] for item in result), tuple(item[1] for item in result)

    def pending(self, bound):
        from tools import approval, clarify_gateway, slash_confirm

        runner = self.adapter.gateway_runner

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
        event_type = event.get("type")
        if event_type not in ("message", "app_mention", "file_shared"):
            raise Uncertain("native non-message")
        event = dict(event)
        provenance = "message"
        if event.get("subtype") == "message_changed":
            event = adapter._normalize_changed_message(event)
            if event is None:
                raise Uncertain("native edit not admitted")
            if not isinstance(event.get("edited"), dict) or not event["edited"].get("ts"):
                raise Uncertain("edit identity missing")
        team = adapter._event_team_id(event, body)
        bot = adapter._team_bot_user_ids[team]
        client = adapter._team_clients[team]
        if event.get("edited"):
            edit = event["edited"]
            if not isinstance(edit, dict) or not isinstance(edit.get("ts"), str):
                raise Uncertain("edit identity missing")
            Thread(team, event.get("channel") or event.get("channel_id") or "", edit["ts"])
            provenance = "edit"
        channel = event.get("channel") or event.get("channel_id")
        if not channel:
            raise Uncertain("missing channel")
        channel_type = event.get("channel_type")
        if channel_type is None:
            info = await client.conversations_info(channel=channel)
            obj = info.get("channel") or {}
            if info.get("ok") is not True:
                raise Uncertain("conversation lookup failed")
            channel_type = "im" if obj.get("is_im") else "mpim" if obj.get("is_mpim") else "channel"
        if channel_type not in ("channel", "group"):
            raise Uncertain("unsupported conversation")
        if event_type == "file_shared":
            file_id = event.get("file_id")
            if not file_id:
                raise Uncertain("missing file id")
            result = await client.files_info(file=file_id)
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

            event.update(user=sender, ts=shares[0]["ts"], thread_ts=shares[0].get("thread_ts"), text="")
            provenance = "file_shared"
        sender = event["user"]
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
            chat_id=channel,
            chat_type="group",
            user_id=sender,
            thread_id=adapter._session_thread_ts(event, ts, False, {}),
            scope_id=team,
            message_id=ts,
        )
        identity = adapter._canonicalize(source)

        session_key = adapter._source_session_key(source)
        recipient = Recipient(team, bot, identity.runtime_profile)
        event_id = ts + (":" + event["edited"]["ts"] if provenance == "edit" else "")
        return Bound(
            Event(thread, event_id, source.user_id, provenance=provenance),
            recipient,
            source,
            identity,
            session_key,
            copy.deepcopy(event),
        )
