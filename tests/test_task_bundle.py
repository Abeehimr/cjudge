"""M21 bundle compatibility and hostile ZIP validation."""

import io
import json
import zipfile

import pytest

from cjudge.tasks.bundle import build, parse


def make_zip(entries):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries:
            archive.writestr(name, content)
    return output.getvalue()


def test_task_bundle_round_trip():
    config = {'title': 'Count', 'statement': '# Count\nSolve it.', 'scoring': 'all_or_nothing',
        'checker': {'kind': 'python', 'source': 'accept()'}, 'banned_identifiers': ['printf'],
        'cpu_seconds': 3, 'wall_seconds': 7}
    payload = build(config, [(b'\x00\xff', b''), (b'2\n', b'2\n')])
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        assert archive.namelist() == ['manifest.json', 'cases/1.in', 'cases/1.out', 'cases/2.in', 'cases/2.out']
        manifest = json.loads(archive.read('manifest.json'))
        assert manifest['format'] == 'cjudge-task' and manifest['version'] == 1
        assert manifest['case_count'] == 2 and 'maximum_marks' not in manifest['config']
    restored, cases = parse(payload)
    assert restored['statement'] == config['statement']
    assert restored['checker']['source'] == 'accept()'
    assert restored['banned_identifiers'] == ['printf']
    assert restored['cpu_seconds'] == 3
    assert cases == [(b'\x00\xff', b''), (b'2\n', b'2\n')]


@pytest.mark.parametrize('change', [
    lambda m, e: m.update(version=2),
    lambda m, e: m.update(case_count=2),
    lambda m, e: m.update(config={'title': 'Bad', 'checker': {'kind': 'python', 'source': ''}}),
    lambda m, e: e.append(('cases/1.in', b'duplicate')),
    lambda m, e: e.append(('../secret', b'x')),
    lambda m, e: e.pop(),
    lambda m, e: e.append(('generator.py', b'print(1)')),
])
def test_reject_invalid_bundle(change):
    manifest = {'format': 'cjudge-task', 'version': 1, 'config': {'title': 'A'}, 'case_count': 1}
    entries = [('cases/1.in', b'1'), ('cases/1.out', b'1')]
    change(manifest, entries)
    with pytest.raises(ValueError):
        parse(make_zip([('manifest.json', json.dumps(manifest)), *entries]))


def test_reject_large_expansion_and_unknown_type():
    manifest = json.dumps({'format': 'cjudge-task', 'version': 1, 'config': {'title': 'A'}, 'case_count': 1})
    with pytest.raises(ValueError):
        parse(make_zip([('manifest.json', manifest), ('cases/1.in', b'x' * (1024 * 1024 + 1)), ('cases/1.out', b'')]))
    assert parse(make_zip([('manifest.json', manifest), ('cases/1.in', b''), ('cases/1.out', b'')]))[1] == [(b'', b'')]
