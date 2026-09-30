"""One worker per box. Programs execute only through the isolate runner."""
import logging
import multiprocessing as mp
from multiprocessing.connection import wait
import os
from pathlib import Path
import signal
import threading
import time
from uuid import uuid4

import psycopg
import sqlalchemy as sa

from cjudge import authoring, identity, runner, tasks
from cjudge.judging import queue
from cjudge.submissions import files, review, batches
from cjudge.tasks.authoring import check_python
from cjudge.tasks.grading import TaskConfig, compare_output, score

LOG = logging.getLogger(__name__)


def pool_size() -> int:
    try:
        count = int(os.getenv('CJUDGE_SANDBOX_INSTANCES', '1'))
    except ValueError as exc:
        raise ValueError('CJUDGE_SANDBOX_INSTANCES must be an integer') from exc
    if not 1 <= count <= 32:
        raise ValueError('CJUDGE_SANDBOX_INSTANCES must be between 1 and 32')
    return count


def validate_capacity(count: int) -> None:
    limit = Path('/run/cjudge-cgroup/memory.max').read_text().strip()
    if limit == 'max' or int(limit) < count * 768 * 1024 * 1024:
        raise ValueError('Judge memory limit must provide at least 768 MiB per sandbox instance')


def judge(submission: dict, lost: threading.Event) -> dict:
    with identity.engine().connect() as conn:
        revision = conn.execute(sa.select(tasks.revisions).where(
            tasks.revisions.c.id == submission['revision_id'])).mappings().one()
    config = TaskConfig.model_validate(revision['config'])
    test_cases = tasks.load_cases(revision['cases_key'])
    if not test_cases or len(test_cases) != revision['case_count']:
        raise runner.SandboxError('Invalid test artifacts')
    compiled = runner.compile_c(files.read(submission))
    if lost.is_set():
        raise runner.SandboxError('Lease lost')
    case_results = []
    passed = 0
    if compiled.verdict != 'CE':
        limits = runner.Limits(cpu_seconds=config.cpu_seconds, wall_seconds=config.wall_seconds,
            memory_kib=config.memory_mib * 1024, stack_kib=config.stack_mib * 1024,
            stdout_bytes=config.stdout_mib * 1024 * 1024)
        for number, (input_bytes, answer) in enumerate(test_cases, 1):
            if lost.is_set():
                raise runner.SandboxError('Lease lost')
            execution = runner.execute(compiled.executable, input_bytes, limits)
            verdict = execution.verdict
            if verdict == 'OK':
                accepted = (check_python(config.checker.source, input_bytes, execution.stdout, answer)
                            if config.checker.kind == 'python' else compare_output(execution.stdout, answer, config.checker))
                verdict = 'AC' if accepted else 'WA'
            passed += verdict == 'AC'
            case_results.append(dict(number=number, verdict=verdict, cpu_seconds=execution.cpu_seconds,
                wall_seconds=execution.wall_seconds, memory_kib=execution.memory_kib,
                stdout=execution.stdout_preview, stderr=execution.stderr,
                stdout_truncated=execution.stdout_truncated, stderr_truncated=execution.stderr_truncated))
    marks = score(config.maximum_marks, passed, len(test_cases), config.scoring)
    diagnostic = compiled.stderr.decode('utf-8', errors='replace')
    return dict(verdict='CE' if compiled.verdict == 'CE' else 'AC' if passed == len(test_cases) else 'Failed',
        passed=passed, total=len(test_cases), score_numerator=str(marks.numerator), score_denominator=str(marks.denominator),
        compiler_feedback=diagnostic, compiler_truncated=compiled.stderr_truncated, cases=case_results)


def renew(slot: int, generation, attempt_id, stop: threading.Event, lost: threading.Event) -> None:
    while not stop.wait(10):
        try:
            with identity.engine().begin() as conn:
                if not queue.heartbeat(conn, slot, generation, attempt_id):
                    lost.set()
                    return
        except Exception:
            lost.set()
            return


def fault_message(exc: Exception) -> str:
    if isinstance(exc, runner.SandboxError):
        return 'Sandbox infrastructure failed'
    if isinstance(exc, OSError):
        return 'Artifact storage unavailable'
    if isinstance(exc, (sa.exc.SQLAlchemyError, psycopg.Error)):
        return 'Database unavailable'
    return 'Worker infrastructure failed'


