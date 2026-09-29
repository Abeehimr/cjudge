from decimal import Decimal
from fractions import Fraction

import pytest

from cjudge.task_grading import Checker, TaskConfig, compare_output, score


def test_checker_contract():
    assert compare_output(b'42\n', b'42\n', Checker())
    assert not compare_output(b'42', b'42\n', Checker())
    relaxed = Checker(ignore_final_newline=True)
    assert compare_output(b'42\r\n', b'42', relaxed)
    assert not compare_output(b'42\n\n', b'42', relaxed)
    assert not compare_output(b'42 ', b'42', relaxed)
    tokens = Checker(kind='tokens')
    assert compare_output(b'a\t b\r\n', b'a b', tokens)
    assert not compare_output(b'A', b'a', tokens)
    assert not compare_output(b'a\xc2\xa0b', b'a b', tokens)
    assert not compare_output(b'a b c', b'a b', tokens)
    numeric = Checker(kind='tokens', ignore_case=True, absolute_tolerance='0.001', relative_tolerance='0.01')
    assert compare_output(b'HELLO 1e2 .0005', b'hello 101 0', numeric)
    assert not compare_output(b'100', b'102', numeric)
    assert not compare_output(b'nan', b'1', numeric)
    assert not compare_output(b'inf', b'1e9999', numeric)
    assert not compare_output(b'1e99999', b'2e99999', numeric)
    assert compare_output(b'NaN', b'nan', numeric)  # literal case-insensitive equality, no numeric shortcut
    assert not compare_output(b'1' * 129, b'2' * 129, numeric)
    with pytest.raises(ValueError):
        Checker(absolute_tolerance='0.1')
    with pytest.raises(ValueError):
        Checker(kind='tokens', relative_tolerance='NaN')


def test_config_and_rational_scoring():
    assert TaskConfig(title=' Sum ').title == 'Sum'
    assert TaskConfig(title='Sum').statement == ''
    for body in [{'title': ' '}, {'title': 'x', 'cpu_seconds': 7},
                 {'title': 'x', 'memory_mib': 2}, {'title': 'x', 'maximum_marks': '1.001'}]:
        with pytest.raises(ValueError):
            TaskConfig(**body)
    assert score(Decimal('10'), 1, 3, 'partial') == Fraction(10, 3)
    assert score(Decimal('10'), 2, 3, 'all_or_nothing') == 0
    assert score(Decimal('10'), 3, 3, 'all_or_nothing') == 10
    with pytest.raises(ValueError):
        score(Decimal('10'), 0, 0, 'partial')
