"""备件管理 API 集成测试。

通过 httpx AsyncClient 测试所有备件相关 HTTP 端点：
请求/响应格式、状态码、分页、过滤、错误处理。

依赖 equipment conftest.py 的 client fixture（已注入权限 mock）。
"""

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.equipment.models.equipment import (
    Equipment,
    EquipmentCategory,
    Location,
)


def _rand_suffix() -> str:
    """生成随机后缀避免测试数据唯一键冲突。"""
    return uuid.uuid4().hex[:8]


# ==================== 创建备件 ====================


class TestCreateSparePartApi:
    """POST /api/v1/equipment/spare-parts/ 创建备件测试。"""

    async def test_create_returns_201_with_data(
        self, client: AsyncClient
    ) -> None:
        """创建备件成功返回数据和 id。"""
        code = f"SP-API-{_rand_suffix()}"
        res = await client.post("/api/v1/equipment/spare-parts/", json={
            "code": code,
            "name": "API测试密封圈",
            "unit": "个",
            "specification": "DN50",
            "unit_price": 12.50,
        })
        assert res.status_code == 200
        body = res.json()
        assert body["code"] == 200
        assert body["data"]["code"] == code
        assert body["data"]["name"] == "API测试密封圈"
        assert body["data"]["unit"] == "个"
        assert body["data"]["id"] is not None

    async def test_create_with_minimal_fields(
        self, client: AsyncClient
    ) -> None:
        """仅传必填字段创建备件成功。"""
        code = f"SP-MIN-{_rand_suffix()}"
        res = await client.post("/api/v1/equipment/spare-parts/", json={
            "code": code,
            "name": "最小字段备件",
            "unit": "根",
        })
        assert res.status_code == 200
        body = res.json()
        assert body["data"]["specification"] is None
        assert body["data"]["unit_price"] is None
        assert body["data"]["is_active"] is True

    async def test_create_duplicate_code_returns_409(
        self, client: AsyncClient
    ) -> None:
        """重复备件编码返回 409 冲突。"""
        code = f"SP-DUP-{_rand_suffix()}"
        # 第一次创建
        res1 = await client.post("/api/v1/equipment/spare-parts/", json={
            "code": code, "name": "第一个", "unit": "个",
        })
        assert res1.status_code == 200

        # 重复创建
        res2 = await client.post("/api/v1/equipment/spare-parts/", json={
            "code": code, "name": "第二个", "unit": "个",
        })
        assert res2.status_code == 409

    async def test_create_missing_required_field_returns_422(
        self, client: AsyncClient
    ) -> None:
        """缺少必填字段时返回 422 校验错误。"""
        res = await client.post("/api/v1/equipment/spare-parts/", json={
            "code": f"SP-422-{_rand_suffix()}",
            # 缺少 name
        })
        assert res.status_code == 422

    async def test_create_invalid_unit_price_negative_returns_422(
        self, client: AsyncClient
    ) -> None:
        """unit_price 为负数时返回 422。"""
        res = await client.post("/api/v1/equipment/spare-parts/", json={
            "code": f"SP-NEG-{_rand_suffix()}",
            "name": "负价格备件",
            "unit": "个",
            "unit_price": -1,
        })
        assert res.status_code == 422


# ==================== 备件列表 ====================


