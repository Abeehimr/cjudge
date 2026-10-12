from decimal import Decimal
from fractions import Fraction
import pytest
from pydantic import ValidationError

from cjudge.submissions.review import displayed, exact
from cjudge.tasks.api import DraftInput
from cjudge.tasks.grading import TaskConfig


def test_assignment_maximum_scores_retained_outcomes_without_changing_evidence():
    run = dict(score_numerator='7', score_denominator='3', passed=1, total=3,
        result_config={'scoring': 'partial', 'maximum_marks': '7'}, legacy_archived_marks=False)
    assert exact(run | {'assignment_maximum': Decimal('5')}) == Fraction(5, 3)
    assert displayed(exact(run | {'assignment_maximum': Decimal('5')})) == '1.67'
    assert exact(run | {'assignment_maximum': Decimal('10')}) == Fraction(10, 3)
    assert displayed(exact(run | {'assignment_maximum': Decimal('10')})) == '3.33'
    assert exact(run | {'assignment_maximum': Decimal('10'), 'legacy_archived_marks': True}) == Fraction(7, 3)
    assert displayed(exact(run | {'assignment_maximum': Decimal('10'), 'legacy_archived_marks': True})) == '2.33'
    assert exact(run | {'assignment_maximum': Decimal('10'), 'result_config': {'scoring': 'all_or_nothing'}}) == 0
    assert run['score_numerator'] == '7'


def test_task_revision_serialization_does_not_write_maximum():
    assert 'maximum_marks' not in TaskConfig(title='Reusable task').model_dump(mode='json')
    assert 'maximum_marks' not in TaskConfig.model_validate({'title': 'Old task', 'maximum_marks': '7'}).model_dump(mode='json')
    assert DraftInput.model_validate({'version': 1, 'config': {'title': 'New task'}}).config.title == 'New task'
    with pytest.raises(ValidationError, match='Maximum marks belong to a lab assignment'):
        DraftInput.model_validate({'version': 1, 'config': {'title': 'New task', 'maximum_marks': '5'}})
