"""M1 gate: docker compose run --rm judge python tests/sandbox_checks.py -v."""

from dataclasses import replace
from pathlib import Path
import socket
import unittest
from unittest.mock import patch

from cjudge.runner import (
    BOX, CGROUP, Limits, Profile, SandboxError, compile_c, execute, run_python,
)


SOURCE = br'''
#define _DEFAULT_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <errno.h>
#include <fcntl.h>
#include <sys/socket.h>
#include <netinet/in.h>

__attribute__((noinline)) int deep(int n) {
    volatile char page[8192];
    page[0] = n;
    return deep(n + 1) + page[0];
}

int main(void) {
    if (getuid() != 60000 || getgid() != 60000) return 99;
    int mode = 0, port = 0;
    scanf("%d %d", &mode, &port);
    if (mode == 1) for (;;) {}
    if (mode == 2) sleep(10);
    if (mode == 3) abort();
    if (mode == 4) {
        volatile char *p = malloc(64 * 1024 * 1024);
        if (!p) return 42;
        for (int i = 0; i < 64 * 1024 * 1024; i += 4096) p[i] = 1;
        return p[0];
    }
    if (mode == 5 || mode == 11) {
        FILE *out = mode == 5 ? stdout : stderr;
        for (;;) fputc('x', out);
    }
    if (mode == 6) {
        pid_t pid = fork();
        if (pid == 0) _exit(0);
        return pid == -1 && errno == EAGAIN ? 0 : 1;
    }
    if (mode == 7) {
        int fd = socket(AF_INET, SOCK_STREAM, 0);
        struct sockaddr_in addr = {.sin_family=AF_INET, .sin_port=htons(port),
                                   .sin_addr.s_addr=htonl(0x7f000001)};
        int rc = connect(fd, (struct sockaddr *)&addr, sizeof(addr));
        return rc == -1 ? 0 : 1;
    }
    if (mode == 8) {
        const char *paths[] = {"/run/cjudge-secret", "/etc/shadow", "/app/src/cjudge/runner.py",
            "/box/answer", "/proc/1/root/run/cjudge-secret", "/sys/fs/cgroup/cgroup.procs",
            "/var/run/docker.sock", "/dev/sda"};
        for (unsigned i = 0; i < sizeof(paths)/sizeof(paths[0]); i++)
            if (open(paths[i], O_RDONLY) >= 0) return 1;
        if (getenv("CJUDGE_SECRET")) return 2;
        if (open("/usr/leak", O_WRONLY|O_CREAT, 0600) >= 0) return 3;
        return 0;
    }
    if (mode == 9) {
        if (access("/box/marker", F_OK) == 0 || access("/tmp/marker", F_OK) == 0) return 1;
        if (close(open("/box/marker", O_WRONLY|O_CREAT, 0600))) return 2;
        if (close(open("/tmp/marker", O_WRONLY|O_CREAT, 0600))) return 3;
        return 0;
    }
    if (mode == 10 || mode == 16) {
        char name[64], data[4096] = {0};
        for (int i = 0; i < 2048; i++) {
            snprintf(name, sizeof(name), "/tmp/f%d", i);
            int fd = open(name, O_WRONLY|O_CREAT, 0600);
            if (fd < 0) return errno == ENOSPC ? 0 : 1;
            if (mode == 10) for (int j = 0; j < 256; j++)
                if (write(fd, data, sizeof(data)) < 0) return errno == ENOSPC ? 0 : 2;
            close(fd);
        }
        return 3;
    }
    if (mode == 12 || mode == 15) {
        for (int i = 0; i < (mode == 12 ? 70000 : 65536); i++) putchar('x');
        if (mode == 12) fputs("TAIL", stdout);
        return 0;
    }
    if (mode == 14) return 42;
    if (mode == 17) return write(0, "x", 1) == -1 && errno == EBADF ? 0 : 1;
    if (mode == 18) return deep(0);
    if (mode == 19) {
        for (int i = 0; i < 128; i++)
            if (open("/dev/null", O_RDONLY) < 0) return errno == EMFILE ? 0 : 1;
        return 2;
    }
    puts("ready");
}
'''


