"""S0 ticket 04 验收：warehouse bitable 适配器（全 live，真实测试版 Base）。

全部打真实飞书 API（仓储应用凭证 + 测试版 Base 坐标，见 bitable_schema），
mock 无法复现写契约坑（单选字符串/字段名/错误码），因此不使用 mock 传输层——
仅 test_invalid_option_rejected_locally 用 monkeypatch 计数证明本地校验
未发起 HTTP。

数据纪律：所有 create 的记录 try/finally 必删（成品销售明细表，
客户=LIVE-TEST-清理用），测试结束 Base 无 LIVE-TEST 残留；同表串行避免
1254291 并发冲突。

偏差说明：7 张核心表快照中无 created_time(1001) 类型字段（最高只到
created_user 1003），readonly 拒写用 gmp_outbound「创建人」(1003) 与
material_receipt「应出报日期..」(formula 20) 验证，同属只读类型集合。

运行：cd "E:\\dazah(仓储)\\backend" &&
      DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/dazah_whdev"
      uv run pytest tests/modules/warehouse/test_live_bitable_adapter.py -v
"""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.warehouse.bitable_adapter import WarehouseBitableAdapter
from app.modules.warehouse.bitable_schema import WarehouseBitableError

# 成品销售明细表（tblv2mhOHvZiepMa）测试字段：品名为单选（type 3），字符串写入
SALES_TEST_FIELDS: dict[str, Any] = {
    "品名": "硫酸黏菌素",
    "数量": 1,
    "客户": "LIVE-TEST-清理用",
}


async def _safe_delete(
    adapter: WarehouseBitableAdapter, table_key: str, record_id: str
) -> None:
    """尽力清理测试记录（已删/不存在则忽略）。"""
    try:
        await adapter.delete_record(table_key, record_id)
    except WarehouseBitableError as exc:
        print(f"[cleanup] 删除 {table_key}/{record_id} 失败: {exc}")


# ── 1. create → get → delete 往返 ──


async def test_create_get_delete_roundtrip() -> None:
    """sales_detail 写读删往返：get 回读品名一致，删除后再查应报错。"""
    adapter = WarehouseBitableAdapter()
    created = await adapter.create_record("sales_detail", dict(SALES_TEST_FIELDS))
    record_id = created["record_id"]
    assert record_id, f"create 应返回 record_id，实际 {created}"
    print(f"[create] record_id={record_id}")
    try:
        got = await adapter.get_record("sales_detail", record_id)
        name = got["fields"].get("品名")
        # 单选读取返回数组（读写不对称），兼容字符串形式
        name_list = name if isinstance(name, list) else [name]
        assert "硫酸黏菌素" in name_list, f"get 回读品名异常: {name!r}"
        print(f"[get] 品名={name!r} 客户={got['fields'].get('客户')!r}")
    finally:
        await _safe_delete(adapter, "sales_detail", record_id)

    with pytest.raises(WarehouseBitableError) as ei:
        await adapter.get_record("sales_detail", record_id)
    print(f"[get after delete] code={ei.value.code}（查不到，清理成功）")


# ── 2. 单选字符串写入契约 ──


async def test_select_string_write_accepted() -> None:
    """单选「品名」以纯字符串写入被接受（实测契约：数组写必 1254062）。"""
    adapter = WarehouseBitableAdapter()
    created = await adapter.create_record("sales_detail", dict(SALES_TEST_FIELDS))
    record_id = created["record_id"]
    assert record_id, f"字符串写单选应成功，实际 {created}"
    try:
        got = await adapter.get_record("sales_detail", record_id)
        name = got["fields"].get("品名")
        assert name in (["硫酸黏菌素"], "硫酸黏菌素"), (
            f"单选字符串写入后回读应为该选项，实际 {name!r}"
        )
        print(f"[select-string] 写入并回读成功: {name!r}")
    finally:
        await _safe_delete(adapter, "sales_detail", record_id)


# ── 3. 非法选项本地拦截（未发 HTTP） ──


