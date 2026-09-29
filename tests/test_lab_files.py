import pytest
from cjudge import lab_files, labs


def test_pdf_bounds_and_immutable_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(lab_files, 'FILES', tmp_path)
    data = b'%PDF-1.7\nexample\n%%EOF\n'
    first, second = lab_files.save(data), lab_files.save(data)
    assert first != second
    assert (tmp_path / f'{first}.pdf').read_bytes() == data
    assert (tmp_path / f'{first}.pdf').stat().st_mode & 0o777 == 0o400
    for payload in [b'not PDF', b'%PDF-1.7\nno end marker', data * (lab_files.MAX_PDF // len(data) + 1)]:
        with pytest.raises(labs.LabError):
            lab_files.validate_pdf(payload)
