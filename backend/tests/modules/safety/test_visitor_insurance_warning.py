"""外来人员保险到期预警口径与格子组装单测（纯函数，零网络零 IO）。

固化 2026-10-14 与需求方确认的口径：
- 已通过 + 在厂（进厂结束 ≥ 今日）才算；已离厂不预警；
- 🔴 已过期 / 🟡 3天内到期（含边界日）/ ⚪ 在厂未填保险有效期；
- 重复申请单合并（单位+人员+窗口+作业一致）；无预警日照发格子。
"""

from __future__ import annotations

from datetime import date

from app.modules.safety.service.visitor_insurance import warning
from app.modules.safety.service.visitor_insurance.reader import VisitorNoticeView
from app.modules.safety.service.visitor_insurance.report import build_cell, build_detail

TODAY = date(2026, 10, 14)  # 周三


def _view(
    *,
    company: str = "测试单位",
    names: str = "张三、李四",
    people: int = 2,
    content: str = "空调维修",
    scope: str = "",
    status: str = "已通过",
    entry_start: date | None = date(2026, 9, 1),
    entry_end: date | None = date(2026, 12, 31),
    insurance_end: date | None = None,
    record_id: str = "rec",
) -> VisitorNoticeView:
    return VisitorNoticeView(
        record_id=record_id,
        company=company,
        names=names,
        people_count=people,
        work_content=content,
        work_scope=scope,
        status=status,
        entry_start=entry_start,
        entry_end=entry_end,
        insurance_end=insurance_end,
    )


class TestClassify:
    def test_expired_soon_missing_three_buckets(self):
        result = warning.classify([
            _view(insurance_end=date(2026, 10, 10), company="甲单位"),      # 过期 4 天
            _view(insurance_end=date(2026, 10, 16), company="乙单位"),      # 剩 2 天
            _view(insurance_end=None, company="丙单位"),                    # 未填
            _view(insurance_end=date(2026, 10, 25), company="丁单位"),      # 不预警
        ], TODAY)
        assert [g.company for g in result.expired] == ["甲单位"]
        assert result.expired[0].days_left == -4
        assert [g.company for g in result.soon] == ["乙单位"]
        assert result.soon[0].days_left == 2
        assert [g.company for g in result.missing] == ["丙单位"]
        assert result.total_notices == 4
        assert result.active_notices == 4

    def test_boundary_days_inclusive(self):
        # 今日到期（剩 0 天）与 今日+3 到期都算临期；+4 不算
        result = warning.classify([
            _view(insurance_end=TODAY, company="今日到期"),
            _view(insurance_end=date(2026, 10, 17), company="三日到期"),
            _view(insurance_end=date(2026, 10, 18), company="四日到期"),
        ], TODAY)
        assert {g.company for g in result.soon} == {"今日到期", "三日到期"}

    def test_left_site_excluded_even_if_expired(self):
        result = warning.classify([
            _view(insurance_end=date(2026, 10, 1), entry_end=date(2026, 10, 13)),
        ], TODAY)
        assert not result.expired and not result.soon and not result.missing
        assert result.active_notices == 0  # 已离厂不进在厂口径

    def test_entry_end_today_counts_as_on_site(self):
        # 进厂结束=今日：当天仍算在厂（≥ 今日含边界）
        result = warning.classify([
            _view(insurance_end=date(2026, 10, 10), entry_end=TODAY),
        ], TODAY)
        assert len(result.expired) == 1

    def test_missing_entry_end_treated_as_on_site(self):
        result = warning.classify([
            _view(insurance_end=None, entry_end=None),
        ], TODAY)
        assert len(result.missing) == 1

    def test_non_approved_excluded(self):
        result = warning.classify([
            _view(insurance_end=date(2026, 10, 10), status="审批中"),
        ], TODAY)
        assert result.total_notices == 0

    def test_duplicate_notices_merged(self):
        # 同单位同批人同窗口的重复申请单：合并为一条，人不重复计
        rows = [
            _view(names="向达杰、郑炎灿", people=5, record_id="r1",
                  insurance_end=None),
            _view(names="向达杰，郑炎灿", people=5, record_id="r2",
                  insurance_end=None),  # 分隔符不同但人员一致
        ]
        result = warning.classify(rows, TODAY)
        assert len(result.missing) == 1
        assert result.missing[0].notices == 1  # 合并后计 1 条
        assert result.missing[0].people == 5

    def test_same_company_different_batches_not_merged(self):
        result = warning.classify([
            _view(names="向达杰、郑炎灿", people=5, insurance_end=None),
            _view(names="吴良凤、陈林", people=8, insurance_end=None),
        ], TODAY)
        assert len(result.missing) == 1  # 同单位聚合为一组
        assert result.missing[0].notices == 2  # 但报备条数分开计
        assert result.missing[0].people == 13

    def test_expired_sorted_most_overdue_first(self):
        result = warning.classify([
            _view(insurance_end=date(2026, 10, 12), company="过期2天"),
            _view(insurance_end=date(2026, 10, 8), company="过期6天"),
        ], TODAY)
        assert [g.company for g in result.expired] == ["过期6天", "过期2天"]

    def test_soon_sorted_by_expiry_date(self):
        result = warning.classify([
            _view(insurance_end=date(2026, 10, 17), company="后"),
            _view(insurance_end=date(2026, 10, 15), company="先"),
        ], TODAY)
        assert [g.company for g in result.soon] == ["先", "后"]

    def test_people_fallback_to_named_count(self):
        # 预计人数缺失时按姓名清单兜底
        result = warning.classify([
            _view(names="张三、李四、王五", people=0, insurance_end=None),
        ], TODAY)
        assert result.missing[0].people == 3

    def test_normalize_names_messy_separators(self):
        assert warning.normalize_names("胡四海。林梦霞，陈德兰；郑光伟  沈月姣") == (
            "胡四海、林梦霞、陈德兰、郑光伟、沈月姣"
        )


