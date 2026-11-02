"""Official TypeSafe System One Choice protocol; Hermes-scoped credentials."""

import json
import math


class JevError(ValueError):
    def __init__(self, message, *, status=0, size=0, dropped=0):
        super().__init__(message)
        self.status = status if type(status) is int and 100 <= status <= 599 else 0
        self.size = size if type(size) is int and size >= 0 else 0
        self.dropped = dropped if type(dropped) is int and dropped >= 0 else 0

    @property
    def diagnostic(self):
        # Only source-owned categories leave this boundary, never exception text.
        message = str(self)
        code = {
            "invalid serialized request": "request-invalid",
            "oversized serialized request": "request-oversized",
            "unsupported request size": "unsupported-request-size",
            "Hermes Jev credential scope unavailable": "scope-unavailable",
            "Hermes Jev credential unavailable": "credential-unavailable",
            "Jev HTTP request failed": "http-rejected",
            "Jev HTTPS transport failed": "transport-failed",
            "Jev HTTPS transport timed out": "transport-timeout",
            "unsupported Jev response encoding": "response-encoding",
            "oversized or invalid Jev response length": "response-length",
            "oversized Jev response": "response-oversized",
            "invalid Jev JSON": "answer-json",
            "answer keys do not match request": "answer-coverage",
            "invalid Choice answer": "answer-choice",
            "nonfinite or out-of-range probability": "answer-probability",
            "invalid probability distribution": "answer-distribution",
            "uncertain or contradictory answer": "answer-contradiction",
            "malformed native Jev answer": "answer-malformed",
        }.get(message, "unclassified")
        if message.startswith("uncertain relevant answer: "):
            code = "answer-confidence"
        return code, self.status if code == "http-rejected" else 0


def validate_answers(batch, result):
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
        # Exhaustive native-generated families: only exact optional priors may omit.
        state = batch["state"]
        authored = [
            unit for unit, span in state["source_selection"]["segments"].items() if not span["quoted"]
        ]
        required = {"response", "scope"} if authored else set()
        priors = {
            f"{unit}_prior{j}" for unit in authored for j in range(len(state["conversation"]["records"]) - 1)
        }
        if set(answers) != required | priors:
            raise JevError("answer keys do not match request")
        admitted = (
            bool(authored) and selected["response"] == "yes" and answers["response"]["confidence"] > 0.5
        )
        if authored:
            selected["response"] = "yes" if admitted else "no"
        extent = set(selected["scope"].split("+")) if admitted and selected["scope"] != "unsafe" else set()
        for name in priors:
            unit = name.split("_prior", 1)[0]
            if unit not in extent or answers[name]["confidence"] < 0.8 or selected[name] != "include":
                selected[name] = "omit"
        return selected
    except (KeyError, TypeError, AttributeError) as exc:
        raise JevError("malformed native Jev answer") from exc


def serialize_request(batch):
    """Exact production encoding, also used by bound/qualification tests."""
    try:
        raw = json.dumps(
            {"model": JevClient.model, **batch}, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode()
    except (ValueError, TypeError, UnicodeError):
        raise JevError("invalid serialized request") from None
    if len(raw) > JevClient.request_limit:
        raise JevError("oversized serialized request", size=len(raw))
    return raw


class JevClient:
    """One request-owned HTTPS connection; no cached credentials or background work."""

    endpoint = "https://api.typesafe.ai/v1/systemone"
    model = "jev-latest"
    limit = 262144
    request_limit = 524288

    async def _exchange(self, raw, key):
        import httpx

        async with (
            httpx.AsyncClient(
                timeout=None,
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
                raise JevError("Jev HTTP request failed", status=response.status_code)
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
        raw = serialize_request(batch)
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
            stdout = await self._exchange(raw, key)
            try:
                result = json.loads(stdout)
            except (ValueError, UnicodeError):
                raise JevError("invalid Jev JSON") from None
            return validate_answers(batch, result)
        except (TimeoutError, httpx.TimeoutException):
            raise JevError("Jev HTTPS transport timed out") from None
        except (httpx.HTTPError, OSError, ValueError) as exc:
            if isinstance(exc, JevError):
                raise
            raise JevError("Jev HTTPS transport failed") from None
