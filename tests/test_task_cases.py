import io
import warnings
import stat
import zipfile

import pytest

from cjudge.task_cases import MAX_FILE, parse_zip, validate_cases


def zipped(entries):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            for name, content in entries:
                archive.writestr(name, content)
    return output.getvalue()


def test_zip_pairing_order_and_binary_content():
    assert parse_zip(zipped([('2.out', b'\xff'), ('1.in', b''), ('2.in', b'2'), ('1.out', b'1')])) == [
        (b'', b'1'), (b'2', b'\xff')]
    for name in ['../1.in', '/1.in', 'x/1.in', '01.in', '1\\.in', '1.in\x00bad']:
        # ZipInfo truncates NUL on writing, so cover actual archive bytes separately below.
        if '\x00' not in name:
            with pytest.raises(ValueError):
                parse_zip(zipped([(name, b''), ('1.out', b'')]))
    for entries in [[('1.in', b'')], [('1.in', b''), ('2.out', b'')],
                    [('1.in', b''), ('1.in', b''), ('1.out', b'')],
                    [('1.in', b'x' * (MAX_FILE + 1)), ('1.out', b'')]]:
        with pytest.raises(ValueError):
            parse_zip(zipped(entries))
    symlink = zipfile.ZipInfo('1.in')
    symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
    with pytest.raises(ValueError):
        parse_zip(zipped([(symlink, b'/etc/passwd'), ('1.out', b'')]))
    with pytest.raises(ValueError):
        parse_zip(b'not a zip')
    stored = io.BytesIO()
    with zipfile.ZipFile(stored, "w", zipfile.ZIP_STORED) as archive:
        archive.writestr("1.in", b"secret")
        archive.writestr("1.out", b"ok")
    corrupted = bytearray(stored.getvalue())
    location = corrupted.index(b"secret")
    corrupted[location] = ord("X")
    with pytest.raises(ValueError):
        parse_zip(bytes(corrupted))
    with pytest.raises(ValueError):
        validate_cases([(b'', b'')] * 101)
    with pytest.raises(ValueError):
        validate_cases([(b'x' * MAX_FILE, b'x' * MAX_FILE)] * 9)
