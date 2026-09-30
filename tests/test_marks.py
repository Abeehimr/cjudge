from fractions import Fraction

from cjudge.submissions.review import displayed


def test_exact_half_up_rounding():
    assert displayed(Fraction(1, 200)) == '0.01'
    assert displayed(Fraction(1, 201)) == '0.00'
    assert displayed(Fraction(100, 3)) == '33.33'
    assert displayed(Fraction(200, 3)) == '66.67'
    assert displayed(Fraction(10**100 * 200 + 1, 200)).endswith('.01')
