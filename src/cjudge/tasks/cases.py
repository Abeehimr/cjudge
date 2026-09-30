"""Bounded task cases; archive names never become filesystem paths."""

import io
import re
import stat
import zipfile
import zlib

MAX_FILE = 1024 * 1024
MAX_TOTAL = 16 * 1024 * 1024
MAX_CASES = 100
MAX_ZIP = 17 * 1024 * 1024


def validate_cases(cases: list[tuple[bytes, bytes]]) -> None:
    if len(cases) > MAX_CASES:
        raise ValueError("At most 100 cases allowed")
    if any(len(part) > MAX_FILE for pair in cases for part in pair):
        raise ValueError("Each input/answer must be at most 1 MiB")
    if sum(len(part) for pair in cases for part in pair) > MAX_TOTAL:
        raise ValueError("Cases exceed 16 MiB combined")


def parse_zip(payload: bytes) -> list[tuple[bytes, bytes]]:
    if len(payload) > MAX_ZIP:
        raise ValueError("ZIP exceeds 17 MiB")
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            entries = archive.infolist()
            if not 2 <= len(entries) <= MAX_CASES * 2:
                raise ValueError("ZIP must contain 1–100 paired cases")
            files = {}
            total = 0
            for entry in entries:
                # Flat, canonical numeric names exclude traversal, aliases and directories.
                if not re.fullmatch(r"[1-9][0-9]{0,5}\.(in|out)", entry.orig_filename):
                    raise ValueError("Use flat N.in/N.out names, with N from 1 to 999999")
                kind = stat.S_IFMT(entry.external_attr >> 16)
                if kind not in (0, stat.S_IFREG) or entry.flag_bits & 1:
                    raise ValueError("Only unencrypted regular files allowed")
                if entry.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                    raise ValueError("Only stored/deflated ZIP entries allowed")
                if entry.filename in files:
                    raise ValueError("Duplicate ZIP entry")
                total += entry.file_size
                if entry.file_size > MAX_FILE or total > MAX_TOTAL:
                    raise ValueError("ZIP expanded size exceeds limits")
                with archive.open(entry) as stream:
                    content = stream.read(MAX_FILE + 1)
                if len(content) != entry.file_size or len(content) > MAX_FILE:
                    raise ValueError("Invalid ZIP entry size")
                files[entry.filename] = content
            numbers = sorted({int(name.split('.')[0]) for name in files})
            if any(f"{number}.{suffix}" not in files for number in numbers for suffix in ("in", "out")):
                raise ValueError("Each input requires a matching answer")
            cases = [(files[f"{number}.in"], files[f"{number}.out"]) for number in numbers]
            validate_cases(cases)
            return cases
    except (zipfile.BadZipFile, EOFError, RuntimeError, NotImplementedError, zlib.error) as exc:
        raise ValueError("Invalid ZIP archive") from exc