class TestListSparePartsApi:
    """GET /api/v1/equipment/spare-parts/ 备件列表测试。"""

    async def test_list_returns_paginated_data(
        self, client: AsyncClient
    ) -> None:
        """列表接口返回分页数据和 meta 信息。"""
        # 确保至少有数据
        await client.post("/api/v1/equipment/spare-parts/", json={
            "code": f"SP-LIST-{_rand_suffix()}",
            "name": "列表测试备件",
            "unit": "个",
        })

        res = await client.get("/api/v1/equipment/spare-parts/", params={
            "page": 1, "page_size": 10,
        })
        assert res.status_code == 200
        body = res.json()
        assert body["code"] == 200
        assert isinstance(body["data"], list)
        assert "meta" in body
        assert body["meta"]["page"] == 1
        assert body["meta"]["page_size"] == 10
        assert "total" in body["meta"]

    async def test_list_supports_category_filter(
        self, client: AsyncClient
    ) -> None:
        """列表支持按分类筛选。"""
        suffix = _rand_suffix()
        await client.post("/api/v1/equipment/spare-parts/", json={
            "code": f"SP-FCAT-{suffix}",
            "name": "分类筛选备件",
            "unit": "个",
            "category": "电气类",
        })

        res = await client.get("/api/v1/equipment/spare-parts/", params={
            "category": "电气类",
        })
        assert res.status_code == 200
        for item in res.json()["data"]:
            assert item["category"] == "电气类"

    async def test_list_supports_keyword_search(
        self, client: AsyncClient
    ) -> None:
        """列表支持关键词搜索。"""
        suffix = _rand_suffix()
        await client.post("/api/v1/equipment/spare-parts/", json={
            "code": f"SP-KSEARCH-{suffix}",
            "name": "独特搜索词备件",
            "unit": "个",
        })

        res = await client.get("/api/v1/equipment/spare-parts/", params={
            "keyword": "独特搜索词",
        })
        assert res.status_code == 200
        data = res.json()["data"]
        assert len(data) >= 1
        for item in data:
            name_or_code = item["name"] + item["code"]
            assert "独特搜索词" in name_or_code

    async def test_list_supports_is_active_filter(
        self, client: AsyncClient
    ) -> None:
        """列表支持按启用状态筛选。"""
        suffix = _rand_suffix()
        # 创建一个停用的
        res_create = await client.post("/api/v1/equipment/spare-parts/", json={
            "code": f"SP-INACTF-{suffix}",
            "name": "停用筛选备件",
            "unit": "个",
        })
        sp_id = res_create.json()["data"]["id"]
        await client.put(f"/api/v1/equipment/spare-parts/{sp_id}", json={
            "is_active": False,
        })

        res = await client.get("/api/v1/equipment/spare-parts/", params={
            "is_active": False,
        })
        assert res.status_code == 200
        for item in res.json()["data"]:
            assert item["is_active"] is False

    async def test_list_page_size_capped_at_200(
        self, client: AsyncClient
    ) -> None:
        """page_size 超过 200 时返回 422 校验错误。"""
        res = await client.get("/api/v1/equipment/spare-parts/", params={
            "page_size": 201,
        })
        assert res.status_code == 422


# ==================== 备件详情 ====================


class TestGetSparePartApi:
    """GET /api/v1/equipment/spare-parts/{id} 备件详情测试。"""

    async def test_get_detail_returns_full_data(
        self, client: AsyncClient
    ) -> None:
        """查询存在的备件返回完整详情。"""
        code = f"SP-DETAIL-{_rand_suffix()}"
        res_create = await client.post("/api/v1/equipment/spare-parts/", json={
            "code": code,
            "name": "详情测试备件",
            "unit": "个",
            "specification": "DETAIL-V1",
        })
        sp_id = res_create.json()["data"]["id"]

        res = await client.get(f"/api/v1/equipment/spare-parts/{sp_id}")
        assert res.status_code == 200
        body = res.json()
        assert body["data"]["id"] == sp_id
        assert body["data"]["code"] == code
        assert body["data"]["specification"] == "DETAIL-V1"

    async def test_get_nonexistent_returns_404(
        self, client: AsyncClient
    ) -> None:
        """查询不存在的备件返回 404。"""
        fake_id = uuid.uuid4()
        res = await client.get(f"/api/v1/equipment/spare-parts/{fake_id}")
        assert res.status_code == 404


# ==================== 更新备件 ====================