async def test_invalid_option_rejected_locally(monkeypatch: pytest.MonkeyPatch) -> None:
    """「品名」传选项集外值 → create 前被校验拦截（1254062），零 HTTP。"""
    adapter = WarehouseBitableAdapter()
    counter = {"http": 0}

    async def _no_http(*args: Any, **kwargs: Any) -> dict[str, Any]:
        counter["http"] += 1
        return {}

    monkeypatch.setattr(
        "app.modules.warehouse.bitable_adapter._request", _no_http
    )

    with pytest.raises(WarehouseBitableError) as ei:
        await adapter.create_record("sales_detail", {"品名": "不存在的选项XYZ"})

    assert ei.value.code == 1254062, f"应抛选项值错误码 1254062，实际 {ei.value.code}"
    assert counter["http"] == 0, "本地校验应拦截，不应发起任何 HTTP 请求"
    print(f"[local-reject] code={ei.value.code} http_calls={counter['http']}")


# ── 4. 只读字段拒写 ──


async def test_readonly_field_rejected() -> None:
    """只读类型字段（created_user 1003 / formula 20）→ readonly_field。"""
    adapter = WarehouseBitableAdapter()

    with pytest.raises(WarehouseBitableError) as ei:
        await adapter.create_record("gmp_outbound", {"创建人": "张三"})
    assert ei.value.code == "readonly_field", (
        f"created_user 应拒写，实际 {ei.value.code}"
    )

    with pytest.raises(WarehouseBitableError) as ei2:
        await adapter.create_record(
            "material_receipt", {"应出报日期..": "2026-09-03"}
        )
    assert ei2.value.code == "readonly_field", (
        f"formula 应拒写，实际 {ei2.value.code}"
    )
    print("[readonly] 创建人(1003) 与 应出报日期..(20) 均被拒写")


# ── 5. 过滤查询 ──


async def test_query_records_with_filter() -> None:
    """records/search 带 filter（客户 contains LIVE-TEST）与无过滤 limit=5。"""
    adapter = WarehouseBitableAdapter()

    rows = await adapter.query_records(
        "sales_detail",
        filter_json={
            "conjunction": "and",
            "conditions": [
                {"field_name": "客户", "operator": "contains", "value": ["LIVE-TEST"]}
            ],
        },
        limit=5,
    )
    assert isinstance(rows, list), f"应返回 list，实际 {type(rows)}"
    for row in rows:
        assert "record_id" in row and isinstance(row["fields"], dict), (
            f"每项应为 {{record_id, fields}}，实际 {row}"
        )
    print(f"[filter] 客户 contains LIVE-TEST -> {len(rows)} 条")

    unfiltered = await adapter.query_records("sales_detail", limit=5)
    assert isinstance(unfiltered, list) and len(unfiltered) <= 5
    print(f"[no-filter] limit=5 -> {len(unfiltered)} 条")


# ── 6. 错误码分类（真实 Base） ──


async def test_error_code_classification() -> None:
    """写入不存在字段（未收录名放行到 Base）→ 飞书返回 1254045 分类异常。

    偏差说明：任务原样 fields 还伴写单选「物料名称」="硫酸"，但测试版
    该字段存在重复选项（V1.0-5 已知坑：该字段任何值写入均 1254062
    SingleSelectFieldConvFail），飞书先校验字段名还是先校验选项值是
    非确定行为（实测两种顺序都出现过），导致 1254045 断言间歇失败。
    改为只写不存在字段：该请求唯一的失败可能是字段名不存在，1254045
    确定。物料名称字段写入整体走 S2 降级方案。
    """
    adapter = WarehouseBitableAdapter()

    with pytest.raises(WarehouseBitableError) as ei:
        await adapter.create_record(
            "material_receipt",
            {"不存在的字段XYZ": "1"},
        )

    assert ei.value.code == 1254045, (
        f"不存在字段应抛 1254045，实际 code={ei.value.code} msg={ei.value.message}"
    )
    print("[error-code] 1254045 分类正确（FieldNotFound）")
