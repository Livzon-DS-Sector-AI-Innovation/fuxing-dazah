"""SubsidyService.export_excel 向后兼容扩展 — 第二页「待核对/跳过说明」。

轻断言（对应 backend-design 6.2 / ticket 04）：
- review_notes 缺省 / 空 → 仅主表单页，主表列头不变（向后兼容）；
- review_notes 非空 → 主表 + 「待核对/跳过说明」两个 sheet，且内容包括
  未匹配监护人姓名（涉及票数）与跳过票号/原因。
openpyxl 能打开返回字节即等价验证了「模板输出可读」。
"""

from __future__ import annotations

import io

from openpyxl import load_workbook

from app.modules.safety.schemas.subsidy import SubsidyRecordInput
from app.modules.safety.service.subsidy import SubsidyService, b_cert_adjusted_total
from app.modules.safety.service.subsidy_plan import (
    ReviewNotes,
    SkippedTicket,
    UnmatchedGuardian,
)

MAIN_SHEET_HEADERS = [
    "序号", "监护人", "监护人级别", "作业地点+作业内容",
    "特殊作业类型", "作业级别", "作业票号", "开始时间", "结束时间",
    "作业间隔时间(h)", "补贴标准", "应发补贴",
]


def _calc_result():
    record = SubsidyRecordInput(
        guardian_name="张三",
        guardian_level="A证",
        operation_type="动火作业",
        operation_level="二级",
        location_content="车间一楼 动火焊接",
        start_time="2026-08-01T08:00:00+08:00",
        end_time="2026-08-01T11:00:00+08:00",
        interval_hours="0",
    )
    return SubsidyService.calculate([record], year=2026, month=8)


def _export(review_notes: ReviewNotes | None = None) -> bytes:
    result = _calc_result()
    return SubsidyService.export_excel(
        result.details,
        result.summaries,
        "监护补贴统计",
        "环保部",
        review_notes=review_notes,
    )


# ── 6.2 用例 1: 缺省 review_notes → 仅主表（向后兼容） ──

def test_export_excel_no_review_notes_single_sheet() -> None:
    wb = load_workbook(io.BytesIO(_export()))

    assert wb.sheetnames == ["监护补贴统计"]
    ws = wb["监护补贴统计"]
    headers = [ws.cell(row=2, column=c).value for c in range(1, 13)]
    assert headers == MAIN_SHEET_HEADERS
    assert ws["A1"].value == "监护补贴统计"


# ── 6.2 用例 2: 空 ReviewNotes（无内容）→ 同样单页 ──

def test_export_excel_empty_review_notes_single_sheet() -> None:
    wb = load_workbook(io.BytesIO(_export(ReviewNotes())))

    assert wb.sheetnames == ["监护补贴统计"]


# ── 6.2 用例 3: 有 notes → 两个 sheet，内容含未匹配人名 / 跳过原因 ──

def test_export_excel_with_review_notes_two_sheets() -> None:
    notes = ReviewNotes(
        unmatched=[
            UnmatchedGuardian(name="王某某", ticket_count=3, operation_types=["动火作业", "受限空间"]),
        ],
        skipped=[
            SkippedTicket(ticket_no="DH-2026-0801", ticket_type="动火作业", reason="无监护人"),
        ],
    )
    wb = load_workbook(io.BytesIO(_export(notes)))

    assert wb.sheetnames == ["监护补贴统计", "待核对-跳过说明"]
    ws = wb["待核对-跳过说明"]
    texts = [str(c) for row in ws.iter_rows(values_only=True) for c in row if c is not None]
    assert any("王某某" in t for t in texts)
    assert any("涉及 3 张票" in t for t in texts)
    assert any("未匹配到A/B证" in t for t in texts)
    assert any("DH-2026-0801" in t for t in texts)
    assert any("无监护人" in t for t in texts)
    # 主表保留在第一位且列头不变
    main = wb["监护补贴统计"]
    assert [main.cell(row=2, column=c).value for c in range(1, 13)] == MAIN_SHEET_HEADERS


# ── 6.2 用例 4: 第二页分区 + 行内容（未匹配：姓名+票数+金额占位；跳过：票号+类型+原因） ──

