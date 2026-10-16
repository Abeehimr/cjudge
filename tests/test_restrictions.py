"""Source-token teaching rules and bounded-input behavior."""
import pytest
from pydantic import ValidationError

from cjudge.tasks.grading import TaskConfig
from cjudge.tasks.restrictions import first_banned


def test_config_defaults_and_validation():
    assert TaskConfig(title='A').banned_identifiers == []
    assert TaskConfig(title='A').languages == ['c11']
    assert TaskConfig(title='A', languages=['c11', 'cpp17']).languages == ['c11', 'cpp17']
    for languages in ([], ['cpp'], ['c11', 'c11']):
        with pytest.raises(ValidationError):
            TaskConfig(title='A', languages=languages)
    assert TaskConfig(title='A', banned_identifiers=['printf', 'Printf']).banned_identifiers == ['printf', 'Printf']
    assert TaskConfig(title='A', banned_identifiers=['for', '+', '-', '*', '/']).banned_identifiers == ['for', '+', '-', '*', '/']
    for names in (['printf', 'printf'], ['9bad'], ['bad-name'], ['é'], ['a' * 129], ['x'] * 101, ['++'], ['%']):
        with pytest.raises(ValidationError):
            TaskConfig(title='A', banned_identifiers=names)


def test_scanner_skips_non_identifiers_and_reports_original_line():
    names = ['printf', 'stdio', 'hidden']
    source = b'#include <stdio.h>\n// printf\nchar *s="printf"; char c=\'p\';\nint my_printf;\n0xprintf;\n/* hidden\n ignored */\npri\\\nntf("yes");\n'
    assert first_banned(source, names) == ('printf', 8)
    assert first_banned(b'char *x="printf"; // printf\n/* printf */', names) is None
    assert first_banned(b'PRINTf();', names) is None
    assert first_banned(b'#define printf puts\n', names) == ('printf', 1)
    assert first_banned(b'printf();', []) is None


def test_long_and_malformed_source_is_bounded():
    assert first_banned(b'a' * 65530 + b'printf', ['printf']) is None
    assert first_banned(b'a' * 65536, ['printf']) is None
    assert first_banned(b'/* unterminated printf', ['printf']) is None


def test_cpp_raw_literals_separators_and_original_lines():
    assert first_banned(b'auto s=R"tag(" while )tag";\nwhile(1){}', ['while'], 'cpp17') == ('while', 2)
    assert first_banned(b'auto s=u8R"(while " for)";', ['while', 'for', 'u8R'], 'cpp17') is None
    assert first_banned(b'auto n=1\'000;\nfor(;;){}', ['for'], 'cpp17') == ('for', 2)
    assert first_banned(b'auto s=R"tag()\\\ntag" while )tag";', ['while'], 'cpp17') is None
    assert first_banned(b'auto s=R"(unterminated while', ['while'], 'cpp17') is None


@pytest.mark.parametrize('language', ['c11', 'cpp17'])
@pytest.mark.parametrize('symbol,source', [
    ('+', b'x + y'), ('+', b'++x'), ('+', b'x += 1'), ('+', b'+x'),
    ('-', b'x - y'), ('-', b'--x'), ('-', b'x -= 1'), ('-', b'-1'), ('-', b'p->x'),
    ('*', b'x * y'), ('*', b'x *= 2'), ('*', b'int *p'), ('*', b'*p'),
    ('/', b'x / y'), ('/', b'x /= 2'),
])
def test_banned_operator_uses(symbol, source, language):
    assert first_banned(source, [symbol], language) == (symbol, 1)


def test_operators_skip_comments_literals_headers_and_numeric_exponents():
    symbols = ['+', '-', '*', '/']
    source = b'#include <dir/a-b+c*d.h>\n// +-*/\n/* +-*/\nchar s[]="+-*/"; char c=\'/\'; double x=1e-3; double y=0x1p+2;'
    assert first_banned(source, symbols) is None
    assert first_banned(b'auto s=u8R"tag(+-*/)tag";', symbols, 'cpp17') is None
    assert first_banned(b'/* / */\nx\\\n/=2;', ['/']) == ('/', 3)
    assert first_banned(b'for(;;) x += 1;', ['+', 'for']) == ('for', 1)


@pytest.mark.parametrize('language', ['c11', 'cpp17'])
def test_operator_rejection_prevents_compilation_in_judge_and_tester(monkeypatch, language):
    from unittest.mock import MagicMock
    from cjudge import identity, tasks, tester
    from cjudge.judging import worker

    revision = {'task_id': 'task', 'config': {'title': 'No addition', 'banned_identifiers': ['+']},
        'case_count': 1, 'cases_key': 'cases'}
    conn = MagicMock()
    conn.execute.return_value.mappings.return_value.one.return_value = revision
    conn.execute.return_value.scalar_one.return_value = 5
    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value = conn
    monkeypatch.setattr(identity, 'engine', lambda: engine)
    monkeypatch.setattr(worker.files, 'read', lambda row: b'int main(void){return 1+2;}')
    monkeypatch.setattr(tester, 'read', lambda job, part: b'int main(void){return 1+2;}')
    monkeypatch.setattr(tasks, 'load_cases', lambda key: [(b'', b'')])
    compile_source = MagicMock(side_effect=AssertionError('restricted source compiled'))
    monkeypatch.setattr(worker.runner, 'compile_source', compile_source)
    judged = worker.judge({'revision_id': 'revision', 'lab_id': 'lab', 'language': language}, None)
    tested = tester.run_case({'revision_id': 'revision', 'progress': 0, 'language': language})
    assert judged['verdict'] == tested['verdict'] == 'Restricted'
    assert judged['restriction'] == tested['restriction'] == {'identifier': '+', 'line': 1}
    assert judged['score_numerator'] == '0' and judged['cases'] == []
    compile_source.assert_not_called()
