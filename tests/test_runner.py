from dataclasses import replace

import pytest

from cjudge.runner import Limits, Profile, SandboxError, verdict_for


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
        assert verdict_for(metadata, code, Profile.COMPILE) == ("OK" if verdict == "OK" else "CE")
    assert verdict_for({}, -15, Profile.EXECUTE, output_exceeded=True) == "OLE"
    for metadata, code in (({}, 0), ({"status": "XX"}, 1), ({}, 2), ({"status": "unknown"}, 1)):
        with pytest.raises(SandboxError):
            verdict_for(metadata, code, Profile.EXECUTE)
    with pytest.raises(SandboxError):
        verdict_for({"status": "RE"}, 1, Profile.CHECKER)