class TestUpdateSparePartApi:
    """PUT /api/v1/equipment/spare-parts/{id} 更新备件测试。"""

    async def test_update_name_succeeds(
        self, client: AsyncClient
    ) -> None:
        """更新备件名称成功。"""
        code = f"SP-UPNAME-{_rand_suffix()}"
        res_create = await client.post("/api/v1/equipment/spare-parts/", json={
            "code": code, "name": "原始名称", "unit": "个",
        })
        sp_id = res_create.json()["data"]["id"]

        res = await client.put(f"/api/v1/equipment/spare-parts/{sp_id}", json={
            "name": "新名称",
        })
        assert res.status_code == 200
        assert res.json()["data"]["name"] == "新名称"

    async def test_update_code_to_duplicate_returns_409(
        self, client: AsyncClient
    ) -> None:
        """更新编码为已存在的编码返回 409。"""
        suffix = _rand_suffix()
        # 创建两个备件
        await client.post("/api/v1/equipment/spare-parts/", json={
            "code": f"SP-DUP1-{suffix}", "name": "备件A", "unit": "个",
        })
        r2 = await client.post("/api/v1/equipment/spare-parts/", json={
            "code": f"SP-DUP2-{suffix}", "name": "备件B", "unit": "个",
        })
        sp2_id = r2.json()["data"]["id"]

        # 尝试将备件B的编码改成备件A的编码
        res = await client.put(f"/api/v1/equipment/spare-parts/{sp2_id}", json={
            "code": f"SP-DUP1-{suffix}",
        })
        assert res.status_code == 409

    async def test_update_nonexistent_returns_404(
        self, client: AsyncClient
    ) -> None:
        """更新不存在的备件返回 404。"""
        res = await client.put(f"/api/v1/equipment/spare-parts/{uuid.uuid4()}", json={
            "name": "不存在",
        })
        assert res.status_code == 404


# ==================== 删除备件 ====================


class TestDeleteSparePartApi:
    """DELETE /api/v1/equipment/spare-parts/{id} 删除备件测试。"""

    async def test_delete_succeeds(self, client: AsyncClient) -> None:
        """删除备件成功返回 200。"""
        code = f"SP-DELAPI-{_rand_suffix()}"
        res_create = await client.post("/api/v1/equipment/spare-parts/", json={
            "code": code, "name": "待删除", "unit": "个",
        })
        sp_id = res_create.json()["data"]["id"]

        res = await client.delete(f"/api/v1/equipment/spare-parts/{sp_id}")
        assert res.status_code == 200

        # 确认已删除（软删除后查不到）
        res_get = await client.get(f"/api/v1/equipment/spare-parts/{sp_id}")
        assert res_get.status_code == 404

    async def test_delete_nonexistent_returns_404(
        self, client: AsyncClient
    ) -> None:
        """删除不存在的备件返回 404。"""
        res = await client.delete(f"/api/v1/equipment/spare-parts/{uuid.uuid4()}")
        assert res.status_code == 404


# ==================== 库存查询 ====================


class TestGetStockApi:
    """GET /api/v1/equipment/spare-parts/{id}/stock 查看库存测试。"""

    async def test_get_stock_returns_data(self, client: AsyncClient) -> None:
        """查询备件库存返回库存信息。"""
        code = f"SP-STKAPI-{_rand_suffix()}"
        res_create = await client.post("/api/v1/equipment/spare-parts/", json={
            "code": code, "name": "库存查询备件", "unit": "个",
        })
        sp_id = res_create.json()["data"]["id"]

        # 先入库一些
        await client.post(f"/api/v1/equipment/spare-parts/{sp_id}/stock/inbound", json={
            "quantity": 50,
        })

        res = await client.get(f"/api/v1/equipment/spare-parts/{sp_id}/stock")
        assert res.status_code == 200
        stock = res.json()["data"]
        assert stock["spare_part_id"] == sp_id
        assert stock["current_qty"] == 50
        assert "safety_qty" in stock
        assert "min_order_qty" in stock

    async def test_get_stock_for_nonexistent_spare_part_returns_404(
        self, client: AsyncClient
    ) -> None:
        """查询不存在备件的库存返回 404。"""
        res = await client.get(
            f"/api/v1/equipment/spare-parts/{uuid.uuid4()}/stock"
        )
        assert res.status_code == 404


# ==================== 入库 ====================


