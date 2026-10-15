import pytest
from pydantic import ValidationError

from cjudge.identity.api import TAInput, TAPasswordInput


@pytest.mark.parametrize('length', [5, 6])
def test_ta_password_boundary(length: int) -> None:
    password = 'x' * length
    for model, fields in ((TAInput, {'username': 'helper', 'name': 'Helper'}), (TAPasswordInput, {})):
        if length == 5:
            with pytest.raises(ValidationError):
                model(password=password, **fields)
        else:
            assert model(password=password, **fields).password == password
