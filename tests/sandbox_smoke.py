"""Run with: docker compose run --rm judge python tests/sandbox_smoke.py."""

from cjudge.runner import BOX, CGROUP, Profile, compile_c, execute, run_python


def main() -> None:
    compiled = compile_c(b'#include <stdio.h>\nint main(void) { int n; scanf("%d", &n); printf("%d\\n", n*2); }')
    assert compiled.verdict == "OK", compiled
    result = execute(compiled.executable, b"21\n")
    assert result.verdict == "OK" and result.stdout == b"42\n", result
    assert compile_c(b"invalid C source").verdict == "CE"
    for profile in (Profile.CHECKER, Profile.GENERATOR):
        result = run_python(b'print("python ready")', profile)
        assert result.verdict == "OK" and result.stdout == b"python ready\n", result
    assert not BOX.parent.exists() and not CGROUP.exists(), "Sandbox state leaked"
    print("PASS: C compilation/execution, compile errors, Python profiles, cleanup")


if __name__ == "__main__":
    main()
