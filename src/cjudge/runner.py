"""Worker-only isolate runner. Never import this as a public command API."""

from dataclasses import dataclass
from enum import StrEnum
from contextlib import contextmanager
import fcntl
import math
import os
from pathlib import Path
import re
import selectors
import stat
import subprocess
import tempfile
import time
from collections.abc import Iterator


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
    stderr_truncated: bool = False
    stdout_truncated: bool = False

    @property
    def stdout_preview(self) -> bytes:
        return self.stdout[:PREVIEW_BYTES]


def verdict_for(metadata: dict[str, str], returncode: int, profile: Profile,
                output_exceeded: bool = False) -> str:
    """Map only confirmed program failures; malformed isolate results fail closed."""
    if metadata.get("status") == "XX" or (not output_exceeded and returncode not in (0, 1)):
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
    if profile == Profile.COMPILE and verdict == "RE" and (
        metadata.get("status") == "SG" or metadata.get("exitcode") != "1"
    ):
        raise SandboxError("Compiler crashed or could not execute")
    if profile == Profile.COMPILE and verdict != "OK":
        return "CE"
    if profile == Profile.CHECKER and verdict != "OK":
        raise SandboxError(f"Checker failed: {verdict}")
    return verdict


BOX = Path("/var/local/lib/isolate/0/box")
CGROUP = Path("/run/cjudge-cgroup/box-0")
META = Path("/run/cjudge.meta")
ISOLATE = ["/usr/local/bin/isolate", "--cg", "--box-id=0"]
LOCK = Path('/run/cjudge-runner-0.lock')


def configure_box(box_id: int) -> None:
    """Assign one box per worker process, before any sandbox work starts."""
    if type(box_id) is not int or not 0 <= box_id < 32:
        raise ValueError('Box ID must be between 0 and 31')
    global BOX, CGROUP, META, ISOLATE, LOCK
    BOX = Path(f'/var/local/lib/isolate/{box_id}/box')
    CGROUP = Path(f'/run/cjudge-cgroup/box-{box_id}')
    META = Path(f'/run/cjudge-{box_id}.meta')
    LOCK = Path(f'/run/cjudge-runner-{box_id}.lock')
    ISOLATE = ['/usr/local/bin/isolate', '--cg', f'--box-id={box_id}']


def _control(command: list[str]) -> str:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=10, check=True)
        return completed.stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise SandboxError(f"Sandbox control failed: {command[0]}") from exc


def _cleanup() -> None:
    # Kill remaining descendants before removing mounts or reusing the identity.
    if CGROUP.exists():
        (CGROUP / "cgroup.kill").write_text("1")
    if os.path.ismount(BOX):
        _control(["umount", str(BOX)])
    _control([*ISOLATE, "--cleanup"])
    META.unlink(missing_ok=True)


@contextmanager
def _sandbox(limits: Limits) -> Iterator[None]:
    if os.geteuid() != 0 or not Path("/run/cjudge-cgroup/cgroup.controllers").is_file():
        raise SandboxError("Run only inside the configured judge container")
    with LOCK.open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise SandboxError("Runner is already busy") from exc
        _cleanup()
        try:
            root = _control([*ISOLATE, "--init"])
            if root != str(BOX.parent):
                raise SandboxError("Unexpected isolate box path")
            _control(["mount", "-t", "tmpfs", "-o",
                      f"size={limits.storage_kib}k,nr_inodes=1024,nosuid,nodev", "tmpfs", str(BOX)])
            (BOX / "tmp").mkdir(mode=0o777)
            (BOX / "tmp").chmod(0o777)
            # Enforce both process and swap limits in addition to isolate's rlimits.
            (CGROUP / "pids.max").write_text(str(limits.processes))
            (CGROUP / "memory.swap.max").write_text("0")
            yield
        finally:
            _cleanup()


def _collect(command: list[str], stdin: bytes, limits: Limits) -> tuple[int, bytes, bytes, set[str]]:
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    caps = {"stdout": limits.stdout_bytes, "stderr": limits.stderr_bytes}
    exceeded: set[str] = set()
    with tempfile.TemporaryFile() as input_file, selectors.DefaultSelector() as selector:
        input_file.write(stdin)
        input_file.seek(0)
        # The submitted program must not be able to rewrite the input through fd 0.
        with open(f"/proc/self/fd/{input_file.fileno()}", "rb") as readonly_input, subprocess.Popen(
            command, stdin=readonly_input, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        ) as process:
            selector.register(process.stdout, selectors.EVENT_READ, "stdout")
            selector.register(process.stderr, selectors.EVENT_READ, "stderr")
            deadline = time.monotonic() + limits.wall_seconds + 5
            try:
                while selector.get_map():
                    if time.monotonic() > deadline:
                        raise SandboxError("isolate watchdog expired")
                    for key, _ in selector.select(timeout=0.1):
                        chunk = os.read(key.fd, 65536)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        remaining = caps[key.data] - len(buffers[key.data])
                        buffers[key.data].extend(chunk[:remaining])
                        if len(chunk) > remaining:
                            if not exceeded:
                                process.terminate()
                            exceeded.add(key.data)
                code = process.wait(timeout=max(0.1, deadline - time.monotonic()))
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
    return code, bytes(buffers["stdout"]), bytes(buffers["stderr"]), exceeded


