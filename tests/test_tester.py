"""M22 admission and protected artifact boundaries."""
import io
import warnings
from uuid import uuid4
import zipfile

import pytest

from cjudge import tester


def bundle(entries: list[tuple[str, bytes]], *, compression=zipfile.ZIP_DEFLATED) -> bytes:
    output = io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', UserWarning)
        with zipfile.ZipFile(output, 'w', compression=compression) as archive:
            for name, data in entries:
                archive.writestr(name, data)
    return output.getvalue()


def test_single_and_flat_archive_limits():
    assert tester.parse_sources('main.c', b'int main(){}', archive=False) == [('main.c', b'int main(){}')]
    assert tester.parse_sources('main.cpp', b'int main(){}', archive=False) == [('main.cpp', b'int main(){}')]
    assert tester.parse_sources('', bundle([('a.c', b'a'), ('b.c', b'b')]), archive=True) == [('a.c', b'a'), ('b.c', b'b')]
    for filename, content in [('no.txt', b'a'), ('../bad.c', b'a'), ('a.c', b''), ('a.c', b'\0'),
                              ('a.c', b'a' * (65536 + 1))]:
        with pytest.raises(ValueError):
            tester.parse_sources(filename, content, archive=False)
    for entries in ([], [('dir/a.c', b'a')], [('a.c', b'a'), ('a.c', b'b')],
                    [('a.c', b'\0')], [('a.c', b'a' * 65537)],
                    [(f'{number}.c', b'x') for number in range(21)]):
        with pytest.raises(ValueError):
            tester.parse_sources('', bundle(entries), archive=True)
    symlink = zipfile.ZipInfo('link.c')
    symlink.external_attr = (0o120777 << 16)
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        archive.writestr(symlink, 'target')
    with pytest.raises(ValueError):
        tester.parse_sources('', output.getvalue(), archive=True)


def test_artifacts_are_immutable_and_verified(tmp_path, monkeypatch):
    monkeypatch.setenv('CJUDGE_AUTHORING_FILES', str(tmp_path))
    batch_id, source_id = uuid4(), uuid4()
    source = b'int main(){return 0;}'
    tester.save(batch_id, source_id, 'c', source)
    row = {'batch_id': batch_id, 'id': source_id, 'size': len(source),
           'sha256': __import__('hashlib').sha256(source).hexdigest()}
    assert tester.read(row, 'c') == source
    with pytest.raises(FileExistsError):
        tester.save(batch_id, source_id, 'c', b'changed')
    row['sha256'] = '0' * 64
    with pytest.raises(OSError):
        tester.read(row, 'c')
    tester.path(batch_id, source_id, 'bin').symlink_to('/etc/passwd')
    with pytest.raises(OSError):
        tester.read(row, 'bin')
