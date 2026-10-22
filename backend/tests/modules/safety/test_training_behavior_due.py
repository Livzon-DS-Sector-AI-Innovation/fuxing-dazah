"""链6 复训到期扫描测试。

接缝：opener 替身（training 客户端注入）。口径：30 天窗口（含已逾期），
状态=已取消不计；提醒文本确定性生成（非 AI 内容）；无到期行不发送。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from app.modules.safety.service.bitable_direct.errors import BitableConfigError
from app.modules.safety.service.training_behavior import retraining_due

TODAY = date(2026, 10, 22)
_BJ = timezone(timedelta(hours=8))


class FakeTrainingClient:
    def __init__(self, records: list[dict]) -> None:
        self.records = records

    async def list_all_records(self, **kwargs) -> list[dict]:
        return self.records


def _training(name: str, due_ms: int | None, status: str = "已完成") -> dict:
    fields: dict = {"培训名称": name, "状态": status}
    if due_ms is not None:
        fields["下次复训日期"] = due_ms
    return {"record_id": f"r-{name}", "fields": fields}


def _ms(d: date) -> int:
    # 北京时区当日 12:00 构造，避免 UTC 日界翻转影响窗口判定
    return int(datetime(d.year, d.month, d.day, 12, tzinfo=_BJ).timestamp() * 1000)


def _opener(records):
    client = FakeTrainingClient(records)

    def open_client(domain: str, kind: str):
        if (domain, kind) == ("training_behavior", "training"):
            return client
        raise BitableConfigError("未配置")

    return open_client


class TestRunRetrainingDueRound:
    async def test_window_filter_and_overdue_marking(self) -> None:
        opener = _opener([
            _training("甲", _ms(date(2026, 10, 25))),   # 3 天后：命中
            _training("乙", _ms(date(2026, 12, 1))),    # 窗口外
            _training("丙", _ms(date(2026, 10, 1))),    # 已逾期 21 天
            _training("丁", None),                       # 无复训日期
            _training("戊", _ms(date(2026, 10, 25)), status="已取消"),
        ])
        sent: list[str] = []

        async def send_digest(text: str) -> None:
            sent.append(text)

        outcome = await retraining_due.run_retraining_due_round(
            opener=opener, today=TODAY, send_digest=send_digest,
        )
        assert outcome["status"] == "ok"
        assert outcome["due"] == 2
        assert outcome["overdue"] == 1
        assert len(sent) == 1
        assert "甲" in sent[0] and "丙" in sent[0]
        assert "乙" not in sent[0] and "丁" not in sent[0] and "戊" not in sent[0]
        assert "逾期" in sent[0]

    async def test_no_due_no_send(self) -> None:
        opener = _opener([_training("乙", _ms(date(2026, 12, 1)))])
        sent: list[str] = []

        async def send_digest(text: str) -> None:
            sent.append(text)

        outcome = await retraining_due.run_retraining_due_round(
            opener=opener, today=TODAY, send_digest=send_digest,
        )
        assert outcome["due"] == 0
        assert sent == []

    async def test_not_connected_soft_skip(self) -> None:
        def opener(domain: str, kind: str):
            raise BitableConfigError("未接入")

        outcome = await retraining_due.run_retraining_due_round(
            opener=opener, today=TODAY, send_digest=None,
        )
        assert outcome["status"] == "not_connected"
