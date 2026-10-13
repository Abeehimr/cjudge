from cjudge import tasks
from cjudge.submissions.api import case_details


def test_released_case_streams_hide_accepted_tests(monkeypatch) -> None:
    monkeypatch.setattr(tasks, 'load_cases', lambda key: [(b'secret input', b'secret answer')] * 2)
    class Results:
        def __init__(self, rows): self.rows = rows
        def mappings(self): return self
        def all(self): return self.rows
        def scalar_one(self): return 'case-key'
    class Connection:
        calls = 0
        def execute(self, statement):
            self.calls += 1
            if self.calls == 1:
                return Results([{'number': number, 'verdict': verdict, 'cpu_seconds': 0.1,
                    'wall_seconds': 0.2, 'memory_kib': 100, 'stdout': b'actual', 'stderr': b'',
                    'stdout_truncated': False, 'stderr_truncated': False}
                    for number, verdict in ((1, 'AC'), (2, 'WA'))])
            return Results([])
    cases = case_details(Connection(), None, None)
    assert all(cases[0][part] is None for part in ('stdin', 'expected', 'stdout', 'stderr'))
    assert cases[1]['stdin'] == 'secret input'
    assert cases[1]['expected'] == 'secret answer'
    assert cases[1]['stdout'] == 'actual'
