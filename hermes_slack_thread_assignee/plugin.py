"""Official native factory/global middleware; no listener or transport replacement."""

import asyncio
import logging
import os
from pathlib import Path

from .bridge import Bridge, Uncertain
from .config import Config

logger = logging.getLogger(__name__)


class Gate:
    def __init__(self, store, *, monitoring=()):
        self.store = store
        self.monitoring = frozenset(tuple(item) for item in monitoring)
        self.disposed = False

    def dispose(self):
        self.disposed = True

    def wire(self, native, adapter):
        from slack_bolt.response import BoltResponse

        bridge = Bridge(adapter)

        async def middleware(body, next):
            if self.disposed:
                return await next()
            try:
                bound = await bridge.bind(body)
                key = bound.event.thread
                exempt = (key.workspace, key.channel, bound.event.sender) in self.monitoring
                if not exempt and not bridge.pending(bound):
                    decision = await asyncio.to_thread(self.store.decide, bound.event, bound.recipient)
                    if decision.action == "drop" and not self.disposed and not bridge.pending(bound):
                        logger.info("thread-assignee: %s", decision.reason)
                        return BoltResponse(status=200, body="")
                    if decision.action == "pass":
                        logger.info("thread-assignee degraded: %s", decision.reason)
            except Uncertain as exc:
                logger.debug("thread-assignee native pass-through: %s", exc)
            except Exception:
                logger.warning("thread-assignee classification failed; native pass-through", exc_info=True)
            return await next()

        native.use(middleware)


def register(ctx):
    path = os.environ.get("HERMES_THREAD_ASSIGNEE_CONFIG")
    if not path:
        raise ValueError("HERMES_THREAD_ASSIGNEE_CONFIG is required")
    config = Config.load(Path(path))
    gate = Gate(config.store(), monitoring=config.monitoring)
    ctx.register_platform_handler("slack", gate.wire)
    ctx.on_unload(gate.dispose)