class TestCell:
    def _result(self, **kw) -> warning.WarningResult:
        return warning.classify([_view(**kw)], TODAY)

    def test_cell_all_clear_still_emits(self):
        cell = build_cell(warning.classify([], TODAY))
        assert cell.tag_color == "green"
        assert "已过期 **0**" in cell.stats
        assert "今日无外来人员保险到期预警" in cell.zone
        assert "今日无" in cell.detail  # 无预警日也照发（口径可见）

    def test_cell_red_when_expired(self):
        cell = build_cell(self._result(insurance_end=date(2026, 10, 10)))
        assert cell.tag_color == "red"
        assert "2026-10-10 过期 **4 天**" in cell.detail
        assert "暂停相关单位人员进厂作业" in cell.detail

    def test_detail_next_expiry_on_empty_soon(self):
        # 无临期时给出在厂报备中最近的真实到期日（空日也有信息量）
        result = warning.classify([
            _view(insurance_end=date(2026, 10, 25), company="远期单位"),
        ], TODAY)
        detail = build_detail(result)
        assert "在厂报备最近到期：远期单位 2026-10-25（剩 11 天）" in detail

    def test_cell_orange_when_only_soon(self):
        cell = build_cell(self._result(insurance_end=date(2026, 10, 16)))
        assert cell.tag_color == "orange"
        assert "剩 **2 天**" in cell.detail

    def test_cell_blue_when_only_missing(self):
        cell = build_cell(self._result(insurance_end=None))
        assert cell.tag_color == "blue"
        assert "未填保险最大单位" in cell.zone
        assert "催收保险凭证" in cell.detail

    def test_detail_missing_grouped_by_company(self):
        result = warning.classify([
            _view(company="甲公司", names="张三", people=1, insurance_end=None),
            _view(company="甲公司", names="李四", people=1, insurance_end=None,
                  content="绿化修剪"),
            _view(company="乙公司", names="王五、赵六", people=2, insurance_end=None),
        ], TODAY)
        detail = build_detail(result)
        # 甲公司两条报备聚合成一行；乙公司人数多排前面（人数倒序）
        assert detail.index("乙公司") < detail.index("甲公司")
        assert "甲公司**：2 条报备｜2 人" in detail
        assert "共扫描 3 条报备" in detail