def _run(profile: Profile, command: list[str], files: dict[str, bytes],
         stdin: bytes = b"", limits: Limits | None = None) -> Result:
    limits = limits or PROFILES[profile]
    if profile != Profile.COMPILE and limits.processes != 1:
        raise ValueError("Only compilation may spawn processes")
    if not isinstance(stdin, bytes) or len(stdin) > 10 * 1024 * 1024:
        raise ValueError("stdin must be bytes, at most 10 MiB")
    for name, content in files.items():
        if not re.fullmatch(r"[a-zA-Z0-9_][a-zA-Z0-9_.-]{0,63}", name) or name == "tmp":
            raise ValueError("Sandbox inputs require plain filenames")
        if not isinstance(content, bytes):
            raise ValueError("Sandbox inputs must be bytes")
    if sum(map(len, files.values())) > 16 * 1024 * 1024:
        raise ValueError("Sandbox inputs exceed 16 MiB")
    try:
        with _sandbox(limits):
            for name, content in files.items():
                (BOX / name).write_bytes(content)
                (BOX / name).chmod(0o755 if name == "main" else 0o644)
            args = [*ISOLATE, "--silent", f"--meta={META}",
                    f"--time={limits.cpu_seconds}", f"--wall-time={limits.wall_seconds}",
                    f"--cg-mem={limits.memory_kib}", f"--stack={limits.stack_kib}",
                    f"--processes={limits.processes}", "--open-files=64", "--core=0",
                    f"--fsize={limits.storage_kib}", "--no-default-dirs",
                    f"--dir=box={BOX}:rw", f"--dir=tmp={BOX / 'tmp'}:rw",
                    "--dir=usr", "--dir=bin", "--dir=lib", "--dir=lib64:maybe",
                    "--dir=dev=/run/cjudge-dev:dev:norec", "--dir=proc=proc:fs",
                    "--env=PATH=/usr/local/bin:/usr/bin:/bin", "--env=HOME=/box",
                    "--env=TMPDIR=/tmp", "--env=LC_ALL=C", "--run", "--", *command]
            code, stdout, stderr, exceeded = _collect(args, stdin, limits)
            metadata = dict(line.split(":", 1) for line in META.read_text().splitlines())
            verdict = verdict_for(metadata, code, profile, bool(exceeded))
            executable = None
            if profile == Profile.COMPILE and verdict == "OK":
                # Never follow a sandbox-created symlink or read a special file as root.
                fd = os.open(BOX / "main", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                with os.fdopen(fd, "rb") as binary:
                    info = os.fstat(binary.fileno())
                    if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= 10 * 1024 * 1024:
                        raise SandboxError("Compiler produced an invalid artifact")
                    executable = binary.read(10 * 1024 * 1024)
            return Result(verdict, stdout, stderr[:PREVIEW_BYTES],
                          float(metadata["time"]), float(metadata["time-wall"]),
                          int(metadata["cg-mem"]), executable,
                          len(stderr) > PREVIEW_BYTES or 'stderr' in exceeded,
                          'stdout' in exceeded or len(stdout) > PREVIEW_BYTES)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        raise SandboxError("Sandbox execution or cleanup failed") from exc


def compile_c(source: bytes) -> Result:
    if not isinstance(source, bytes) or not 0 < len(source) <= SOURCE_BYTES:
        raise ValueError("C source must contain 1–65536 bytes")
    return _run(Profile.COMPILE, ["/usr/bin/gcc", "-O2", "-std=c11", "-fdiagnostics-color=never",
                                 "/box/main.c", "-o", "/box/main", "-lm"], {"main.c": source})


def execute(executable: bytes, stdin: bytes = b"", limits: Limits | None = None) -> Result:
    if not isinstance(executable, bytes) or not 0 < len(executable) <= 10 * 1024 * 1024:
        raise ValueError("Executable must contain 1 byte to 10 MiB")
    return _run(Profile.EXECUTE, ["/box/main"], {"main": executable}, stdin, limits)


def run_python(script: bytes, profile: Profile, files: dict[str, bytes] | None = None,
               args: tuple[str, ...] = (), limits: Limits | None = None) -> Result:
    """Bounded Python primitive for worker-only checker/generator protocols."""
    if profile not in (Profile.CHECKER, Profile.GENERATOR):
        raise ValueError("Python requires checker or generator profile")
    if not isinstance(script, bytes) or not 0 < len(script) <= SOURCE_BYTES:
        raise ValueError("Python source must contain 1–65536 bytes")
    if files and "program.py" in files:
        raise ValueError("program.py is reserved")
    return _run(profile, ["/usr/local/bin/python3", "-I", "-B", "/box/program.py", *args],
                {**(files or {}), "program.py": script}, limits=limits)
