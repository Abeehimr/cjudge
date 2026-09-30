"""Run only in the judge container: prove independent boxes and UIDs."""
from concurrent.futures import ProcessPoolExecutor

from cjudge import runner


def check(slot: int) -> tuple[int, bytes]:
    runner.configure_box(slot)
    result = runner.compile_c(b'#include <stdio.h>\n#include <unistd.h>\nint main(void){printf("%d\\n",getuid());return 0;}')
    assert result.verdict == 'OK'
    execution = runner.execute(result.executable)
    assert execution.verdict == 'OK'
    return slot, execution.stdout


if __name__ == '__main__':
    with ProcessPoolExecutor(2) as pool:
        results = list(pool.map(check, [0, 1]))
    assert results[0][1] != results[1][1], results
    assert results == [(0, b'60000\n'), (1, b'60001\n')], results
    print('PASS: parallel sandbox compilation/execution and unique UIDs')
