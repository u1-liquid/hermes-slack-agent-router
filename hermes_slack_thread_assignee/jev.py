"""Native Jev Choice protocol. No shell, generated instructions or embedded auth."""

import asyncio
import json
import math
import time
from pathlib import Path


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
                relevant = field == "kind" or selected.get(unit + "_kind") not in ("ack", "reference")
            elif name.startswith("same"):
                left, right = name[4:].split("_")
                relevant = all(selected.get(f"u{i}_kind") == "action" for i in (left, right))
            if relevant and answer["confidence"] < confidence:
                raise JevError("uncertain relevant answer: " + name)
        return selected
    except (KeyError, TypeError, AttributeError) as exc:
        raise JevError("malformed native Jev answer") from exc


class JevClient:
    @staticmethod
    async def _read_bounded(stream, limit):
        chunks, size = [], 0
        while chunk := await stream.read(min(4096, limit + 1 - size)):
            size += len(chunk)
            if size > limit:
                raise JevError("oversized native output")
            chunks.append(chunk)
        return b"".join(chunks)

    async def _exchange(self, process, raw):
        async def send():
            try:
                process.stdin.write(raw)
                await process.stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                process.stdin.close()

        tasks = [
            asyncio.create_task(self._read_bounded(process.stdout, 262144)),
            asyncio.create_task(self._read_bounded(process.stderr, 16384)),
            asyncio.create_task(send()),
        ]
        try:
            stdout, stderr, _ = await asyncio.gather(*tasks)
            await process.wait()
            return stdout, stderr
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    def __init__(self, executable="jev", timeout=1.2, receipt_directory: Path | None = None):
        if not 0 < timeout <= 1.2:
            raise ValueError("Jev sub-budget must be in (0, 1.2] seconds")
        self.executable = executable
        self.timeout = timeout
        self.receipt_directory = receipt_directory

    async def ask(self, batch):
        raw = json.dumps(batch, ensure_ascii=False, allow_nan=False).encode()
        if len(raw) > 262144:
            raise JevError("oversized serialized request")
        process = None
        started = time.monotonic()
        receipt = {"protocol": "jev ask Choice", "exit": None, "elapsed_ms": None}
        stdout, stderr = b"", b""
        try:
            async with asyncio.timeout(self.timeout):
                process = await asyncio.create_subprocess_exec(
                    self.executable,
                    "ask",
                    "--timeout",
                    str(self.timeout),
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await self._exchange(process, raw)
            receipt["exit"] = process.returncode
            if process.returncode != 0:
                raise JevError("native Jev failed")
            if len(stdout) > 262144:
                raise JevError("oversized native answer")
            try:
                result = json.loads(stdout)
            except (ValueError, UnicodeError) as exc:
                raise JevError("invalid native JSON") from exc
            return validate_answers(batch, result)
        except (TimeoutError, OSError) as exc:
            raise JevError("native Jev timeout or launch failure") from exc
        finally:
            if process is not None and process.returncode is None:
                process.kill()

                # Reap on timeout AND task cancellation; never detach inference.
                async def reap():
                    async def discard(stream):
                        while await stream.read(4096):
                            pass

                    await asyncio.gather(discard(process.stdout), discard(process.stderr), process.wait())

                await asyncio.shield(reap())
                receipt["exit"] = process.returncode
            receipt["elapsed_ms"] = round((time.monotonic() - started) * 1000, 3)
            if self.receipt_directory is not None:
                root = Path(self.receipt_directory)
                root.mkdir(parents=True, exist_ok=True, mode=0o700)
                (root / "jev-request.json").write_bytes(raw)
                (root / "jev-result.json").write_bytes(stdout)
                (root / "jev-stderr.txt").write_bytes(stderr)
                (root / "jev-receipt.json").write_text(json.dumps(receipt, indent=2))
