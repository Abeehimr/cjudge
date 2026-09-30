import hashlib
from uuid import uuid4

import pytest

from cjudge.submissions import files


def test_bounded_immutable_sources(monkeypatch, tmp_path):
    monkeypatch.setenv('CJUDGE_SUBMISSION_FILES', str(tmp_path))
    source, key = b'int main(void) { return 0; }', uuid4()
    digest = files.validate('main.c', source)
    files.save(key, source)
    row = {'id': key, 'size': len(source), 'sha256': digest}
    assert files.read(row) == source
    with pytest.raises(FileExistsError):
        files.save(key, b'changed')
    with pytest.raises(OSError):
        files.read(row | {'sha256': hashlib.sha256(b'changed').hexdigest()})
    for name, data in [('../main.c', source), ('x.cpp', source), ('x.c', b''),
                       ('x.c', b'x' * 65537), ('x.c', b'x\x00')]:
        with pytest.raises(ValueError):
            files.validate(name, data)
    path = tmp_path / f'{key}.c'
    path.unlink()
    path.symlink_to(tmp_path / 'outside')
    with pytest.raises(OSError):
        files.read(row)