def test_export_excel_review_sheet_sections() -> None:
    notes = ReviewNotes(
        unmatched=[
            UnmatchedGuardian(name="李雷", ticket_count=2, operation_types=["受限空间"]),
        ],
        skipped=[
            SkippedTicket(ticket_no="CONF-001", ticket_type="受限空间", reason="缺少开始时间"),
            SkippedTicket(ticket_no="HT-002", ticket_type="登高作业", reason="无监护人"),
        ],
    )
    ws = load_workbook(io.BytesIO(_export(notes)))["待核对-跳过说明"]

    texts = [str(c) for row in ws.iter_rows(values_only=True) for c in row if c is not None]
    assert any("证书未匹配监护人" in t for t in texts)
    assert any("跳过票" in t for t in texts)

    rows_by_key = {
        row[0]: row for row in ws.iter_rows(values_only=True) if row[0] in ("未匹配", "跳过")
    }
    unmatched_row = rows_by_key["未匹配"]
    assert unmatched_row[1] == "李雷"
    assert "涉及 2 张票" in str(unmatched_row[2])
    assert "受限空间" in str(unmatched_row[2])
    assert unmatched_row[3] == 0  # 金额占位恒 0（不计入补贴）

    skipped_rows = [row for row in ws.iter_rows(values_only=True) if row[0] == "跳过"]
    by_ticket = {row[1]: row for row in skipped_rows}
    assert "CONF-001" in by_ticket and "HT-002" in by_ticket
    assert "受限空间" in str(by_ticket["CONF-001"][2])
    assert "缺少开始时间" in str(by_ticket["CONF-001"][2])
    assert "登高作业" in str(by_ticket["HT-002"][2])
    assert "无监护人" in str(by_ticket["HT-002"][2])
    assert all(row[3] == 0 for row in skipped_rows)


# ── P-1 回归: B 证详情不被就地修改 / 不重复打折 ──

def test_export_excel_b_cert_no_double_discount() -> None:
    """B 证记录 export 两次金额一致：model_copy 防副作用 + 防重复打折。"""
    record = SubsidyRecordInput(
        guardian_name="李四",
        guardian_level="B证",
        operation_type="临时用电",
        operation_level="",
        location_content="配电房 临时接电",
        start_time="2026-08-05T08:00:00+08:00",
        end_time="2026-08-05T11:00:00+08:00",
        interval_hours="0",
    )
    result = SubsidyService.calculate([record], year=2026, month=8)
    original = result.details[0].subsidy_amount  # B 证系数前 = 15.0

    wb1 = load_workbook(io.BytesIO(SubsidyService.export_excel(
        result.details, result.summaries, "监护补贴统计", "环保部", b_cert_rate=0.5)))
    wb2 = load_workbook(io.BytesIO(SubsidyService.export_excel(
        result.details, result.summaries, "监护补贴统计", "环保部", b_cert_rate=0.5)))

    # 入参 details 不被就地修改 → 第二次导出金额与第一次一致（无重复打折）
    assert result.details[0].subsidy_amount == original
    k1 = wb1["监护补贴统计"]["L3"].value
    k2 = wb2["监护补贴统计"]["L3"].value
    assert k1 == k2 == round(original * 0.5)  # 15.0 → 7.5 → 组内取整 8

    # 摘要口径：B 证折算后实发合计 == Excel L 列合计（P-1/S-1）
    assert b_cert_adjusted_total(result.details, b_cert_rate=0.5) == k1


def test_export_excel_adjusted_total_matches_k_column() -> None:
    """A/B 证混合：摘要折算合计与 K 列（按监护人合并取整）口径一致。"""
    records = [
        SubsidyRecordInput(
            guardian_name="张三", guardian_level="A证", operation_type="受限空间",
            operation_level="", location_content="污水池 清罐",
            start_time="2026-08-02T08:00:00+08:00",
            end_time="2026-08-02T11:00:00+08:00", interval_hours="0",
        ),
        SubsidyRecordInput(
            guardian_name="李四", guardian_level="B证", operation_type="受限空间",
            operation_level="", location_content="污水池 清罐",
            start_time="2026-08-03T08:00:00+08:00",
            end_time="2026-08-03T11:00:00+08:00", interval_hours="0",
        ),
    ]
    result = SubsidyService.calculate(records, year=2026, month=8)
    before = [d.subsidy_amount for d in result.details]

    wb = load_workbook(io.BytesIO(SubsidyService.export_excel(
        result.details, result.summaries, "监护补贴统计", "环保部", b_cert_rate=0.5)))
    ws = wb["监护补贴统计"]

    # L 列：张三 60（A 证不折）；李四 60×0.5=30 → 组内取整
    assert ws["L3"].value == 60
    assert ws["L4"].value == 30
    # 入参未被修改（A/B 均为系数前金额）
    assert [d.subsidy_amount for d in result.details] == before
    # 摘要折算合计 = 60 + 30（L 列合计）
    assert b_cert_adjusted_total(result.details, 0.5) == 90.0
