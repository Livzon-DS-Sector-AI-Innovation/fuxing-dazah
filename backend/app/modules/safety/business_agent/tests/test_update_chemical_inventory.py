"""update_chemical_inventory 写工具单测（零真机：fake office client + fake store）。

覆盖：锚点定位单行写入（含单位后缀保留/缓存失效/写地址冒号）、多行消歧拒绝、
无匹配、源开关关闭拒绝、与现值一致跳过、权限矩阵与 chemical 域路由挂载。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.safety.business_agent.tools.write_tools import (
    update_chemical_inventory,
)
from app.modules.safety.feishu.office_client._base import OfficeResult

TOKEN = "H0YWsAf52hBAIDtmJlxcqThZn2c"

def _base_sheets() -> dict[str, list[list[Any]]]:
    """精简两张子表：危废库版式（缺一昼夜使用量）；环保中心版式（首行表头+g 后缀）。
    每测试独立深拷贝（multi_match 用例会追加行，防随机顺序下状态泄漏）。"""
    return {
        "H8wjnP": [
            ["序号", "存放部位", "危险品名称", "规格", "管理类别", "当前数量/kg", "库存上限/kg", "危险性"],
            [1, "危库二", "米尔贝水层废液", "20%", "危废库地面", 1400, 20000, "易燃易爆"],
            [2, "危库二", "乙酸乙酯废液", "80%", "危废库地面", 4900, 20000, "易燃易爆"],
        ],
        "GgfZuX": [
            ["序号", "存放部位", "危险品名称", "规格", "管理类别", "当前数量", "库存上限", "危险性"],
            [1, "二楼化验室", "氢氧化钠", "500g/瓶", "试剂柜", "3000g", "7000g", "具有强腐蚀性，易制毒"],
        ],
    }


class FakeOfficeClient:
    """read_sheet_metainfo / read_sheet / write_sheet 三方法替身（记录写调用）。"""

    def __init__(self) -> None:
        self.writes: list[tuple[str, Any]] = []
        self.sheets = _base_sheets()
        self.row_counts = {"H8wjnP": 3, "GgfZuX": 2}  # 行数=表头+数据行（读取窗口按此）

    async def read_sheet_metainfo(self, spreadsheet_token: str) -> OfficeResult:
        return OfficeResult.data({
            "revision": 1759,
            "sheets": [
                {"sheetId": "H8wjnP", "title": "危废库",
                 "rowCount": self.row_counts["H8wjnP"], "columnCount": 8},
                {"sheetId": "GgfZuX", "title": "环保工程中心",
                 "rowCount": self.row_counts["GgfZuX"], "columnCount": 8},
            ],
        })

    async def read_sheet(
        self, spreadsheet_token: str, sheet_range: str,
        *, max_rows: int = 500, max_cols: int = 50,
    ) -> OfficeResult:
        sid = sheet_range.split("!")[0]
        return OfficeResult.data(self.sheets[sid])

    async def write_sheet(
        self, spreadsheet_token: str, sheet_range: str, values: list[list[Any]],
    ) -> OfficeResult:
        self.writes.append((sheet_range, values))
        # 写后回读可见（模拟落库）
        sid, addr = sheet_range.split("!")
        col = ord(addr[0]) - 65  # A=0
        row = int(addr.split(":")[0][1:])
        rows = self.sheets[sid]
        if len(rows) < row:
            rows.extend([[] for _ in range(row - len(rows))])
        while len(rows[row - 1]) <= col:
            rows[row - 1].append(None)
        rows[row - 1][col] = values[0][0]
        return OfficeResult.link("u", file_token=TOKEN, message="ok")


_INVALIDATED: list[bool] = []


def _seed(
    monkeypatch: pytest.MonkeyPatch, *, source_on: bool = True,
) -> FakeOfficeClient:
    monkeypatch.setenv(
        "SAFETY_CHEMICAL_INVENTORY_SOURCE", "sheet" if source_on else "bitable",
    )
    conn = SimpleNamespace(app_token=TOKEN, enabled=True)
    monkeypatch.setattr(
        "app.modules.safety.bitable_config.store.store.get_connection",
        lambda domain, kind: conn,
    )
    client = FakeOfficeClient()
    monkeypatch.setattr(
        "app.modules.safety.feishu.office_client.build_office_client",
        lambda: client,
    )
    _INVALIDATED.clear()
    monkeypatch.setattr(
        "app.modules.safety.service.chemical_inventory_direct.reader.invalidate_shared_reader",
        lambda: _INVALIDATED.append(True),
    )
    return client


def _ctx(
    *, role: str | None = None, department: str | None = None,
) -> SimpleNamespace:
    person = SimpleNamespace(department=department) if department is not None else None
    return SimpleNamespace(deps=SimpleNamespace(db=None, role=role, person=person))


class TestUpdateChemicalInventory:
    async def test_single_row_write_with_cache_invalidation(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """单行命中：写当前数量（写地址带冒号）+ 缓存失效 + 前后值回报。"""
        client = _seed(monkeypatch)
        result = await update_chemical_inventory(
            _ctx(role='creator'), department="危废库", material_name="乙酸乙酯废液", quantity=5200,
        )
        assert result["ok"] is True
        assert result["record_id"] == "H8wjnP:3"
        assert client.writes == [("H8wjnP!F3:F3", [[5200]])]
        assert result["changed"][0]["before"] == "4900"
        assert result["changed"][0]["after"] == "5200"
        assert _INVALIDATED == [True]

    async def test_unit_suffix_preserved(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """g 后缀行：写回保留 '5200g' 形态（不裸写数字）。"""
        client = _seed(monkeypatch)
        result = await update_chemical_inventory(
            _ctx(role='creator'), department="环保工程中心", material_name="氢氧化钠", quantity=5200,
        )
        assert result["ok"] is True
        assert client.writes == [("GgfZuX!F2:F2", [["5200g"]])]
        assert result["changed"][0]["after"] == "5200g"

    async def test_department_accepts_slug(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """部门入参用英文 slug（weifeiku）同样命中。"""
        _seed(monkeypatch)
        result = await update_chemical_inventory(
            _ctx(role='creator'), department="weifeiku", material_name="乙酸乙酯废液", quantity=1,
        )
        assert result["ok"] is True

    async def test_multi_match_requires_location(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """同子表同物料多行（部位不同）：拒绝并列出候选要求消歧。"""
        client = _seed(monkeypatch)
        client.sheets["H8wjnP"].append(
            [3, "危库三", "乙酸乙酯废液", "80%", "危废库地面", 100, 20000, "易燃易爆"],
        )
        client.row_counts["H8wjnP"] = 4
        result = await update_chemical_inventory(
            _ctx(role='creator'), department="危废库", material_name="乙酸乙酯废液", quantity=1,
        )
        assert result["ok"] is False
        assert "消歧" in result["error"]
        assert len(result["matches"]) == 2
        # 部位消歧后单行命中
        result2 = await update_chemical_inventory(
            _ctx(role='creator'), department="危废库", material_name="乙酸乙酯废液",
            quantity=1, storage_location="危库三",
        )
        assert result2["ok"] is True
        assert result2["record_id"] == "H8wjnP:4"

    async def test_no_match(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _seed(monkeypatch)
        result = await update_chemical_inventory(
            _ctx(role='creator'), department="危废库", material_name="不存在的物料", quantity=1,
        )
        assert result["ok"] is False
        assert "未找到" in result["error"]

    async def test_source_off_refused(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _seed(monkeypatch, source_on=False)
        result = await update_chemical_inventory(
            _ctx(role='creator'), department="危废库", material_name="乙酸乙酯废液", quantity=1,
        )
        assert result["ok"] is False
        assert "未启用" in result["error"]

    async def test_same_value_skips_write(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client = _seed(monkeypatch)
        result = await update_chemical_inventory(
            _ctx(role='creator'), department="危废库", material_name="乙酸乙酯废液", quantity=4900,
        )
        assert result["ok"] is True
        assert result["changed"] == []
        assert client.writes == []

    async def test_missing_column_rejected(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """危废库无「一昼夜使用量」列：明确拒绝而非误写他列。"""
        _seed(monkeypatch)
        result = await update_chemical_inventory(
            _ctx(role='creator'), department="危废库", material_name="乙酸乙酯废液", daily_usage=5,
        )
        assert result["ok"] is False
        assert "没有该列" in result["error"]


class TestWiring:
    def test_permissions_matrix(self) -> None:
        """查询全员开放；写入工具全员可见（部门限制在工具内强制，创建者放行；旧角色值走别名兜底）。"""
        from app.modules.safety.business_agent.core.permissions import check

        for role in ("creator", "manager", "viewer", "safety_admin", "dept_leader", "inspector"):
            assert check(role, "update_chemical_inventory") is True
            assert check(role, "query_chemical_inventory") is True
        assert check(None, "update_chemical_inventory") is False
        assert check(None, "query_chemical_inventory") is False

    def test_tool_kind_and_routing(self) -> None:
        from app.modules.safety.business_agent.tool_selector import route_message
        from app.modules.safety.business_agent.tools.registry import TOOL_KIND

        assert TOOL_KIND["update_chemical_inventory"] is True  # 写→确认流
        tools = route_message("帮我更新危化品库存").tool_names
        assert "update_chemical_inventory" in tools
        assert "query_chemical_inventory" in tools


class TestDepartmentScope:
    """写入部门准入：管理员不限；其余角色仅限本部门（子表名或行内车间归属）。"""

    async def test_admin_bypasses_department_check(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _seed(monkeypatch)
        result = await update_chemical_inventory(
            _ctx(role="creator"), department="危废库",
            material_name="乙酸乙酯废液", quantity=5000,
        )
        assert result["ok"] is True

    async def test_functional_dept_matches_sheet_title(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """功能部门（子表名=部门）：本部门子表放行。"""
        client = _seed(monkeypatch)
        client.sheets["H8wjnP"][0][1] = "存放部位"  # 标题行仍匹配部门规则走标题
        result = await update_chemical_inventory(
            _ctx(role="viewer", department="危废库"),
            department="危废库", material_name="乙酸乙酯废液", quantity=5000,
        )
        assert result["ok"] is True
        assert client.writes == [("H8wjnP!F3:F3", [[5000]])]

    async def test_other_department_refused(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """非本部门子表：拒绝并点明部门不匹配。"""
        client = _seed(monkeypatch)
        result = await update_chemical_inventory(
            _ctx(role="viewer", department="发酵一部"),
            department="危废库", material_name="乙酸乙酯废液", quantity=5000,
        )
        assert result["ok"] is False
        assert "仅限本部门" in result["error"]
        assert client.writes == []

    async def test_workshop_scope_by_storage_location(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """产品线子表按行内车间归属：车间二人员只能改部位含「车间二」的行。"""
        client = _seed(monkeypatch)
        client.sheets["H8wjnP"] = [
            ["序号", "存放部位", "危险品名称", "规格", "管理类别", "当前数量/kg", "库存上限/kg", "危险性"],
            [1, "车间二提取岗位", "乙醇", "1", "车间储罐", 90000, 150000, "易燃易爆"],
            [2, "车间一纯化岗位", "乙腈", "1", "车间储罐", 800, 5000, "易燃易爆"],
        ]
        client.sheets["GgfZuX"] = [
            ["序号", "存放部位", "危险品名称", "规格", "管理类别", "当前数量", "库存上限", "危险性"],
        ]
        # 同物料跨车间两行：车间二人员 → 只留车间二行（唯一命中可直接写）
        result = await update_chemical_inventory(
            _ctx(role="manager", department="车间二"),
            department="危废库", material_name="乙醇", quantity=95000,
        )
        assert result["ok"] is True
        assert result["record_id"] == "H8wjnP:2"
        # 车间一人员改乙醇 → 命中行被部门规则滤空 → 拒绝
        result2 = await update_chemical_inventory(
            _ctx(role="manager", department="车间一"),
            department="危废库", material_name="乙醇", quantity=1,
        )
        assert result2["ok"] is False
        assert "仅限本部门" in result2["error"]

    async def test_person_without_department_refused(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """人员信息无部门：非管理员拒绝（deny-by-default）。"""
        _seed(monkeypatch)
        result = await update_chemical_inventory(
            _ctx(role="viewer"), department="危废库",
            material_name="乙酸乙酯废液", quantity=5000,
        )
        assert result["ok"] is False
        assert "部门" in result["error"]
