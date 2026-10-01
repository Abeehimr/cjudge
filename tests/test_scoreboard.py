from datetime import datetime, timedelta, timezone
from fractions import Fraction
from uuid import UUID

from cjudge.labs.scoreboard import standings


START = datetime(2026, 1, 1, tzinfo=timezone.utc)
TASKS = [dict(task_id=UUID(int=i), config=dict(title=f'Task {i}', maximum_marks='10')) for i in (1, 2)]
STUDENTS = [dict(id=UUID(int=i), name=f'Student {i}', roll_number=f'R{i}') for i in (3, 4, 5)]


def attempt(key, student, task, score, seconds, *, state='complete', deleted=False):
    value = Fraction(score or 0)
    return dict(id=UUID(int=key), account_id=UUID(int=student), task_id=UUID(int=task),
        run_id=UUID(int=key) if score is not None else None, score_numerator=str(value.numerator),
        score_denominator=str(value.denominator), accepted_at=START + timedelta(seconds=seconds),
        state=state, deleted_at=START if deleted else None)


def test_counted_attempts_ranking_time_and_link_privacy():
    rows = [attempt(10, 3, 1, 10, 30), attempt(11, 3, 1, 10, 40), attempt(12, 3, 2, 0, 60),
        attempt(13, 4, 1, 10, 20), attempt(14, 5, 1, 5, 1)]
    board = standings(TASKS, STUDENTS, rows, set(), START, UUID(int=3))
    assert [row['roll_number'] for row in board['students']] == ['R4', 'R3', 'R5']
    assert [row['elapsed_us'] for row in board['students']] == [20_000_000, 30_000_000, 1_000_000]
    assert board['students'][1]['tasks'][0]['submission_id'] == UUID(int=10)
    assert board['students'][0]['tasks'][0]['submission_id'] is None
    assert board['students'][0]['tasks'][0]['state'] == 'first_solve'
    assert board['students'][1]['tasks'][0]['state'] == 'solved'
    assert board['students'][1]['tasks'][1]['state'] == 'zero'
    assert board['students'][2]['tasks'][0]['state'] == 'partial'
    assert board['students'][2]['tasks'][1]['state'] == 'empty'


def test_deletion_restoration_pending_and_first_solve_ties():
    rows = [attempt(10, 3, 1, 10, 20), attempt(11, 4, 1, 10, 20),
        attempt(12, 5, 1, 10, 10, deleted=True)]
    board = standings(TASKS, STUDENTS, rows, set(), START)
    assert [row['rank'] for row in board['students']] == [1, 1, 3]
    assert board['students'][0]['tasks'][0]['state'] == 'first_solve'
    rows[2]['deleted_at'] = None
    board = standings(TASKS, STUDENTS, rows, {UUID(int=1)}, START)
    assert board['students'][0]['roll_number'] == 'R5'
    assert board['students'][0]['tasks'][0]['first_solve']
    assert all(row['tasks'][0]['state'] == 'judging' and row['pending'] for row in board['students'])
    assert all(row['total'] == '10.00' for row in board['students'])
    rows[2]['state'] = 'delayed'
    board = standings(TASKS, STUDENTS, rows, set(), START)
    assert board['students'][0]['tasks'][0]['delayed']


def test_exact_selection_rounded_totals_and_unrounded_time():
    rows = [attempt(10, 3, 1, Fraction(1001, 1000), .000002),
        attempt(11, 3, 1, Fraction(1002, 1000), .000003),
        attempt(12, 4, 1, Fraction(1001, 1000), .000001)]
    board = standings(TASKS, STUDENTS[:2], rows, set(), START)
    assert [row['total'] for row in board['students']] == ['1.00', '1.00']
    assert [row['elapsed_us'] for row in board['students']] == [1, 3]
    assert board['students'][1]['tasks'][0]['submission_id'] == UUID(int=11)
    assert standings([], [], [], set(), None) == {'tasks': [], 'students': []}


def test_pending_without_result_is_not_graded_zero():
    board = standings(TASKS, STUDENTS[:1], [attempt(10, 3, 1, None, 1, state='queued')], set(), START)
    cell = board['students'][0]['tasks'][0]
    assert cell['state'] == 'judging' and cell['marks'] is None
    assert cell['submission_id'] is None and cell['elapsed_us'] is None
    assert board['students'][0]['elapsed_us'] == 0


def test_live_notifications_broadcast_only_when_enabled():
    from unittest.mock import Mock, patch
    from cjudge.judging.queue import notify, ADMIN_CHANNEL
    conn = Mock()
    account, lab = UUID(int=3), UUID(int=10)
    with patch('cjudge.events.publish') as publish:
        conn.execute.return_value.scalar_one.return_value = False
        notify(conn, account, lab_id=lab)
        assert publish.call_count == 2
        publish.assert_any_call(conn, lab_id=ADMIN_CHANNEL)
        publish.assert_any_call(conn, account_id=account)
        publish.reset_mock()
        conn.execute.return_value.scalar_one.return_value = True
        notify(conn, account, lab_id=lab)
        assert publish.call_count == 3
        publish.assert_any_call(conn, lab_id=lab, account_id=None)