class TestInboundStockApi:
    """POST /api/v1/equipment/spare-parts/{id}/stock/inbound 入库测试。"""

    async def test_inbound_increases_stock(
        self, client: AsyncClient
    ) -> None:
        """入库成功后库存数量增加。"""
        code = f"SP-INAPI-{_rand_suffix()}"
        res_create = await client.post("/api/v1/equipment/spare-parts/", json={
            "code": code, "name": "入库API备件", "unit": "个",
        })
        sp_id = res_create.json()["data"]["id"]

        # 第一次入库
        res1 = await client.post(
            f"/api/v1/equipment/spare-parts/{sp_id}/stock/inbound",
            json={"quantity": 30, "remark": "首次入库"},
        )
        assert res1.status_code == 200
        assert res1.json()["data"]["current_qty"] == 30

        # 第二次入库
        res2 = await client.post(
            f"/api/v1/equipment/spare-parts/{sp_id}/stock/inbound",
            json={"quantity": 20, "remark": "第二次入库"},
        )
        assert res2.status_code == 200
        assert res2.json()["data"]["current_qty"] == 50

    async def test_inbound_with_warehouse_location(
        self, client: AsyncClient
    ) -> None:
        """入库时指定库位，库存记录更新库位信息。"""
        code = f"SP-WHAPI-{_rand_suffix()}"
        res_create = await client.post("/api/v1/equipment/spare-parts/", json={
            "code": code, "name": "库位入库备件", "unit": "个",
        })
        sp_id = res_create.json()["data"]["id"]

        res = await client.post(
            f"/api/v1/equipment/spare-parts/{sp_id}/stock/inbound",
            json={"quantity": 10, "warehouse_location": "B-03-01"},
        )
        assert res.status_code == 200
        assert res.json()["data"]["warehouse_location"] == "B-03-01"

    async def test_inbound_zero_quantity_returns_422(
        self, client: AsyncClient
    ) -> None:
        """入库数量为 0 时返回 422（校验 ge=1）。"""
        code = f"SP-ZQ-{_rand_suffix()}"
        res_create = await client.post("/api/v1/equipment/spare-parts/", json={
            "code": code, "name": "零数量备件", "unit": "个",
        })
        sp_id = res_create.json()["data"]["id"]

        res = await client.post(
            f"/api/v1/equipment/spare-parts/{sp_id}/stock/inbound",
            json={"quantity": 0},
        )
        assert res.status_code == 422

    async def test_inbound_nonexistent_spare_part_returns_404(
        self, client: AsyncClient
    ) -> None:
        """对不存在的备件入库返回 404。"""
        res = await client.post(
            f"/api/v1/equipment/spare-parts/{uuid.uuid4()}/stock/inbound",
            json={"quantity": 10},
        )
        assert res.status_code == 404


# ==================== 盘点调整 ====================


class TestAdjustStockApi:
    """POST /api/v1/equipment/spare-parts/{id}/stock/adjust 盘点调整测试。"""

    async def test_adjust_increase(
        self, client: AsyncClient
    ) -> None:
        """盘点调整增加库存。"""
        code = f"SP-ADJAPI-{_rand_suffix()}"
        res_create = await client.post("/api/v1/equipment/spare-parts/", json={
            "code": code, "name": "盘点调整备件", "unit": "个",
        })
        sp_id = res_create.json()["data"]["id"]
        # 先入库
        await client.post(
            f"/api/v1/equipment/spare-parts/{sp_id}/stock/inbound",
            json={"quantity": 30},
        )

        res = await client.post(
            f"/api/v1/equipment/spare-parts/{sp_id}/stock/adjust",
            json={"new_qty": 50, "remark": "盘盈"},
        )
        assert res.status_code == 200
        assert res.json()["data"]["current_qty"] == 50

    async def test_adjust_decrease(
        self, client: AsyncClient
    ) -> None:
        """盘点调整减少库存。"""
        code = f"SP-ADJDEC-{_rand_suffix()}"
        res_create = await client.post("/api/v1/equipment/spare-parts/", json={
            "code": code, "name": "盘亏备件", "unit": "个",
        })
        sp_id = res_create.json()["data"]["id"]
        await client.post(
            f"/api/v1/equipment/spare-parts/{sp_id}/stock/inbound",
            json={"quantity": 50},
        )

        res = await client.post(
            f"/api/v1/equipment/spare-parts/{sp_id}/stock/adjust",
            json={"new_qty": 20, "remark": "盘亏"},
        )
        assert res.status_code == 200
        assert res.json()["data"]["current_qty"] == 20

    async def test_adjust_to_zero(
        self, client: AsyncClient
    ) -> None:
        """盘点调整到 0 是允许的。"""
        code = f"SP-ADJZ-{_rand_suffix()}"
        res_create = await client.post("/api/v1/equipment/spare-parts/", json={
            "code": code, "name": "清零备件", "unit": "个",
        })
        sp_id = res_create.json()["data"]["id"]
        await client.post(
            f"/api/v1/equipment/spare-parts/{sp_id}/stock/inbound",
            json={"quantity": 10},
        )

        res = await client.post(
            f"/api/v1/equipment/spare-parts/{sp_id}/stock/adjust",
            json={"new_qty": 0, "remark": "清零"},
        )
        assert res.status_code == 200
        assert res.json()["data"]["current_qty"] == 0

    async def test_adjust_negative_new_qty_returns_422(
        self, client: AsyncClient
    ) -> None:
        """调整后数量为负数返回 422（校验 ge=0）。"""
        code = f"SP-ADJNEG-{_rand_suffix()}"
        res_create = await client.post("/api/v1/equipment/spare-parts/", json={
            "code": code, "name": "负调整备件", "unit": "个",
        })
        sp_id = res_create.json()["data"]["id"]

        res = await client.post(
            f"/api/v1/equipment/spare-parts/{sp_id}/stock/adjust",
            json={"new_qty": -1},
        )
        assert res.status_code == 422

    async def test_adjust_nonexistent_spare_part_returns_404(
        self, client: AsyncClient
    ) -> None:
        """对不存在的备件盘点返回 404。"""
        res = await client.post(
            f"/api/v1/equipment/spare-parts/{uuid.uuid4()}/stock/adjust",
            json={"new_qty": 10},
        )
        assert res.status_code == 404


