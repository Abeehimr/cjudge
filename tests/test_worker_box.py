from cjudge import runner


def test_worker_box_paths():
    try:
        runner.configure_box(7)
        assert str(runner.BOX) == '/var/local/lib/isolate/7/box'
        assert str(runner.CGROUP) == '/run/cjudge-cgroup/box-7'
        assert runner.ISOLATE[-1] == '--box-id=7'
        assert runner.META.name == 'cjudge-7.meta'
        assert runner.LOCK.name == 'cjudge-runner-7.lock'
    finally:
        runner.configure_box(0)
