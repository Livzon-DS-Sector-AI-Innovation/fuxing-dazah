"""仓储管理模块权限声明。

权限编码规范: warehouse:<resource>:<action>
- read: 查看/读取
- create: 新增
- update: 编辑/修改
- delete: 删除
- confirm: 盘点确认
"""

from app.platform.permission.registry import PermissionDef

PERMISSIONS: list[PermissionDef] = [
    # ── 物料主数据 ──
    PermissionDef(
        code="warehouse:material:read",
        name="查看物料主数据",
        module="warehouse",
        resource="material",
        action="read",
        description="查看物料主数据列表和详情",
    ),
    PermissionDef(
        code="warehouse:material:create",
        name="新增物料",
        module="warehouse",
        resource="material",
        action="create",
        description="新增物料主数据",
    ),
    PermissionDef(
        code="warehouse:material:update",
        name="编辑物料",
        module="warehouse",
        resource="material",
        action="update",
        description="编辑物料主数据",
    ),
    PermissionDef(
        code="warehouse:material:delete",
        name="删除物料",
        module="warehouse",
        resource="material",
        action="delete",
        description="删除物料主数据（软删除）",
    ),
    # ── 库位 ──
    PermissionDef(
        code="warehouse:location:read",
        name="查看库位",
        module="warehouse",
        resource="location",
        action="read",
        description="查看库位列表和详情",
    ),
    PermissionDef(
        code="warehouse:location:create",
        name="新增库位",
        module="warehouse",
        resource="location",
        action="create",
        description="新增库位",
    ),
    PermissionDef(
        code="warehouse:location:update",
        name="编辑库位",
        module="warehouse",
        resource="location",
        action="update",
        description="编辑库位",
    ),
    PermissionDef(
        code="warehouse:location:delete",
        name="删除库位",
        module="warehouse",
        resource="location",
        action="delete",
        description="删除库位（软删除）",
    ),
    # ── 库存 ──
    PermissionDef(
        code="warehouse:stock:read",
        name="查看库存",
        module="warehouse",
        resource="stock",
        action="read",
        description="查看现有库存与库存概览",
    ),
    # ── 出入库 ──
    PermissionDef(
        code="warehouse:movement:read",
        name="查看出入库记录",
        module="warehouse",
        resource="movement",
        action="read",
        description="查看出入库记录列表和详情",
    ),
    PermissionDef(
        code="warehouse:movement:create",
        name="新增出入库",
        module="warehouse",
        resource="movement",
        action="create",
        description="登记入库/出库记录",
    ),
    PermissionDef(
        code="warehouse:movement:delete",
        name="撤销出入库",
        module="warehouse",
        resource="movement",
        action="delete",
        description="撤销出入库记录并反向冲销库存",
    ),
    # ── 盘点 ──
    PermissionDef(
        code="warehouse:stocktake:read",
        name="查看盘点单",
        module="warehouse",
        resource="stocktake",
        action="read",
        description="查看盘点单列表和明细",
    ),
    PermissionDef(
        code="warehouse:stocktake:create",
        name="创建盘点单",
        module="warehouse",
        resource="stocktake",
        action="create",
        description="创建盘点单并快照库存",
    ),
    PermissionDef(
        code="warehouse:stocktake:update",
        name="填写盘点结果",
        module="warehouse",
        resource="stocktake",
        action="update",
        description="填写盘点单实盘数量",
    ),
    PermissionDef(
        code="warehouse:stocktake:confirm",
        name="确认盘点单",
        module="warehouse",
        resource="stocktake",
        action="confirm",
        description="确认盘点单并按实盘调整库存",
    ),
    PermissionDef(
        code="warehouse:stocktake:delete",
        name="删除盘点单",
        module="warehouse",
        resource="stocktake",
        action="delete",
        description="删除草稿状态盘点单",
    ),
]
