"""ticket 06 新 Agent 双工具最小单测（preview / generate_guardian_subsidy）。

测试接缝（backend-design 6.3「工具层薄包装」）：
- mock 平台 client：monkeypatch ``subsidy_tools.WorkTicketPlatformClient`` 为
  FakeClient（经 __aenter__/__aexit__ 符合工具调用方式），避免真实凭据/网络；
- mock ``ctx.deps.db``：沿用 service/tests/test_subsidy_plan.py 的
  _FakeSession/_FakeResult（build_certificate_map 只调 execute(...).all()）；
- mock ``subsidy_tools.send_file_to_chat``：校验被调用参数与返回分支；
- 直接调用工具函数（不走 core.pipeline，避免真实审计写库）。

覆盖：
- preview 返回结构（total_fetched/matched_records/guardian_names/unmatched/skipped/
  departments/confirm_suggestion）与窗口计算（8 月 → 7/8/9 月；1 月跨年 → 去年 12 月起）；
- 部门不命中 → 候选部门 + need_department_selection；
- 拉取失败 → platform_fetch_error / auth_failed 降级；
- generate 发送成功（send_file_to_chat 收到 chat_id/bytes/文件名）+ 文字摘要；
- chat_id=None → 降级（不调发送）；
- 发送失败 → 兜底 base64；
- registry TOOL_KIND / _all_read_funcs / _all_write_funcs 接线；
- permissions 角色授予（admin/leader 可，inspector/viewer 拒）；
- executor 确认卡摘要分支（新的 generate_guardian_subsidy，旧 export_subsidy_report
  分支已删除）。
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from app.modules.safety.business_agent import executor
from app.modules.safety.business_agent.core import permissions as core_permissions
from app.modules.safety.business_agent.permissions import (
    TOOL_GENERATE_GUARDIAN_SUBSIDY,
    TOOL_PREVIEW_GUARDIAN_SUBSIDY,
)
from app.modules.safety.business_agent.schemas import SafetyDeps
from app.modules.safety.business_agent.tools import subsidy_tools
from app.modules.safety.business_agent.tools.registry import (
    TOOL_KIND,
)
from app.modules.safety.business_agent.tools.subsidy_tools import (
    generate_guardian_subsidy,
    preview_guardian_subsidy,
)
from app.modules.safety.workticket_review.parser import FIELD_MAP

# ── 夹具：最小原始记录（client 输出结构 → parser 可解析）──────────────


def _raw_record(
    ticket_type: str,
    *,
    ticket_no: str,
    guardian: str,
    apply_unit: str,
    start_iso: str = "2026-08-01T08:00:00+08:00",
    end_iso: str = "2026-08-01T11:00:00+08:00",
) -> dict[str, Any]:
    """构造一条 client.list_tickets_for_date_range 返回的原始记录。

    variables 同时写原始键（时间）与 ``$fieldId`` 显示键（guardian/apply_unit），
    与平台 start-form-properties 实测结构一致（parser 优先取显示值）。
    """
    fm = FIELD_MAP.get(ticket_type, {})
    variables: dict[str, Any] = {}
    for name, iso in (("start_time", start_iso), ("end_time", end_iso)):
        fid = fm.get(name)
        if fid:
            variables[fid] = iso
    for name, value in (("guardian", guardian), ("apply_unit", apply_unit)):
        fid = fm.get(name)
        if fid:
            variables[f"${fid}"] = value
    return {
        "type": ticket_type,
        "processInstanceId": f"pid-{ticket_no}",
        "serialNumber": ticket_no,
        "createTime": start_iso,
        "variables": variables,
    }


# ── 夹具：Fake 平台 client（async with 协议）───────────────────────────


class _FakeClient:
    def __init__(
        self,
        records: list[dict[str, Any]] | None = None,
        *,
        raise_error: Exception | None = None,
    ) -> None:
        self._records = records or []
        self._raise_error = raise_error
        self.calls: list[tuple[Any, Any]] = []

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False

    async def list_tickets_for_date_range(
        self, start_date: Any, end_date: Any
    ) -> list[dict[str, Any]]:
        self.calls.append((start_date, end_date))
        if self._raise_error:
            raise self._raise_error
        return self._records


def _set_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    records: list[dict[str, Any]] | None = None,
    error: Exception | None = None,
) -> _FakeClient:
    fake = _FakeClient(records=records, raise_error=error)
    monkeypatch.setattr(subsidy_tools, "WorkTicketPlatformClient", lambda: fake)
    return fake


# ── 夹具：Fake DB session（build_certificate_map.execute(...).all()）─────


class _FakeResult:
    def __init__(self, rows: list[tuple[str, str]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[str, str]]:
        return self._rows


class _FakeSession:
    def __init__(self, rows: list[tuple[str, str]] | None = None) -> None:
        self._rows = rows or [
            ("张三", "guardian_a"),
            ("李四", "guardian_b"),
            ("王五", "guardian_b"),
        ]

    async def execute(self, statement: Any) -> _FakeResult:
        return _FakeResult(self._rows)


def _ctx(db: Any, *, chat_id: str | None = "oc_test") -> RunContext[SafetyDeps]:
    deps = SafetyDeps(
        db=db,
        person=None,
        role="safety_admin",
        session_id="",
        channel="feishu",
        chat_id=chat_id,
    )
    return RunContext(deps=deps, model=TestModel(), usage=RunUsage())


# ═══════════════════════════════════════════════════════════════════
# preview_guardian_subsidy
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_preview_returns_expected_structure(monkeypatch: pytest.MonkeyPatch) -> None:
    """预览：返回结构齐全，窗口为 8 月 → 7/8/9 月（±1 月）。"""
    records = [
        _raw_record("hot_work", ticket_no="DH-0801", guardian="张三", apply_unit="环保部"),
        _raw_record("confined_space", ticket_no="XK-0802", guardian="李四", apply_unit="环保部"),
        _raw_record("height_work", ticket_no="GC-0803", guardian="王五", apply_unit="环保部"),
    ]
    fake = _set_client(monkeypatch, records=records)

    result = await preview_guardian_subsidy(_ctx(_FakeSession()), "环保", 2026, 8)

    assert result["total_fetched"] == 3
    assert result["matched_records"] == 3
    assert result["matched_tickets"] == 3
    assert result["guardian_names"] == ["张三", "李四", "王五"]
    assert result["a_cert_count"] == 1
    assert result["b_cert_count"] == 2
    assert result["unmatched"] == []
    assert result["skipped"] == []
    assert "环保部" in result["departments"]
    assert result["need_department_selection"] is False
    assert result["hint"] is None
    assert "确认计算" in result["confirm_suggestion"]
    assert result["confirm_suggestion"].startswith("以上为「环保」2026年8月")
    assert result["stats"]["guardian_count"] == 3

    # 窗口：2026-07-01 ~ 2026-09-30
    start, end = fake.calls[0]
    assert (start.year, start.month, start.day) == (2026, 7, 1)
    assert (end.year, end.month, end.day) == (2026, 9, 30)


@pytest.mark.asyncio
async def test_preview_window_crosses_year_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    """1 月窗口跨年：2025-12-01 ~ 2026-02-28；12 月窗口：2026-11-01 ~ 2027-01-31。"""
    fake = _set_client(monkeypatch)

    await preview_guardian_subsidy(_ctx(_FakeSession()), "环保", 2026, 1)
    start, end = fake.calls[0]
    assert (start.year, start.month, start.day) == (2025, 12, 1)
    assert (end.year, end.month, end.day) == (2026, 2, 28)

    await preview_guardian_subsidy(_ctx(_FakeSession()), "环保", 2026, 12)
    start, end = fake.calls[1]
    assert (start.year, start.month, start.day) == (2026, 11, 1)
    assert (end.year, end.month, end.day) == (2027, 1, 31)


@pytest.mark.asyncio
async def test_preview_no_dept_match_returns_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    """部门关键词不命中 → matched=0 + 候选部门清单 + need_department_selection。"""
    records = [
        _raw_record("hot_work", ticket_no="DH-0901", guardian="张三", apply_unit="发酵工程部"),
    ]
    _set_client(monkeypatch, records=records)

    result = await preview_guardian_subsidy(_ctx(_FakeSession()), "环保", 2026, 8)

    assert result["matched_records"] == 0
    assert result["need_department_selection"] is True
    assert "发酵工程部" in result["departments"]
    assert "候选部门" in (result["hint"] or "")


@pytest.mark.asyncio
async def test_preview_empty_window_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    """窗口无票 → total_fetched=0 + 提示。"""
    _set_client(monkeypatch, records=[])

    result = await preview_guardian_subsidy(_ctx(_FakeSession()), "环保", 2026, 8)

    assert result["total_fetched"] == 0
    assert result["matched_records"] == 0
    assert "未拉到作业票" in (result["hint"] or "")


@pytest.mark.asyncio
async def test_preview_fetch_failure_degrades(monkeypatch: pytest.MonkeyPatch) -> None:
    """平台拉取失败 → platform_fetch_error；凭据类错误 → auth_failed。"""
    _set_client(monkeypatch, error=RuntimeError("平台接口调用失败 GET ... HTTP 500"))
    result = await preview_guardian_subsidy(_ctx(_FakeSession()), "环保", 2026, 8)
    assert result["error_type"] == "platform_fetch_error"
    assert "平台拉取失败" in result["error"]

    _set_client(monkeypatch, error=RuntimeError("平台敏感凭据未配置"))
    result = await preview_guardian_subsidy(_ctx(_FakeSession()), "环保", 2026, 8)
    assert result["error_type"] == "auth_failed"
    assert "凭据" in result["error"]


@pytest.mark.asyncio
async def test_preview_invalid_params() -> None:
    """非法年月/空部门 → invalid_params，不拉取。"""
    result = await preview_guardian_subsidy(_ctx(_FakeSession()), "环保", 2026, 13)
    assert result["error_type"] == "invalid_params"

    result = await preview_guardian_subsidy(_ctx(_FakeSession()), "", 2026, 8)
    assert result["error_type"] == "invalid_params"
    assert "部门关键词" in result["error"]


# ═══════════════════════════════════════════════════════════════════
# generate_guardian_subsidy
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_generate_sends_file_and_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    """生成 → 发送成功：summary（票数/人数/金额/待核对）+ send_file_to_chat 收到 chat_id。"""
    records = [
        _raw_record("hot_work", ticket_no="DH-0801", guardian="张三", apply_unit="环保部"),
        _raw_record("confined_space", ticket_no="XK-0802", guardian="李四", apply_unit="环保部"),
    ]
    _set_client(monkeypatch, records=records)

    sent: list[tuple[str, bytes, str]] = []

    async def fake_send(chat_id: str, file_bytes: bytes, file_name: str) -> bool:
        sent.append((chat_id, file_bytes, file_name))
        return True

    monkeypatch.setattr(subsidy_tools, "send_file_to_chat", fake_send)

    result = await generate_guardian_subsidy(_ctx(_FakeSession()), "环保", 2026, 8)

    assert result["sent"] is True
    assert result["file_name"].endswith(".xlsx")
    assert "环保部 2026年8月" in result["file_name"]
    assert result["summary"]["matched_count"] == 2
    assert result["summary"]["guardian_count"] == 2
    # P-1/S-1：摘要金额 = B 证按 0.5 系数折算后实发合计（受限空间 B 证 60×0.5=30；
    # 动火 A 证无 level 费率为 0）——与 Excel K 列口径一致
    assert result["summary"]["total_amount"] == 30.0
    assert "折算后实发合计" in result["message"]
    assert result["summary"]["unmatched_count"] == 0
    assert result["summary"]["skipped_count"] == 0
    assert "待核对" in result["message"] or "总金额" in result["message"]

    assert len(sent) == 1
    chat_id, file_bytes, file_name = sent[0]
    assert chat_id == "oc_test"
    assert len(file_bytes) > 0
    assert file_name.endswith(".xlsx")


@pytest.mark.asyncio
async def test_generate_custom_filename(monkeypatch: pytest.MonkeyPatch) -> None:
    records = [
        _raw_record("hot_work", ticket_no="DH-0801", guardian="张三", apply_unit="环保部"),
    ]
    _set_client(monkeypatch, records=records)
    sent: list[tuple[str, bytes, str]] = []

    async def fake_send(chat_id: str, file_bytes: bytes, file_name: str) -> bool:
        sent.append((chat_id, file_bytes, file_name))
        return True

    monkeypatch.setattr(subsidy_tools, "send_file_to_chat", fake_send)

    result = await generate_guardian_subsidy(
        _ctx(_FakeSession()), "环保", 2026, 8, filename="环保部8月补贴"
    )

    assert result["sent"] is True
    # 无扩展名时自动补 .xlsx（按缺省逻辑）
    assert sent[0][2] == "环保部8月补贴.xlsx"


@pytest.mark.asyncio
async def test_generate_chat_id_none_degrades(monkeypatch: pytest.MonkeyPatch) -> None:
    """chat_id=None（web 渠道）→ 降级提示 + base64 兜底，不调发送。"""
    records = [
        _raw_record("hot_work", ticket_no="DH-0801", guardian="张三", apply_unit="环保部"),
    ]
    _set_client(monkeypatch, records=records)
    called: list[Any] = []

    async def fake_send(*args: Any, **kwargs: Any) -> bool:
        called.append((args, kwargs))
        return True

    monkeypatch.setattr(subsidy_tools, "send_file_to_chat", fake_send)

    result = await generate_guardian_subsidy(_ctx(_FakeSession(), chat_id=None), "环保", 2026, 8)

    assert result["sent"] is False
    assert result["degraded"] is True
    assert "当前渠道无法回传文件" in result["message"]
    assert "飞书会话" in result["message"]
    assert result["file_content_base64"]
    assert called == []  # 未调用发送


@pytest.mark.asyncio
async def test_generate_send_failure_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """发送失败 → sent=False + 兜底 base64 + 提示重试。"""
    records = [
        _raw_record("hot_work", ticket_no="DH-0801", guardian="张三", apply_unit="环保部"),
    ]
    _set_client(monkeypatch, records=records)

    async def fake_send(chat_id: str, file_bytes: bytes, file_name: str) -> bool:
        return False

    monkeypatch.setattr(subsidy_tools, "send_file_to_chat", fake_send)

    result = await generate_guardian_subsidy(_ctx(_FakeSession()), "环保", 2026, 8)

    assert result["sent"] is False
    assert "发送失败" in result["message"]
    assert result["file_content_base64"]
    assert "summary" in result


@pytest.mark.asyncio
async def test_generate_no_matched_records_degrades(monkeypatch: pytest.MonkeyPatch) -> None:
    """有票但部门不命中 → no_matched_records + 候选部门，不生成文件。"""
    records = [
        _raw_record("hot_work", ticket_no="DH-0901", guardian="张三", apply_unit="发酵工程部"),
    ]
    _set_client(monkeypatch, records=records)

    result = await generate_guardian_subsidy(_ctx(_FakeSession()), "环保", 2026, 8)

    assert result["error_type"] == "no_matched_records"
    assert "发酵工程部" in result["departments"]


# ═══════════════════════════════════════════════════════════════════
# registry / permissions / executor 接线
# ═══════════════════════════════════════════════════════════════════


def test_registry_kind_and_func_lists() -> None:
    """TOOL_KIND 分类 + read/write 注册表接线。"""
    assert TOOL_KIND["preview_guardian_subsidy"] is False
    assert TOOL_KIND["generate_guardian_subsidy"] is True

    from app.modules.safety.business_agent.tools.registry import (
        _all_read_funcs,
        _all_write_funcs,
    )

    assert "preview_guardian_subsidy" in {f.__name__ for f in _all_read_funcs()}
    assert "generate_guardian_subsidy" in {f.__name__ for f in _all_write_funcs()}
    # 旧工具已从注册表移除
    assert "export_subsidy_report" not in {f.__name__ for f in _all_write_funcs()}
    assert "import_subsidy_records" not in {f.__name__ for f in _all_read_funcs()}


def test_permissions_role_policy() -> None:
    """监护补贴工具：safety_admin / dept_leader 可调；inspector / viewer 拒绝。"""
    assert core_permissions.check("safety_admin", TOOL_PREVIEW_GUARDIAN_SUBSIDY)
    assert core_permissions.check("safety_admin", TOOL_GENERATE_GUARDIAN_SUBSIDY)
    assert core_permissions.check("dept_leader", TOOL_PREVIEW_GUARDIAN_SUBSIDY)
    assert core_permissions.check("dept_leader", TOOL_GENERATE_GUARDIAN_SUBSIDY)
    assert not core_permissions.check("inspector", TOOL_GENERATE_GUARDIAN_SUBSIDY)
    assert not core_permissions.check("viewer", TOOL_PREVIEW_GUARDIAN_SUBSIDY)
    assert not core_permissions.check(None, TOOL_PREVIEW_GUARDIAN_SUBSIDY)


def test_registry_constants_match_permissions() -> None:
    """registry TOOL_KIND 键与 permissions 常量名一致（防拼写漂移）。"""
    assert TOOL_KIND[TOOL_PREVIEW_GUARDIAN_SUBSIDY] is False
    assert TOOL_KIND[TOOL_GENERATE_GUARDIAN_SUBSIDY] is True


def test_executor_summary_branch() -> None:
    """确认卡摘要：新工具分支覆盖部门/月份；旧 export_subsidy_report 分支已移除。"""
    text = executor._format_tool_summary(
        "generate_guardian_subsidy",
        {"dept_keyword": "环保", "year": 2026, "month": 8, "filename": None},
    )
    assert "环保" in text
    assert "2026年8月" in text
    assert "平台" in text

    # 旧工具名不再有专门分支 → 走通用摘要
    generic = executor._format_tool_summary("export_subsidy_report", {})
    assert "将在" in generic
    # 旧格式化函数已删除
    assert not hasattr(executor, "_format_subsidy_export_summary")
