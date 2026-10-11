"""Bounded CSV selection for enrollment removal; this never imports accounts."""
import csv
import io

from cjudge import identity


def parse_removal_csv(payload: bytes) -> list[str]:
    if len(payload) > 1024 * 1024:
        raise ValueError('CSV exceeds 1 MiB')
    try:
        reader = csv.DictReader(io.StringIO(payload.decode('utf-8-sig', errors='strict')), strict=True)
        if reader.fieldnames not in (['roll_number'], ['roll_number', 'name']):
            raise ValueError('CSV must have roll_number or roll_number,name headers')
        rolls, seen = [], set()
        for row in reader:
            if len(rolls) == 1000 or None in row or any(value is None for value in row.values()):
                raise ValueError('CSV has malformed rows or exceeds 1000 students')
            roll = identity.normalize_roll(row['roll_number'])
            if roll in seen:
                raise ValueError(f'Duplicate roll number: {roll}')
            seen.add(roll)
            rolls.append(roll)
        if not rolls:
            raise ValueError('CSV has no students')
        return rolls
    except (UnicodeError, csv.Error) as exc:
        raise ValueError('CSV must be valid UTF-8 CSV') from exc
