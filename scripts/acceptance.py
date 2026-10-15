#!/usr/bin/env python3
"""M9 HTTPS acceptance on disposable volumes; restore the normal deployment on exit."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import http.client
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
from urllib.parse import urlencode
from uuid import uuid4
import ssl
import argparse
import signal
import re
import socket
import ipaddress
import threading
from collections.abc import Callable

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
BASE = 'https://localhost:8443'
CONTEXT = ssl.create_default_context(cafile='certs/server.crt')
WEB_ADDRESS = 'localhost'


class Connection(http.client.HTTPSConnection):
    """Reach the internal bridge while verifying the existing localhost certificate."""
    def __init__(self, timeout: float = 20) -> None:
        super().__init__('localhost', 8443, context=CONTEXT, timeout=timeout)

    def connect(self) -> None:
        self.sock = socket.create_connection((WEB_ADDRESS, 8443), self.timeout)
        self.sock = CONTEXT.wrap_socket(self.sock, server_hostname='localhost')


def command(args: list[str], *, capture: bool = False, env: dict[str, str] | None = None) -> str | None:
    return subprocess.run(args, check=True, text=True, env=env,
        stdout=subprocess.PIPE if capture else sys.stderr).stdout


class Client:
    def __init__(self, cookie: str = '', csrf: str = '') -> None:
        self.cookie, self.csrf = cookie, csrf
        self.connection = Connection()

    def call(self, path: str, method: str = 'GET', body: bytes | None = None, headers: dict | None = None) -> tuple[dict | list, float]:
        fields = {'Cookie': self.cookie, 'Origin': BASE, 'X-CSRF-Token': self.csrf, **(headers or {})}
        start = time.monotonic()
        for attempt in range(2):
            try:
                self.connection.request(method, '/api' + path, body=body, headers=fields)
                response = self.connection.getresponse()
                content = response.read()
                break
            except (http.client.RemoteDisconnected, BrokenPipeError, ConnectionResetError):
                self.close()
                if attempt or not (method == 'GET' or fields.get('Idempotency-Key')):
                    raise
                self.connection = Connection()
        elapsed = (time.monotonic() - start) * 1000
        if response.status not in (200, 201):
            detail = json.loads(content).get('detail') if response.getheader('Content-Type', '').startswith('application/json') else None
            code = detail.get('code') if isinstance(detail, dict) else None
            raise RuntimeError(f'{method} {path.split("?")[0]} returned {response.status}; code={code}')
        return json.loads(content), elapsed

    def close(self) -> None:
        self.connection.close()


def percentile(values: list[float], quantile: float = .95) -> float:
    return sorted(values)[math.ceil(len(values) * quantile) - 1]


def metrics(values: list[float]) -> dict:
    return dict(requests=len(values), p50_ms=round(percentile(values, .5), 3),
        p95_ms=round(percentile(values), 3), p99_ms=round(percentile(values, .99), 3))


def memory_bytes(value: str) -> int:
    number, unit = re.fullmatch(r'([0-9.]+)([KMG]?i?B)', value).groups()
    return round(float(number) * {'B': 1, 'kB': 1000, 'MB': 1000**2, 'GB': 1000**3,
        'KiB': 1024, 'MiB': 1024**2, 'GiB': 1024**3}[unit])


def sample_resources(project: str, stop: threading.Event, peaks: dict) -> None:
    while not stop.is_set():
        try:
            result = subprocess.run(['docker', 'stats', '--no-stream', '--format', '{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}'],
                capture_output=True, text=True, timeout=15)
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    name, cpu, usage = line.split('|')
                    if name.startswith(project + '-'):
                        service = name[len(project) + 1:].rsplit('-', 1)[0]
                        item = peaks.setdefault(service, dict(cpu_percent=0.0, memory_bytes=0))
                        item['cpu_percent'] = max(item['cpu_percent'], float(cpu.strip('%')))
                        item['memory_bytes'] = max(item['memory_bytes'], memory_bytes(usage.split(' / ')[0]))
        except (OSError, ValueError, AttributeError, subprocess.TimeoutExpired):
            peaks['sampling_error'] = True
        stop.wait(5)


def wait(predicate: Callable[[], bool], seconds: float = 60) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.5)
    raise TimeoutError('Acceptance condition timed out')


def benchmark(state: dict, report: dict, restart: Callable[[], None]) -> None:
    lab = state['lab_id']
    clients = [Client(cookie, state['csrf']) for cookie in state['students']]
    admin = Client(state['admin_cookie'], state['csrf'])
    programs = state['programs']
    try:
        def healthy() -> bool:
            try:
                return admin.call('/admin/isolates')[0]['healthy'] == report['workers']
            except (OSError, RuntimeError, http.client.HTTPException) as error:
                report['last_readiness_error'] = str(error)
                admin.close()
                admin.connection = Connection()
                return False
        wait(healthy)
        report.pop('last_readiness_error', None)

        def submit(index: int, source: str | None = None, samples: list[float] | None = None) -> dict:
            program = programs[index % 5]
            query = urlencode({'revision_id': program['revision_id'], 'filename': 'main.c'})
            row, elapsed = clients[index].call(f'/labs/{lab}/submissions?{query}', 'POST',
                (source or program['source']).encode(), {'Content-Type': 'application/octet-stream', 'Idempotency-Key': str(uuid4())})
            if samples is not None:
                samples.append(elapsed)
            return row

        def completed(rows: list[dict], indices: range | list[int], expected: str = 'Passed', seconds: float = 300,
                      samples: list[float] | None = None) -> None:
            pending = dict(zip(indices, rows))
            deadline = time.monotonic() + seconds
            while pending:
                for index, row in list(pending.items()):
                    value, elapsed = clients[index].call(f'/labs/{lab}/submissions/{row["id"]}')
                    if samples is not None:
                        samples.append(elapsed)
                    status = value['status']
                    if status == expected:
                        del pending[index]
                    elif status in ('Judging delayed', 'Compile error', 'Passed', 'Failed'):
                        detail = admin.call(f'/admin/labs/{lab}/submissions/{row["id"]}')[0]
                        report['unexpected_judging'] = dict(status=status, expected=expected,
                            task=programs[index % 5]['title'],
                            verdicts=[case['verdict'] for case in detail['cases']])
                        raise RuntimeError(f'Unexpected judge status: {status}; expected {expected}')
                if pending and time.monotonic() >= deadline:
                    raise TimeoutError(f'{len(pending)} submissions remain unresolved')
                if pending:
                    time.sleep(.5)

        light = []
        for index in range(150, 155):
            start = time.monotonic()
            row = submit(index)
            completed([row], [index], seconds=30)
            light.append(dict(task=programs[index % 5]['title'], seconds=round(time.monotonic() - start, 3)))
        report['light_load'] = light
        # Populate realistic histories before measuring reads; this is not the paced burst.
        with ThreadPoolExecutor(30) as executor:
            warm_rows = list(executor.map(submit, range(150)))
        completed(warm_rows, range(150))
        print('Light-load and warm-up judging complete', file=sys.stderr)

        def reader(index: int) -> dict[str, list[float]]:
            paths = [f'/labs/{lab}', f'/labs/{lab}/submissions?revision_id={programs[index % 5]["revision_id"]}',
                f'/labs/{lab}/submissions', f'/labs/{lab}/submissions/{warm_rows[index]["id"]}']
            samples = {name: [] for name in ('lab', 'task_history', 'history', 'status')}
            names = list(samples)
            # Five staggered warm-up requests, then 120 seconds at one request/user/second.
            start = time.monotonic() + index / 150
            for number in range(125):
                time.sleep(max(0, start + number - time.monotonic()))
                _, elapsed = clients[index].call(paths[number % 4])
                if number >= 5:
                    samples[names[number % 4]].append(elapsed)
            return samples
        with ThreadPoolExecutor(150) as executor:
            samples = list(executor.map(reader, range(150)))
        merged = {name: [value for sample in samples for value in sample[name]] for name in samples[0]}
        report['api'] = {name: metrics(values) for name, values in merged.items()}
        all_values = [value for values in merged.values() for value in values]
        report['api']['overall'] = metrics(all_values)
        print(f'API measurements complete: overall p95={report["api"]["overall"]["p95_ms"]} ms', file=sys.stderr)

        start = time.monotonic()
        wall_start = time.time()
        acceptance_latency = []
        def paced(index: int) -> dict:
            time.sleep(max(0, start + index * 60 / 149 - time.monotonic()))
            return submit(index, samples=acceptance_latency)
        with ThreadPoolExecutor(150) as executor:
            rows = list(executor.map(paced, range(150)))
        completed(rows, range(150))
        first = min(datetime.fromisoformat(row['accepted_at']).timestamp() for row in rows)
        last = max(datetime.fromisoformat(row['accepted_at']).timestamp() for row in rows)
        report['burst'] = dict(submissions=150, arrival_seconds=round(last - first, 3),
            completion_seconds=round(time.monotonic() - start - (first - wall_start), 3), passed=150,
            acceptance=metrics(acceptance_latency))

        start = time.monotonic()
        with ThreadPoolExecutor(15) as executor:
            timed = list(executor.map(lambda index: submit(index, 'int main(void){for(;;){}}'), range(155, 170)))
        timeout_latency, queue_delays = [], []
        completed(timed, range(155, 170), expected='Failed', seconds=180, samples=timeout_latency)
        for row in timed:
            detail = admin.call(f'/admin/labs/{lab}/submissions/{row["id"]}')[0]
            assert len(detail['cases']) == 10 and all(case['verdict'] == 'TLE' for case in detail['cases'])
            queue_delays.append(min(datetime.fromisoformat(item['started_at']).timestamp() for item in detail['attempts'])
                - datetime.fromisoformat(detail['accepted_at']).timestamp())
        report['timeouts'] = dict(submissions=15, cases_per_submission=10, expected_verdict='TLE',
            completion_seconds=round(time.monotonic() - start, 3), api_p95_ms=round(percentile(timeout_latency), 3),
            queue_delay_p95_seconds=round(percentile(queue_delays), 3))
        # Read and reconnect an SSE stream through nginx, then verify persistent evidence after restart.
        def reconnect_events() -> None:
            connection = Connection(timeout=5)
            response = None
            try:
                connection.request('GET', f'/api/labs/{lab}/events', headers={'Cookie': state['students'][0]})
                response = connection.getresponse()
                assert response.status == 200 and response.readline() == b'event: refresh\n'
            finally:
                if response is not None:
                    response.close()
                connection.close()
        for _ in range(2):
            reconnect_events()
        restart()
        admin.close()
        wait(healthy)
        report.pop('last_readiness_error', None)
        for client in clients:
            client.close()
            client.connection = Connection()
        completed(rows, range(150), seconds=30)
        reconnect_events()
        report['restart_persistence'] = True
        report['sse_reconnect'] = True
        report['passed'] = all(item['p95_ms'] < 300 for item in report['api'].values()) and report['burst']['completion_seconds'] <= 300 and all(item['seconds'] <= 30 for item in light)
    finally:
        admin.close()
        for client in clients:
            client.close()


def mixed_benchmark(state: dict, report: dict) -> None:
    labs = state['student_labs']
    assert len(state['lab_ids']) == 3 and [labs[:150].count(lab) for lab in state['lab_ids']] == [50, 50, 50]
    readers = [Client(cookie, state['csrf']) for cookie in state['students'][:150]]
    uploaders = [Client(cookie, state['csrf']) for cookie in state['students'][:150]]
    admin = Client(state['admin_cookie'], state['csrf'])
    streams: list[tuple[Connection, http.client.HTTPResponse]] = []
    programs = state['programs']

    def submit(index: int) -> tuple[dict, float]:
        program = programs[index % 5]
        query = urlencode({'revision_id': program['revision_id'], 'filename': 'main.c'})
        return uploaders[index].call(f'/labs/{labs[index]}/submissions?{query}', 'POST',
            program['source'].encode(), {'Content-Type': 'application/octet-stream', 'Idempotency-Key': str(uuid4())})

    def completed(rows: list[dict], seconds: float = 300) -> None:
        pending = dict(enumerate(rows))
        deadline = time.monotonic() + seconds
        while pending:
            for index, row in list(pending.items()):
                value, _ = readers[index].call(f'/labs/{labs[index]}/submissions/{row["id"]}')
                if value['status'] == 'Passed':
                    del pending[index]
                elif value['status'] in ('Judging delayed', 'Compile error', 'Partial pass', 'Failed'):
                    raise RuntimeError(f'Unexpected mixed judging status: {value["status"]}')
            if pending and time.monotonic() >= deadline:
                raise TimeoutError(f'{len(pending)} mixed submissions remain unresolved')
            if pending:
                time.sleep(.5)

    def open_stream(index: int) -> tuple[Connection, http.client.HTTPResponse]:
        connection = Connection(timeout=20)
        connection.request('GET', f'/api/labs/{labs[index]}/events', headers={'Cookie': state['students'][index]})
        response = connection.getresponse()
        if response.status != 200 or response.readline() != b'event: refresh\n':
            response.close()
            connection.close()
            raise RuntimeError('Mixed SSE connection failed')
        return connection, response

    try:
        wait(lambda: admin.call('/admin/isolates')[0]['healthy'] == report['workers'])
        with ThreadPoolExecutor(30) as executor:
            warm = [row for row, _ in executor.map(submit, range(150))]
        completed(warm)
        with ThreadPoolExecutor(30) as executor:
            streams = list(executor.map(open_stream, range(150)))
        report['sse_connections'] = len(streams)
        print('Mixed warm-up and 150 SSE connections complete', file=sys.stderr)

        start = time.monotonic() + 2
        errors: list[str] = []
        def reader(index: int) -> dict[str, list[float]]:
            lab = labs[index]
            paths = [f'/labs/{lab}', f'/labs/{lab}/submissions?revision_id={programs[index % 5]["revision_id"]}',
                f'/labs/{lab}/submissions', f'/labs/{lab}/submissions/{warm[index]["id"]}']
            samples = {name: [] for name in ('lab', 'task_history', 'history', 'status')}
            names = list(samples)
            for number in range(125):
                time.sleep(max(0, start + index / 150 + number - time.monotonic()))
                try:
                    _, elapsed = readers[index].call(paths[number % 4])
                    if number >= 5:
                        samples[names[number % 4]].append(elapsed)
                except (OSError, RuntimeError, http.client.HTTPException) as error:
                    errors.append(type(error).__name__)
                    readers[index].close()
                    readers[index].connection = Connection()
            return samples

        accepted: list[dict] = []
        acceptance_latency: list[float] = []
        with ThreadPoolExecutor(150) as executor:
            futures = [executor.submit(reader, index) for index in range(150)]
            for index in range(150):
                time.sleep(max(0, start + 35 + index * 60 / 149 - time.monotonic()))
                row, elapsed = submit(index)
                accepted.append(row)
                acceptance_latency.append(elapsed)
            samples = [future.result() for future in futures]
        merged = {name: [value for sample in samples for value in sample[name]] for name in samples[0]}
        report['api'] = {name: metrics(values) for name, values in merged.items()}
        report['api']['overall'] = metrics([value for values in merged.values() for value in values])
        report['read_failures'] = dict(count=len(errors), types=sorted(set(errors)))
        completed(accepted)

        per_lab: dict[str, dict] = {}
        queue_delays, judging_durations = [], []
        first = min(datetime.fromisoformat(row['accepted_at']).timestamp() for row in accepted)
        last_finished = first
        for index, row in enumerate(accepted):
            detail = admin.call(f'/admin/labs/{labs[index]}/submissions/{row["id"]}')[0]
            if len(detail['cases']) != 10 or any(case['verdict'] != 'AC' for case in detail['cases']):
                raise RuntimeError('Mixed submission has unexpected case verdicts')
            accepted_at = datetime.fromisoformat(row['accepted_at']).timestamp()
            started_at = datetime.fromisoformat(detail['attempts'][0]['started_at']).timestamp()
            finished_at = datetime.fromisoformat(detail['history'][0]['finished_at']).timestamp()
            queue_delays.append((started_at - accepted_at) * 1000)
            judging_durations.append((finished_at - started_at) * 1000)
            last_finished = max(last_finished, finished_at)
            item = per_lab.setdefault(labs[index], dict(submissions=0, first_accepted=accepted_at, last_finished=finished_at))
            item['submissions'] += 1
            item['first_accepted'] = min(item['first_accepted'], accepted_at)
            item['last_finished'] = max(item['last_finished'], finished_at)
        report['mixed'] = dict(submissions=len(accepted), acceptance=metrics(acceptance_latency),
            completion_seconds=round(last_finished - first, 3), queue_delay=metrics(queue_delays),
            judging_duration=metrics(judging_durations),
            labs=[dict(submissions=item['submissions'], completion_seconds=round(item['last_finished'] - item['first_accepted'], 3))
                for item in per_lab.values()])
        report['passed'] = (len(accepted) == 150 and not errors and len(streams) == 150 and
            all(item['p95_ms'] <= 300 for item in report['api'].values()) and
            report['mixed']['completion_seconds'] <= 300)
    finally:
        for connection, response in streams:
            response.close()
            connection.close()
        admin.close()
        for client in readers + uploaders:
            client.close()


def main() -> None:
    global WEB_ADDRESS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('result', nargs='?', default='/tmp/cjudge-m9-results.json')
    parser.add_argument('--performance-only', action='store_true', help='Repeat performance after module gates have already passed')
    parser.add_argument('--mixed', action='store_true', help='Measure 3 labs with 50 students each during read, SSE, and submission load')
    options = parser.parse_args()
    normal = ['docker', 'compose']
    config = json.loads(command(normal + ['--profile', 'judging', 'config', '--format', 'json'], capture=True))
    running = command(normal + ['ps', '--services', '--status', 'running'], capture=True).split()
    stopped = [name for name in running if name in ('worker', 'judge')]
    env = dict(os.environ, CJUDGE_BIND_ADDRESS='127.0.0.1', CJUDGE_ALLOWED_HOSTS='localhost,127.0.0.1',
        CJUDGE_ACCEPTANCE_LABS='3' if options.mixed else '1')
    project = 'cjudge-m9-' + uuid4().hex[:10]
    compose = normal + ['-p', project, '-f', 'compose.yaml', '-f', 'deploy/acceptance.yaml']
    report = dict(timestamp=datetime.now(timezone.utc).isoformat(), platform=platform.platform(), cpu_count=os.cpu_count(),
        load_average=os.getloadavg(), python_version=platform.python_version(),
        docker_version=command(['docker', 'version', '--format', '{{.Server.Version}}'], capture=True).strip(),
        workers=int(config['services']['worker']['environment']['CJUDGE_SANDBOX_INSTANCES']),
        worker_memory_bytes=config['services']['worker'].get('mem_limit'),
        fixtures=['Arithmetic', 'Arrays', 'Strings', 'Sorting', 'Matrices'], cases_per_task=10,
        container_networks_internal=True, physical_lan_offline_check='pending', passed=False,
        scenario='3 labs × 50 mixed' if options.mixed else '1 lab × 150 baseline')
    for line in Path('/proc/cpuinfo').read_text().splitlines():
        if line.startswith('model name'):
            report['cpu_model'] = line.split(':', 1)[1].strip()
            break
    report['memory'] = Path('/proc/meminfo').read_text().splitlines()[0]
    report['commit'] = command(['git', 'rev-parse', 'HEAD'], capture=True).strip()
    report['tracked_changes'] = subprocess.run(['git', 'diff', '--quiet']).returncode != 0
    destination = Path(options.result)
    report['project'] = project
    destination.write_text(json.dumps(report, indent=2) + '\n')
    def dc(*args: str, capture: bool = False) -> str | None:
        return command(compose + list(args), capture=capture, env=env)
    try:
        isolated = json.loads(dc('--profile', 'judging', 'config', '--format', 'json', capture=True))
        report['images'] = {name: command(['docker', 'image', 'inspect', isolated['services'][name]['image'],
            '--format', '{{.Id}}'], capture=True).strip() for name in ('api', 'web', 'worker')}
        report['api_command'] = json.loads(command(['docker', 'image', 'inspect', isolated['services']['api']['image'],
            '--format', '{{json .Config.Cmd}}'], capture=True))
        assert all(network.get('internal') for network in isolated['networks'].values())
        assert all(not isolated['services'][name].get('ports') for name in ('api', 'db', 'worker'))
        if stopped:
            command(normal + ['stop', *stopped])
        dc('up', '-d', '--no-build', 'db')
        wait(lambda: subprocess.run(compose + ['exec', '-T', 'db', 'pg_isready', '-U', 'cjudge', '-d', 'cjudge'],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0)
        dc('run', '--rm', 'key-init')
        dc('run', '--rm', 'api', 'alembic', 'upgrade', 'head')
        dc('up', '-d', '--no-build', 'web')
        wait(lambda: subprocess.run(compose + ['exec', '-T', 'api', 'python', '-c',
            'import urllib.request; urllib.request.urlopen("http://localhost:8000/api/ready")'],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0)
        WEB_ADDRESS = str(ipaddress.ip_address(dc('exec', '-T', 'api', 'python', '-c',
            'import socket; print(socket.gethostbyname("web"))', capture=True).strip()))
        report['transport'] = 'HTTPS to internal nginx bridge, verified localhost certificate/Host/Origin'
        if not options.performance_only:
            dc('exec', '-T', 'api', 'python', 'tests/identity_gate.py')
            for name in ('tasks', 'labs', 'submissions', 'release'):
                dc('exec', '-T', 'api', 'python', f'tests/{name}_gate.py')
            for name in ('sandbox_checks', 'sandbox_parallel', 'judging_gate', 'marks_gate', 'authoring_gate'):
                arguments = ['--sandbox'] if name in ('marks_gate', 'authoring_gate') else []
                dc('run', '--rm', '-e', 'CJUDGE_SANDBOX_INSTANCES=2', '-e', 'TMPDIR=/var/lib/cjudge-authoring',
                    '-v', './migrations:/app/migrations:ro', '-v', './alembic.ini:/app/alembic.ini:ro',
                    'worker', 'python', f'tests/{name}.py', *arguments)
        report['module_gates_passed'] = None if options.performance_only else True
        dc('--profile', 'judging', 'up', '-d', '--no-build', 'worker')
        state = json.loads(dc('exec', '-T', 'api', 'python', 'tests/deployment_seed.py', capture=True))
        report['fixture_hashes'] = [{key: program[key] for key in ('title', 'source_sha256', 'cases_sha256')}
            for program in state['programs']]
        report['grading_limits'] = dict(cpu_seconds=.2, wall_seconds=1, memory_mib=64, stack_mib=8, stdout_mib=1)
        def restart() -> None:
            global WEB_ADDRESS
            dc('restart', 'api', 'web', 'worker')
            WEB_ADDRESS = str(ipaddress.ip_address(dc('exec', '-T', 'api', 'python', '-c',
                'import socket; print(socket.gethostbyname("web"))', capture=True).strip()))
        stop_samples = threading.Event()
        peaks: dict = {}
        sampler = threading.Thread(target=sample_resources, args=(project, stop_samples, peaks), daemon=True)
        sampler.start()
        try:
            if options.mixed:
                mixed_benchmark(state, report)
            else:
                benchmark(state, report, restart)
        finally:
            stop_samples.set()
            sampler.join(timeout=20)
            report['resource_peaks'] = peaks
            report['load_average_after'] = os.getloadavg()
    except Exception as error:
        report['error'] = str(error)
        logs = dc('logs', '--tail', '200', 'api', capture=True)
        report['transaction_error_types'] = re.findall(r'Transaction unavailable \(([A-Za-z_]+)\)', logs)
        raise
    finally:
        try:
            try:
                dc('--profile', 'judging', '--profile', 'setup', 'down', '--volumes')
                report['disposable_cleanup_complete'] = True
            finally:
                if stopped:
                    command(normal + ['--profile', 'judging', 'up', '-d', *stopped])
                report['normal_services_restored'] = True
        finally:
            destination.write_text(json.dumps(report, indent=2) + '\n')
        print(f'Results: {destination}; passed={report["passed"]}', file=sys.stderr)
    if not report['passed']:
        raise SystemExit('Performance target failed; inspect results')


if __name__ == '__main__':
    def terminate(signum: int, frame) -> None:
        raise KeyboardInterrupt('Acceptance interrupted; restoring services')
    signal.signal(signal.SIGTERM, terminate)
    main()
