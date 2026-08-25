"""打卡核对工具：日期推导、结果扁平化、多维表删除旧记录测试。"""

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

from app.modules.toolbox.tools.attendance_check._bitable import (
    delete_all_records,
    flatten_check_result,
)
from app.modules.toolbox.tools.attendance_check._core import months_in_range

CHINA_TZ = timezone(timedelta(hours=8))


def test_months_in_range_single_month() -> None:
    assert months_in_range(date(2026, 8, 1), date(2026, 8, 24)) == ["2026-08"]


def test_months_in_range_multi_month() -> None:
    assert months_in_range(date(2026, 7, 15), date(2026, 9, 2)) == ["2026-07", "2026-08", "2026-09"]


def test_months_in_range_cross_year() -> None:
    assert months_in_range(date(2025, 12, 20), date(2026, 1, 5)) == ["2025-12", "2026-01"]


def test_flatten_check_result() -> None:
    check_result = [
        {
            "员工姓名": "张三",
            "工号": "1",
            "异常": [
                {
                    "日期": "2026-05-03",
                    "异常类型": ["迟到"],
                    "缺卡": None,
                    "迟到": 5,
                    "早退": None,
                    "应上班时间": "08:30",
                    "应下班时间": "17:30",
                }
            ],
        }
    ]
    records = flatten_check_result(check_result)
    expected_ts = int(datetime(2026, 5, 3, tzinfo=CHINA_TZ).timestamp() * 1000)
    assert records == [
        {
            "姓名": "张三",
            "工号": "1",
            "异常日期": expected_ts,
            "异常类型": ["迟到"],
            "缺卡类型": [],
            "迟到分钟": 5,
            "应上班时间": "08:30",
            "应下班时间": "17:30",
            "月份": 5,
        }
    ]


def test_flatten_check_result_drops_none_fields() -> None:
    check_result = [
        {
            "员工姓名": "李四",
            "工号": "2",
            "异常": [
                {
                    "日期": "2026-07-02",
                    "异常类型": ["缺卡"],
                    "缺卡": ["下班卡"],
                    "迟到": None,
                    "早退": None,
                    "应上班时间": "08:30",
                    "应下班时间": "18:00",
                }
            ],
        }
    ]
    records = flatten_check_result(check_result)
    expected_ts = int(datetime(2026, 7, 2, tzinfo=CHINA_TZ).timestamp() * 1000)
    assert records == [
        {
            "姓名": "李四",
            "工号": "2",
            "异常日期": expected_ts,
            "异常类型": ["缺卡"],
            "缺卡类型": ["下班卡"],
            "应上班时间": "08:30",
            "应下班时间": "18:00",
            "月份": 7,
        }
    ]


class FakeRecordAPI:
    """lark bitable 记录 API 替身：list 分页返回预置批次，batch_delete 记录调用。"""

    def __init__(self, batches: list[list[str]]) -> None:
        self._batches = batches
        self.delete_calls: list[list[str]] = []

    def list(self, _req: Any) -> SimpleNamespace:
        batch = self._batches.pop(0) if self._batches else []
        return SimpleNamespace(
            success=lambda: True,
            data=SimpleNamespace(
                items=[SimpleNamespace(record_id=f"rec-{i}") for i in batch],
                has_more=bool(self._batches),
                page_token="next" if self._batches else "",
            ),
        )

    def batch_delete(self, req: Any) -> SimpleNamespace:
        self.delete_calls.append(list(req.request_body.records))
        return SimpleNamespace(success=lambda: True)


class FakeBitable:
    def __init__(self, batches: list[list[str]]) -> None:
        self.v1 = SimpleNamespace(app_table_record=FakeRecordAPI(batches))


class FakeClient:
    def __init__(self, batches: list[list[str]]) -> None:
        self.bitable = FakeBitable(batches)


def test_delete_all_records_paginates_and_batches() -> None:
    # 3 页共 1010 条 → batch_delete 3 次（500/500/10）
    ids = [str(i) for i in range(1010)]
    client = FakeClient([ids[:500], ids[500:1000], ids[1000:]])
    deleted = delete_all_records(client, "app", "tbl")
    assert deleted == 1010
    api = client.bitable.v1.app_table_record
    assert len(api.delete_calls) == 3
    assert [len(b) for b in api.delete_calls] == [500, 500, 10]


def test_delete_all_records_empty_table() -> None:
    client = FakeClient([])
    deleted = delete_all_records(client, "app", "tbl")
    assert deleted == 0
    assert client.bitable.v1.app_table_record.delete_calls == []