class SandboxGate(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        result = compile_c(SOURCE)
        if result.verdict != "OK":
            raise AssertionError(result)
        cls.binary = result.executable

    def tearDown(self) -> None:
        self.assertFalse(BOX.parent.exists(), "Filesystem state survived cleanup")
        self.assertFalse(CGROUP.exists(), "Cgroup survived cleanup")

    def run_case(self, mode: int, **limits):
        return execute(self.binary, f"{mode} 0".encode(), replace(Limits(), **limits))

    def test_compile_errors_and_libm(self) -> None:
        self.assertEqual(compile_c(b"invalid source").verdict, "CE")
        result = compile_c(b'#include <math.h>\n#include <stdio.h>\nint main(void){double x; scanf("%lf",&x); printf("%.0f",sqrt(x));}')
        self.assertEqual(result.verdict, "OK")
        self.assertEqual(execute(result.executable, b"9").stdout, b"3")

    def test_cpu_and_wall_limits(self) -> None:
        self.assertEqual(self.run_case(1, cpu_seconds=0.2, wall_seconds=1).verdict, "TLE")
        self.assertEqual(self.run_case(2, cpu_seconds=0.2, wall_seconds=0.5).verdict, "TLE")

    def test_crash_exit_and_memory(self) -> None:
        self.assertEqual(self.run_case(3).verdict, "RE")
        self.assertEqual(self.run_case(14).verdict, "RE")
        self.assertEqual(self.run_case(4, memory_kib=32 * 1024).verdict, "MLE")
        self.assertEqual(self.run_case(18, stack_kib=64).verdict, "RE")

    def test_output_limits_and_full_output(self) -> None:
        self.assertEqual(self.run_case(5, stdout_bytes=65536).verdict, "OLE")
        self.assertEqual(self.run_case(11, stderr_bytes=65536).verdict, "OLE")
        result = self.run_case(15, stdout_bytes=65536)
        self.assertEqual((result.verdict, len(result.stdout)), ("OK", 65536))
        result = self.run_case(12)
        self.assertEqual(result.verdict, "OK")
        self.assertEqual(len(result.stdout_preview), 65536)
        self.assertEqual(result.stdout[70000:], b"TAIL")

    def test_blocked_fork_and_network(self) -> None:
        self.assertEqual(self.run_case(6).verdict, "OK")
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            port = listener.getsockname()[1]
            self.assertEqual(execute(self.binary, f"7 {port}".encode()).verdict, "OK")

    def test_hidden_files_and_clean_cases(self) -> None:
        secret = Path("/run/cjudge-secret")
        secret.write_text("answer and credentials")
        try:
            with patch.dict("os.environ", {"CJUDGE_SECRET": "must not inherit"}):
                self.assertEqual(self.run_case(8).verdict, "OK")
            for _ in range(2):
                self.assertEqual(self.run_case(9).verdict, "OK")
            self.assertEqual(self.run_case(17).verdict, "OK")
        finally:
            secret.unlink()

    def test_storage_and_inode_limits(self) -> None:
        for mode in (10, 16):
            self.assertEqual(self.run_case(mode, storage_kib=4096).verdict, "OK")
        self.assertEqual(self.run_case(19).verdict, "OK")

    def test_python_profiles_and_checker_failure(self) -> None:
        result = run_python(b'print(open("answer").read())', Profile.CHECKER, {"answer": b"42"})
        self.assertEqual((result.verdict, result.stdout), ("OK", b"42\n"))
        self.assertEqual(run_python(b'print("case")', Profile.GENERATOR).stdout, b"case\n")
        with self.assertRaises(SandboxError):
            run_python(b'raise RuntimeError("broken checker")', Profile.CHECKER)
        self.assertEqual(self.run_case(8).verdict, "OK")
        result = run_python(
            b'from pathlib import Path\n'
            b's = Path("/proc/self/status").read_text()\n'
            b'assert "CapEff:\\t0000000000000000" in s\n', Profile.CHECKER,
        )
        self.assertEqual(result.verdict, "OK")

    def test_cleanup_after_controller_failure(self) -> None:
        with patch("cjudge.runner._collect", side_effect=OSError("injected controller failure")):
            with self.assertRaises(SandboxError):
                self.run_case(0)
        self.assertFalse(BOX.parent.exists())
        self.assertEqual(self.run_case(0).verdict, "OK")


if __name__ == "__main__":
    unittest.main()