# ==================== 库存预警 ====================


class TestStockWarningsApi:
    """GET /api/v1/equipment/spare-parts/stock/warnings 库存预警测试。"""

    async def test_warnings_returns_list(self, client: AsyncClient) -> None:
        """预警接口返回列表格式（可能为空）。"""
        res = await client.get("/api/v1/equipment/spare-parts/stock/warnings")
        assert res.status_code == 200
        body = res.json()
        assert body["code"] == 200
        assert isinstance(body["data"], list)

    async def test_warnings_includes_low_stock_items(
        self, client: AsyncClient
    ) -> None:
        """库存不足的备件出现在预警列表，且字段为前端契约的扁平结构。"""
        code = f"SP-WARNAPI-{_rand_suffix()}"
        # 走导入创建低库存场景（API 其它入口不写 safety_qty）
        content = _make_import_file([
            [code, "预警API备件", None, "个", None, None, 1.0, 1, 10],
        ])
        await client.post(
            "/api/v1/equipment/spare-parts/import",
            files={"file": ("预警.xlsx", content, "application/octet-stream")},
        )

        res = await client.get("/api/v1/equipment/spare-parts/stock/warnings")
        assert res.status_code == 200
        items = res.json()["data"]
        target = next(i for i in items if i["code"] == code)
        assert target["name"] == "预警API备件"
        assert target["current_qty"] == 1
        assert target["min_qty"] == 10
        assert target["shortage"] == 9
        assert target["spare_part_id"]


# ==================== 消耗流水 ====================


class TestTransactionsApi:
    """GET /api/v1/equipment/spare-parts/transactions 消耗流水测试。"""

    async def test_transactions_returns_paginated(
        self, client: AsyncClient
    ) -> None:
        """流水接口返回分页数据。"""
        # 先创建一个备件并入库以产生流水
        code = f"SP-TXNAPI-{_rand_suffix()}"
        res_create = await client.post("/api/v1/equipment/spare-parts/", json={
            "code": code, "name": "流水API备件", "unit": "个",
        })
        sp_id = res_create.json()["data"]["id"]
        await client.post(
            f"/api/v1/equipment/spare-parts/{sp_id}/stock/inbound",
            json={"quantity": 10},
        )

        res = await client.get("/api/v1/equipment/spare-parts/transactions", params={
            "page": 1, "page_size": 20,
        })
        assert res.status_code == 200
        body = res.json()
        assert isinstance(body["data"], list)
        assert "meta" in body

    async def test_transactions_filter_by_type(
        self, client: AsyncClient
    ) -> None:
        """流水支持按类型筛选。"""
        code = f"SP-TXNTYPE-{_rand_suffix()}"
        res_create = await client.post("/api/v1/equipment/spare-parts/", json={
            "code": code, "name": "类型筛选备件", "unit": "个",
        })
        sp_id = res_create.json()["data"]["id"]
        await client.post(
            f"/api/v1/equipment/spare-parts/{sp_id}/stock/inbound",
            json={"quantity": 5},
        )

        res = await client.get("/api/v1/equipment/spare-parts/transactions", params={
            "transaction_type": "入库",
        })
        assert res.status_code == 200
        for item in res.json()["data"]:
            assert item["transaction_type"] == "入库"


