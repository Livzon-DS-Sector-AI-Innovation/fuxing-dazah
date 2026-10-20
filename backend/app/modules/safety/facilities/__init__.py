"""安全设备设施管理域（facilities-p1：三台账接入 + 校验任务闭环）。

需求源：docs/DESIGN-安全设备设施管理模块-三台账校验闭环与锅炉监控-20261019.md。
包内分层：
- ``ledger.py``  列映射适配层（纯函数，表头驱动，锚点推算/降级）
- ``reader.py``  三台账直读 reader（BitablePageClient 注入 + TTL 缓存）
- ``engine.py``  校验任务纯函数引擎（到期筛选/分组键/锚点前移判定）
- ``dispatch.py`` 每日派发编排 + 对账（调度 08:10）
- ``closure.py`` 闭环/取消/reopen 状态迁移（事件与对账双通道共用）
- ``event_handler.py`` record 变更事件实时闭环通道
- ``notify.py``   滚动批次卡 + 速递格子 + 逾期升级
"""

# 触发 @on_event 装饰器注册（三台账 record 变更实时闭环通道；经 api 路由的
# import 链在应用启动时挂载，照 feishu/__init__ 的 handler 注册惯例）
from app.modules.safety.facilities import event_handler  # noqa: F401,E402