def work(slot: int) -> None:
    runner.configure_box(slot)
    generation = uuid4()
    active = None
    try:
        # Recover a committed final result whose publisher crashed before switching marks.
        with identity.engine().connect() as conn:
            pending_labs = conn.execute(sa.select(batches.c.lab_id).where(batches.c.state == 'judging').distinct()).scalars().all()
        for lab_id in pending_labs:
            with identity.engine().begin() as conn:
                review.publish_ready(conn, lab_id)
        with identity.engine().begin() as conn:
            queue.register(conn, slot, generation)
        compiled = runner.compile_c(b'#include <stdio.h>\nint main(void){puts("ready");return 0;}')
        if compiled.verdict != 'OK':
            raise runner.SandboxError('Startup sandbox check failed')
        execution = runner.execute(compiled.executable)
        if execution.verdict != 'OK' or execution.stdout != b'ready\n':
            raise runner.SandboxError('Startup sandbox check failed')
        with identity.engine().begin() as conn:
            queue.worker_status(conn, slot, generation, 'Idle')
        url = sa.make_url(os.environ['DATABASE_URL']).set(drivername='postgresql').render_as_string(hide_password=False)
        with psycopg.connect(url, autocommit=True) as listener:
            listener.execute('LISTEN cjudge_jobs')
            while True:
                with identity.engine().begin() as conn:
                    active = queue.claim(conn, slot, generation)
                if active is None:
                    # LISTEN precedes claim: an upload cannot slip between claim and wait.
                    for _ in listener.notifies(timeout=30, stop_after=1):
                        break
                    continue
                stop, lost = threading.Event(), threading.Event()
                heartbeat = threading.Thread(target=renew, args=(slot, generation, active['attempt_id'], stop, lost), daemon=True)
                heartbeat.start()
                try:
                    if active.get('authoring'):
                        try:
                            case = authoring.run_case(active)
                        except authoring.AuthoringError as exc:
                            with identity.engine().begin() as conn:
                                if not authoring.fail(conn, active['attempt_id'], str(exc), author_error=True):
                                    raise runner.SandboxError('Lease lost')
                                queue.worker_status(conn, slot, generation, 'Idle')
                        else:
                            with identity.engine().begin() as conn:
                                if lost.is_set() or not authoring.checkpoint(conn, active['attempt_id'], case):
                                    raise runner.SandboxError('Lease lost')
                        active = None
                        continue
                    result = judge(active, lost)
                    if lost.is_set():
                        raise runner.SandboxError('Lease lost')
                    with identity.engine().begin() as conn:
                        if not queue.finish(conn, slot, generation, active, result):
                            raise runner.SandboxError('Lease lost')
                    with identity.engine().begin() as conn:
                        review.publish_ready(conn, active['lab_id'])
                finally:
                    stop.set()
                    heartbeat.join(timeout=5)
                active = None
    except Exception as exc:
        message = fault_message(exc)
        LOG.error('Worker slot=%s failed (%s)', slot, type(exc).__name__)
        try:
            with identity.engine().begin() as conn:
                if active:
                    if active.get('authoring'):
                        authoring.fail(conn, active['attempt_id'], message)
                    else:
                        queue.fail(conn, active['attempt_id'], message)
                queue.worker_status(conn, slot, generation, 'Faulted', message)
        except Exception:
            pass  # Lease recovery handles a simultaneous database outage.
        raise SystemExit(1) from None


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    count = pool_size()
    validate_capacity(count)
    context = mp.get_context('spawn')
    stopping = False
    def shutdown(signum, frame):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    processes, deadlines, backoff, started = {}, {}, {}, {}
    try:
        while not stopping:
            timestamp = time.monotonic()
            for slot in range(count):
                process = processes.get(slot)
                if process and not process.is_alive():
                    process.join()
                    process.close()
                    del processes[slot]
                    backoff[slot] = 5 if timestamp - started[slot] >= 90 else min(backoff.get(slot, 2.5) * 2, 60)
                    deadlines[slot] = timestamp + backoff[slot]
                if slot not in processes and timestamp >= deadlines.get(slot, 0):
                    process = context.Process(target=work, args=(slot,))
                    process.start()
                    processes[slot], started[slot] = process, timestamp
            handles = [process.sentinel for process in processes.values()]
            if handles:
                wait(handles, timeout=1)
            else:
                time.sleep(1)
    finally:
        for process in processes.values():
            if process.is_alive():
                process.terminate()
        for process in processes.values():
            process.join(timeout=5)
            if process.is_alive():
                process.kill()
                process.join()
        identity.engine().dispose()


if __name__ == '__main__':
    main()