# ==================== 设备-备件关联 ====================


class TestEquipmentLinkApi:
    """备件-设备关联 API 测试。"""

    @staticmethod
    async def _create_test_equipment(
        db_session: AsyncSession,
    ) -> str:
        """在 DB 中创建 Location + Category + Equipment，返回 equipment_id 字符串。"""
        suffix = _rand_suffix()
        # 1. 位置
        location = Location(name=f"测试车间-{suffix}", code=f"LOC-{suffix}")
        db_session.add(location)
        await db_session.flush()

        # 2. 分类
        category = EquipmentCategory(
            name=f"测试分类-{suffix}", code=f"CAT-{suffix}",
        )
        db_session.add(category)
        await db_session.flush()

        # 3. 设备
        equipment = Equipment(
            equipment_no=f"EQ-{suffix}",
            name=f"测试设备-{suffix}",
            location_id=location.id,
            status="完好",
        )
        db_session.add(equipment)
        await db_session.flush()
        await db_session.refresh(equipment)
        return str(equipment.id)

    async def test_link_and_list_equipments(
        self, client: AsyncClient, _equipment_session: AsyncSession,
    ) -> None:
        """绑定设备后能在关联列表中查询到。"""
        code = f"SP-EQAPI-{_rand_suffix()}"
        res_create = await client.post("/api/v1/equipment/spare-parts/", json={
            "code": code, "name": "关联设备备件", "unit": "个",
        })
        sp_id = res_create.json()["data"]["id"]
        eq_id = await self._create_test_equipment(_equipment_session)

        # 绑定设备
        res_link = await client.post(
            f"/api/v1/equipment/spare-parts/{sp_id}/equipments",
            json={"equipment_id": eq_id, "quantity": 3},
        )
        assert res_link.status_code == 200
        assert res_link.json()["data"]["equipment_id"] == eq_id
        assert res_link.json()["data"]["quantity"] == 3

        # 查询关联设备列表
        res_list = await client.get(
            f"/api/v1/equipment/spare-parts/{sp_id}/equipments",
        )
        assert res_list.status_code == 200
        assert len(res_list.json()["data"]) >= 1
        linked_eq_ids = [
            item["equipment_id"] for item in res_list.json()["data"]
        ]
        assert eq_id in linked_eq_ids

    async def test_unlink_equipment(
        self, client: AsyncClient, _equipment_session: AsyncSession,
    ) -> None:
        """解绑设备关联后列表不再包含该关联。"""
        code = f"SP-UNLINKAPI-{_rand_suffix()}"
        res_create = await client.post("/api/v1/equipment/spare-parts/", json={
            "code": code, "name": "解绑测试备件", "unit": "个",
        })
        sp_id = res_create.json()["data"]["id"]
        eq_id = await self._create_test_equipment(_equipment_session)

        # 绑定
        res_link = await client.post(
            f"/api/v1/equipment/spare-parts/{sp_id}/equipments",
            json={"equipment_id": eq_id, "quantity": 1},
        )
        link_id = res_link.json()["data"]["id"]

        # 解绑
        res_del = await client.delete(
            f"/api/v1/equipment/spare-parts/{sp_id}/equipments/{link_id}",
        )
        assert res_del.status_code == 200

        # 确认已解绑
        res_list = await client.get(
            f"/api/v1/equipment/spare-parts/{sp_id}/equipments",
        )
        linked_ids = [
            item["id"] for item in res_list.json()["data"]
        ]
        assert link_id not in linked_ids

    async def test_unlink_nonexistent_returns_404(
        self, client: AsyncClient, _equipment_session: AsyncSession,
    ) -> None:
        """解绑不存在的关联返回 404。"""
        code = f"SP-UNL404-{_rand_suffix()}"
        res_create = await client.post("/api/v1/equipment/spare-parts/", json={
            "code": code, "name": "404解绑备件", "unit": "个",
        })
        sp_id = res_create.json()["data"]["id"]

        res = await client.delete(
            f"/api/v1/equipment/spare-parts/{sp_id}/equipments/{uuid.uuid4()}",
        )
        assert res.status_code == 404

    async def test_duplicate_link_returns_error(
        self, client: AsyncClient, _equipment_session: AsyncSession,
    ) -> None:
        """重复绑定同一设备-备件组合返回错误。"""
        code = f"SP-DUPLINK-{_rand_suffix()}"
        res_create = await client.post("/api/v1/equipment/spare-parts/", json={
            "code": code, "name": "重复绑定备件", "unit": "个",
        })
        sp_id = res_create.json()["data"]["id"]
        eq_id = await self._create_test_equipment(_equipment_session)

        # 第一次绑定
        await client.post(
            f"/api/v1/equipment/spare-parts/{sp_id}/equipments",
            json={"equipment_id": eq_id, "quantity": 1},
        )
        # 第二次绑定同设备
        res2 = await client.post(
            f"/api/v1/equipment/spare-parts/{sp_id}/equipments",
            json={"equipment_id": eq_id, "quantity": 2},
        )
        assert res2.status_code == 400


