from unittest.mock import Mock

import pytest
from sqlalchemy.exc import OperationalError

from app.services.aggregate_lock_service import AggregateLockBusy, lock_task


@pytest.mark.parametrize("code", [1205, 1213])
def test_mysql_contention_rolls_back_and_becomes_retryable(code):
    db = Mock()
    db.get_bind.return_value.dialect.name = "mysql"
    db.scalar.side_effect = OperationalError("select", {}, Exception(code, "contention"))
    with pytest.raises(AggregateLockBusy):
        lock_task(db, 1)
    db.rollback.assert_called_once()


def test_mysql_unrelated_error_is_not_disguised_as_contention():
    db = Mock()
    db.get_bind.return_value.dialect.name = "mysql"
    db.scalar.side_effect = OperationalError("select", {}, Exception(1146, "missing table"))
    with pytest.raises(OperationalError):
        lock_task(db, 1)
