"""Versioned, bounded task ZIPs; archive names never become filesystem paths."""

import io
import json
import stat
import zipfile
import zlib

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from cjudge.tasks.cases import MAX_CASES, MAX_FILE, MAX_TOTAL, MAX_ZIP, validate_cases
from cjudge.tasks.grading import TaskConfig


MANIFEST_LIMIT = 1024 * 1024


class Manifest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    format: str
    version: int
    config: TaskConfig
    case_count: int = Field(ge=1, le=MAX_CASES)


def build(config: dict, cases: list[tuple[bytes, bytes]]) -> bytes:
    validate_cases(cases)
    manifest = Manifest(format='cjudge-task', version=2,
        config=TaskConfig.model_validate(config), case_count=len(cases))
    metadata = manifest.model_dump_json(exclude={'config': {'maximum_marks'}}).encode()
    if len(metadata) > MANIFEST_LIMIT:
        raise ValueError('Task manifest exceeds 1 MiB')
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_STORED) as archive:
        archive.writestr('manifest.json', metadata)
        for number, (input_bytes, answer) in enumerate(cases, 1):
            archive.writestr(f'cases/{number}.in', input_bytes)
            archive.writestr(f'cases/{number}.out', answer)
    payload = output.getvalue()
    if len(payload) > MAX_ZIP:
        raise ValueError('Task ZIP exceeds 17 MiB')
    return payload


def parse(payload: bytes) -> tuple[dict, list[tuple[bytes, bytes]]]:
    if len(payload) > MAX_ZIP:
        raise ValueError('Task ZIP exceeds 17 MiB')
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            entries = archive.infolist()
            if not 3 <= len(entries) <= 1 + MAX_CASES * 2:
                raise ValueError('Task ZIP needs a manifest and 1–100 paired cases')
            names = [entry.filename for entry in entries]
            if len(names) != len(set(names)) or 'manifest.json' not in names:
                raise ValueError('Missing manifest or duplicate ZIP entry')
            files = {}
            total = 0
            for entry in entries:
                limit = MANIFEST_LIMIT if entry.filename == 'manifest.json' else MAX_FILE
                kind = stat.S_IFMT(entry.external_attr >> 16)
                if (kind not in (0, stat.S_IFREG) or entry.flag_bits & 1 or
                        entry.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
                    raise ValueError('Only unencrypted regular ZIP files are allowed')
                if entry.file_size > limit:
                    raise ValueError('Task ZIP entry exceeds size limit')
                total += entry.file_size
                if total > MANIFEST_LIMIT + MAX_TOTAL:
                    raise ValueError('Task ZIP expanded size exceeds limits')
                with archive.open(entry) as stream:
                    content = stream.read(limit + 1)
                if len(content) != entry.file_size or len(content) > limit:
                    raise ValueError('Invalid ZIP entry size')
                files[entry.filename] = content
            manifest_data = json.loads(files.pop('manifest.json'))
            if not isinstance(manifest_data, dict) or not isinstance(manifest_data.get('config'), dict):
                raise ValueError('Invalid task manifest')
            if 'maximum_marks' in manifest_data['config']:
                raise ValueError('Task ZIP must not contain lab marks')
            manifest = Manifest.model_validate(manifest_data)
            if manifest.format != 'cjudge-task' or manifest.version not in (1, 2):
                raise ValueError('Unsupported task ZIP format/version')
            if manifest.version == 1 and manifest.config.languages != ['c11']:
                raise ValueError('Task ZIP v1 supports only C11')
            expected = {f'cases/{number}.{part}' for number in range(1, manifest.case_count + 1)
                        for part in ('in', 'out')}
            if files.keys() != expected:
                raise ValueError('Task ZIP must contain only consecutive paired cases')
            cases = [(files[f'cases/{number}.in'], files[f'cases/{number}.out'])
                     for number in range(1, manifest.case_count + 1)]
            validate_cases(cases)
            return manifest.config.model_dump(mode='json', exclude={'maximum_marks'}), cases
    except (zipfile.BadZipFile, EOFError, RuntimeError, NotImplementedError, zlib.error,
            json.JSONDecodeError, ValidationError, UnicodeDecodeError) as exc:
        raise ValueError('Invalid task ZIP') from exc