# ==================== 出库 ====================


class TestOutboundStockApi:
    """POST /api/v1/equipment/spare-parts/{id}/stock/outbound 出库测试。"""

    async def _create_with_stock(self, client: AsyncClient, qty: int) -> str:
        code = f"SP-OUTAPI-{_rand_suffix()}"
        res_create = await client.post("/api/v1/equipment/spare-parts/", json={
            "code": code, "name": "出库API备件", "unit": "个",
        })
        sp_id = res_create.json()["data"]["id"]
        await client.post(
            f"/api/v1/equipment/spare-parts/{sp_id}/stock/inbound",
            json={"quantity": qty},
        )
        return sp_id

    async def test_outbound_decreases_stock(self, client: AsyncClient) -> None:
        """出库成功后库存减少，备注写入流水。"""
        sp_id = await self._create_with_stock(client, 30)

        res = await client.post(
            f"/api/v1/equipment/spare-parts/{sp_id}/stock/outbound",
            json={"quantity": 5, "remark": "车间领用"},
        )
        assert res.status_code == 200
        assert res.json()["data"]["current_qty"] == 25

        # 流水中可见出库记录
        res_tx = await client.get("/api/v1/equipment/spare-parts/transactions")
        tx_items = res_tx.json()["data"]
        outbound_rows = [
            t for t in tx_items
            if t["spare_part_id"] == sp_id and t["transaction_type"] == "出库"
        ]
        assert outbound_rows
        assert outbound_rows[0]["quantity"] == -5
        assert outbound_rows[0]["remark"] == "车间领用"

    async def test_outbound_exact_qty_clears_stock(self, client: AsyncClient) -> None:
        """出库数量等于库存时允许（清空）。"""
        sp_id = await self._create_with_stock(client, 8)

        res = await client.post(
            f"/api/v1/equipment/spare-parts/{sp_id}/stock/outbound",
            json={"quantity": 8},
        )
        assert res.status_code == 200
        assert res.json()["data"]["current_qty"] == 0

    async def test_outbound_insufficient_returns_400(self, client: AsyncClient) -> None:
        """库存不足时返回 400。"""
        sp_id = await self._create_with_stock(client, 10)

        res = await client.post(
            f"/api/v1/equipment/spare-parts/{sp_id}/stock/outbound",
            json={"quantity": 999},
        )
        assert res.status_code == 400

    async def test_outbound_zero_quantity_returns_422(self, client: AsyncClient) -> None:
        """出库数量为 0 时返回 422（校验 ge=1）。"""
        sp_id = await self._create_with_stock(client, 10)

        res = await client.post(
            f"/api/v1/equipment/spare-parts/{sp_id}/stock/outbound",
            json={"quantity": 0},
        )
        assert res.status_code == 422

    async def test_outbound_nonexistent_returns_404(self, client: AsyncClient) -> None:
        """对不存在的备件出库返回 404。"""
        res = await client.post(
            f"/api/v1/equipment/spare-parts/{uuid.uuid4()}/stock/outbound",
            json={"quantity": 1},
        )
        assert res.status_code == 404


# ==================== Excel 导入 ====================


