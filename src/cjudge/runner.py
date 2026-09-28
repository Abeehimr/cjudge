"""Worker-only isolate runner. Never import this as a public command API."""

from dataclasses import dataclass
from enum import StrEnum
import math


class SandboxError(RuntimeError):
    """Infrastructure failure; never award a student verdict or score."""


class Profile(StrEnum):
    COMPILE = "compile"
    EXECUTE = "execute"
    CHECKER = "checker"
    GENERATOR = "generator"


@dataclass(frozen=True)
class Limits:
    cpu_seconds: float = 2
    wall_seconds: float = 6
    memory_kib: int = 256 * 1024
    stack_kib: int = 8 * 1024
    stdout_bytes: int = 10 * 1024 * 1024
    stderr_bytes: int = 1024 * 1024
    storage_kib: int = 64 * 1024
    processes: int = 1

    def __post_init__(self) -> None:
        for value in (self.cpu_seconds, self.wall_seconds):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value <= 60:
                raise ValueError("Time limits must be finite and within (0, 60] seconds")
        if self.wall_seconds < self.cpu_seconds:
            raise ValueError("Wall limit must be at least the CPU limit")
        for value, ceiling in (
            (self.memory_kib, 512 * 1024), (self.stack_kib, 64 * 1024),
            (self.stdout_bytes, 10 * 1024 * 1024), (self.stderr_bytes, 1024 * 1024),
            (self.storage_kib, 128 * 1024), (self.processes, 32),
        ):
            if type(value) is not int or not 0 < value <= ceiling:
                raise ValueError("Resource limit exceeds runner bounds")


PROFILES = {
    Profile.COMPILE: Limits(cpu_seconds=10, wall_seconds=30, memory_kib=512 * 1024,
                            stdout_bytes=1024 * 1024, storage_kib=128 * 1024, processes=32),
    Profile.EXECUTE: Limits(),
    Profile.CHECKER: Limits(cpu_seconds=5, wall_seconds=15, stdout_bytes=64 * 1024),
    Profile.GENERATOR: Limits(cpu_seconds=10, wall_seconds=30),
}
SOURCE_BYTES = 64 * 1024
PREVIEW_BYTES = 64 * 1024


@dataclass(frozen=True)
class Result:
    # OK means successful execution, not acceptance. Comparison belongs to M3.
    verdict: str
    stdout: bytes
    stderr: bytes
    cpu_seconds: float
    wall_seconds: float
    memory_kib: int
    executable: bytes | None = None

    @property
    def stdout_preview(self) -> bytes:
        return self.stdout[:PREVIEW_BYTES]


def verdict_for(metadata: dict[str, str], returncode: int, profile: Profile,
                output_exceeded: bool = False) -> str:
    """Map only confirmed program failures; malformed isolate results fail closed."""
    if not output_exceeded and (returncode not in (0, 1) or metadata.get("status") == "XX"):
        raise SandboxError("isolate failed")
    if output_exceeded:
        verdict = "OLE"
    elif metadata.get("cg-oom-killed") == "1":
        verdict = "MLE"
    elif metadata.get("status") == "TO":
        verdict = "TLE"
    elif metadata.get("status") in ("RE", "SG"):
        verdict = "RE"
    elif returncode == 0 and metadata.get("exitcode") == "0" and not metadata.get("status"):
        verdict = "OK"
    else:
        raise SandboxError("Missing or unknown isolate outcome")
    if profile == Profile.COMPILE and verdict != "OK":
        return "CE"
    if profile == Profile.CHECKER and verdict != "OK":
        raise SandboxError(f"Checker failed: {verdict}")
    return verdict
