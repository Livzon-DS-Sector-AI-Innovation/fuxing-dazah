# 08: 行详情抽屉与流水时间线

**What to build:** 仓库管理员在库存列表点击任意行，右侧滑出详情抽屉：上半部物料/批次/库位信息，下半部该物料近 90 天出入库流水时间线（倒序，含方向/数量/单号/时间）。后端 movements 查询支持 material_id 精确筛选。抽屉关闭回到列表原状态。

**Blocked by:** 01 (前端测试设施与脚本)

**Status:** done

- [x] movements 端点支持 material_id 参数（路由测试覆盖：双物料造数断言 total=1 且全部命中）
- [x] Drawer 打开/关闭/加载/空流水四态正确
- [x] 时间线倒序且字段齐全（组件测试：点击行 → 抽屉标题 + 时间线条目）

> 备注：MovementFilter 类型与 setMovementParams 同步补 material_id；前端抽屉用 useQuery enabled=!!detail 惰性取数；antd Table 点击行用 findAllByText 首个匹配规避测量行文本重复。
