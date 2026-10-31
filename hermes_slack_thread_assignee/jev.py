"""Official TypeSafe System One Choice protocol; Hermes-scoped credentials."""

import asyncio
import json
import math


class JevError(ValueError):
    pass


def validate_answers(batch, result, confidence=0.8):
    try:
        answers = result["answers"]
        if not isinstance(answers, dict) or set(answers) != set(batch["questions"]):
            raise JevError("answer keys do not match request")
        selected = {}
        for name, question in batch["questions"].items():
            answer = answers[name]
            criteria = question["criteria"]
            distribution = answer["probabilities"]
            if (
                answer["type"] != "choice"
                or answer["choice"] not in criteria
                or not isinstance(distribution, dict)
                or set(distribution) != set(criteria)
            ):
                raise JevError("invalid Choice answer")
            numbers = [answer["confidence"], *distribution.values()]
            if any(type(n) not in (float, int) or not math.isfinite(n) or not 0 <= n <= 1 for n in numbers):
                raise JevError("nonfinite or out-of-range probability")
            if abs(sum(distribution.values()) - 1) > 0.025:
                raise JevError("invalid probability distribution")
            choice = answer["choice"]
            if distribution[choice] < max(distribution.values()):
                raise JevError("uncertain or contradictory answer")
            selected[name] = choice
        for name, answer in answers.items():
            relevant = True
            if name.startswith("u") and "_" in name:
                unit, field = name.split("_", 1)
                relevant = field in ("kind", "mixed", "destination") or selected.get(unit + "_kind") not in (
                    "ack",
                    "reference",
                )
                if selected.get(unit + "_destination") == "generic" and field.startswith(("ref", "to")):
                    relevant = False  # Generic routing uses main/main_ref instead of these answers.
            elif name.startswith("same"):
                left, right = name[4:].split("_")
                relevant = all(selected.get(f"u{i}_kind") == "action" for i in (left, right))
            elif name == "main" or name.startswith("main_ref"):
                relevant = any(
                    key.endswith("_destination")
                    and value == "generic"
                    and selected.get(key.replace("_destination", "_kind")) == "action"
                    for key, value in selected.items()
                )
            if relevant and answer["confidence"] < confidence:
                raise JevError("uncertain relevant answer: " + name)
        return selected
    except (KeyError, TypeError, AttributeError) as exc:
        raise JevError("malformed native Jev answer") from exc


class JevClient:
    """One request-owned HTTPS connection; no cached credentials or background work."""

    endpoint = "https://api.typesafe.ai/v1/systemone"
    model = "jev-latest"
    limit = 262144

    def __init__(self, timeout=1.2):
        if not math.isfinite(timeout) or not 0 < timeout <= 1.2:
            raise ValueError("Jev sub-budget must be in (0, 1.2] seconds")
        self.timeout = timeout

    async def _exchange(self, raw, key):
        import httpx

        async with (
            httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=False,
                trust_env=False,
            ) as client,
            client.stream(
                "POST",
                self.endpoint,
                content=raw,
                headers={
                    "Authorization": "Bearer " + key,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "Accept-Encoding": "identity",
                },
            ) as response,
        ):
            # Never follow redirects, retry errors, or expose service error bodies.
            if response.status_code != 200:
                raise JevError("Jev HTTP request failed")
            if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                raise JevError("unsupported Jev response encoding")
            length = response.headers.get("Content-Length")
            if length is not None and (not length.isdecimal() or int(length) > self.limit):
                raise JevError("oversized or invalid Jev response length")
            chunks, size = [], 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > self.limit:
                    raise JevError("oversized Jev response")
                chunks.append(chunk)
            return b"".join(chunks)

    async def ask(self, batch):
        try:
            raw = json.dumps({"model": self.model, **batch}, ensure_ascii=False, allow_nan=False).encode()
        except (ValueError, TypeError, UnicodeError):
            raise JevError("invalid serialized request") from None
        if len(raw) > self.limit:
            raise JevError("oversized serialized request")
        # Import and resolve inside the calling request's native Hermes scope, not
        # at registration/construction or through CLI-specific auth/environment files.
        try:
            from agent.secret_scope import get_secret

            key = get_secret("TYPESAFE_API_KEY")
        except (ImportError, RuntimeError, OSError):
            raise JevError("Hermes Jev credential scope unavailable") from None
        if not isinstance(key, str) or not key:
            raise JevError("Hermes Jev credential unavailable")
        import httpx

        try:
            # The total sub-budget includes connect/send/stream and resource cleanup;
            # the caller's whole-ingress deadline may cancel it earlier.
            async with asyncio.timeout(self.timeout):
                stdout = await self._exchange(raw, key)
            try:
                result = json.loads(stdout)
            except (ValueError, UnicodeError):
                raise JevError("invalid Jev JSON") from None
            return validate_answers(batch, result)
        except (TimeoutError, httpx.HTTPError, OSError, ValueError) as exc:
            if isinstance(exc, JevError):
                raise
            raise JevError("Jev HTTPS transport failed") from None
