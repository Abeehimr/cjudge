from dataclasses import replace
from unittest.mock import patch

import pytest

from cjudge.runner import Limits, Profile, SandboxError, compile_c, execute, run_python, verdict_for


def test_limits_and_verdict_contract() -> None:
    for changes in ({"cpu_seconds": float("nan")}, {"wall_seconds": 1},
                    {"processes": 0}, {"memory_kib": -1}, {"stdout_bytes": True}):
        with pytest.raises(ValueError):
            replace(Limits(), **changes)
    for metadata, code, verdict in (
        ({"exitcode": "0"}, 0, "OK"), ({"status": "RE", "exitcode": "1"}, 1, "RE"),
        ({"status": "SG", "exitsig": "11"}, 1, "RE"),
        ({"status": "TO"}, 1, "TLE"),
        ({"status": "SG", "cg-oom-killed": "1"}, 1, "MLE"),
    ):
        assert verdict_for(metadata, code, Profile.EXECUTE) == verdict
        if metadata.get("status") == "SG" and verdict == "RE":
            with pytest.raises(SandboxError):
                verdict_for(metadata, code, Profile.COMPILE)
        else:
            assert verdict_for(metadata, code, Profile.COMPILE) == ("OK" if verdict == "OK" else "CE")
    assert verdict_for({}, -15, Profile.EXECUTE, output_exceeded=True) == "OLE"
    with pytest.raises(SandboxError):
        verdict_for({"status": "XX"}, 1, Profile.EXECUTE, output_exceeded=True)
    for metadata, code in (({}, 0), ({"status": "XX"}, 1), ({}, 2), ({"status": "unknown"}, 1)):
        with pytest.raises(SandboxError):
            verdict_for(metadata, code, Profile.EXECUTE)
    with pytest.raises(SandboxError):
        verdict_for({"status": "RE"}, 1, Profile.CHECKER)
    with pytest.raises(SandboxError):
        verdict_for({"status": "RE", "exitcode": "127"}, 1, Profile.COMPILE)


def test_reject_invalid_requests_before_sandbox() -> None:
    for source in (b"", b"x" * 65537, "not bytes"):
        with pytest.raises(ValueError):
            compile_c(source)
    with pytest.raises(ValueError):
        execute(b"binary", limits=Limits(processes=2))
    with pytest.raises(ValueError):
        run_python(b"pass", Profile.EXECUTE)
    for files in ({"../answer": b"secret"}, {"program.py": b"override"}, {"tmp": b"reserved"}):
        with pytest.raises(ValueError):
            run_python(b"pass", Profile.CHECKER, files)
    with patch("cjudge.runner.os.geteuid", return_value=1000):
        with pytest.raises(SandboxError, match="configured judge container"):
            execute(b"binary")