def _make_import_file(rows: list[list[object]]) -> bytes:
    """构造备件导入 xlsx（表头 + 示例行 + 数据行）。"""
    import io

    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "备件管理"
    ws.append([
        "备件编码 *", "备件名称 *", "规格型号", "计量单位 *",
        "备件分类", "默认供应商", "参考单价（元）", "初始库存数量", "安全库存",
    ])
    ws.append(["SP-001", "轴承密封圈", "Φ50×Φ34×7", "个", "机械密封", "示例供应商", "85.50", "50", "10"])
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class TestImportSparePartsApi:
    """GET/POST /api/v1/equipment/spare-parts/import 备件导入测试。"""

    async def test_template_contains_quantity_headers(self, client: AsyncClient) -> None:
        """导入模板包含新增的数量/安全库存列。"""
        import io

        import openpyxl

        res = await client.get("/api/v1/equipment/spare-parts/import/template")
        assert res.status_code == 200

        wb = openpyxl.load_workbook(io.BytesIO(res.content))
        assert "备件管理" in wb.sheetnames
        headers = [c.value for c in wb["备件管理"][1]]
        assert "初始库存数量" in headers
        assert "安全库存" in headers

    async def test_import_with_quantity(self, client: AsyncClient) -> None:
        """带数量导入：建档成功且库存落数量。"""
        code = f"SP-IMPAPI-{_rand_suffix()}"
        content = _make_import_file([
            [code, "导入备件", "DN50", "个", "五金机械", None, 9.9, 12, 3],
        ])

        res = await client.post(
            "/api/v1/equipment/spare-parts/import",
            files={"file": ("备件.xlsx", content, "application/octet-stream")},
        )
        assert res.status_code == 200
        data = res.json()["data"]
        assert data["imported"] == 1
        assert data["skipped"] == 0

        res_list = await client.get(
            "/api/v1/equipment/spare-parts/", params={"keyword": code}
        )
        items = res_list.json()["data"]
        assert items and items[0]["current_qty"] == 12

    async def test_import_existing_code_accumulates(self, client: AsyncClient) -> None:
        """重复导入同编码：数量累加而非报错。"""
        code = f"SP-IMPAPI-{_rand_suffix()}"
        content1 = _make_import_file([
            [code, "累加备件", None, "个", None, None, 5.0, 10, None],
        ])
        await client.post(
            "/api/v1/equipment/spare-parts/import",
            files={"file": ("备件1.xlsx", content1, "application/octet-stream")},
        )

        content2 = _make_import_file([
            [code, "累加备件", None, "个", None, None, 6.0, 15, None],
        ])
        res2 = await client.post(
            "/api/v1/equipment/spare-parts/import",
            files={"file": ("备件2.xlsx", content2, "application/octet-stream")},
        )
        assert res2.status_code == 200
        assert res2.json()["data"]["imported"] == 1

        res_list = await client.get(
            "/api/v1/equipment/spare-parts/", params={"keyword": code}
        )
        items = res_list.json()["data"]
        assert items and items[0]["current_qty"] == 25  # 10 + 15

    async def test_import_overwrite_mode_via_form(self, client: AsyncClient) -> None:
        """mode 表单参数生效：overwrite 时库存覆盖为表值而非累加。"""
        code = f"SP-IMPAPI-{_rand_suffix()}"
        content1 = _make_import_file([
            [code, "覆盖备件", None, "个", None, None, 5.0, 10, None],
        ])
        await client.post(
            "/api/v1/equipment/spare-parts/import",
            files={"file": ("备件1.xlsx", content1, "application/octet-stream")},
        )

        content2 = _make_import_file([
            [code, "覆盖备件", None, "个", None, None, 5.0, 4, None],
        ])
        res = await client.post(
            "/api/v1/equipment/spare-parts/import",
            data={"mode": "overwrite"},
            files={"file": ("备件2.xlsx", content2, "application/octet-stream")},
        )
        assert res.status_code == 200
        assert res.json()["data"]["imported"] == 1

        res_list = await client.get(
            "/api/v1/equipment/spare-parts/", params={"keyword": code}
        )
        items = res_list.json()["data"]
        assert items and items[0]["current_qty"] == 4  # 覆盖为 4，不是 10 + 4
