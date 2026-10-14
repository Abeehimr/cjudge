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
    for names in (['printf', 'printf'], ['9bad'], ['bad-name'], ['é'], ['a' * 129], ['x'] * 101):
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
