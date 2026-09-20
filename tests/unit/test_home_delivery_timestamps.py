"""数据库无时区 UTC 时间必须以明确时区返回浏览器。"""

from datetime import datetime, timezone
from types import SimpleNamespace

from app.services.home_delivery_snapshot_service import share_response


def test_share_timestamps_keep_utc_after_database_roundtrip():
    instant = datetime(2026, 9, 18, 2, 0)
    row = SimpleNamespace(id=1, delivery_id=2, expires_at=instant, revoked_at=instant)
    result = share_response(row)
    assert result["expires_at"].tzinfo == timezone.utc
    assert result["revoked_at"].tzinfo == timezone.utc
    assert result["expires_at"].hour == 2
