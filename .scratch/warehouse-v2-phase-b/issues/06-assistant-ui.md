# 06: 悬浮 AI 助手前端

**What to build:** 仓储模块页面右下角悬浮助手：圆形按钮 → 420×640 聊窗（可放大）；发消息走 chat/stream，前端 fetch 流读取渲染：阶段标签（正在调用 xxx）→ 打字机输出完整回复 → Markdown 表格渲染为卡片 + 错误/finished 处理；写操作确认卡（若 Runner 返回确认事件：风险 Tag + 确认/取消，确认调既有确认接口）；会话续聊（session_id 保持）。对话历史仅内存态（刷新即清），不做历史管理 UI。

**Blocked by:** 05 (Agent Web 网关)

**Status:** done

- [x] 悬浮按钮 + 聊窗开合正常（组件测试）
- [x] SSE 解析：mock 流断言阶段标签/消息渲染/finished 终态
- [x] 确认卡渲染与确认调用（确认事件接口预留；V1.0 Runner 无确认事件输出，确认走既有草稿确认门）
- [x] 仅 /warehouse 路由组挂载（warehouse/layout.tsx）；typecheck 零新增

> 备注：修复 finally 中过期闭包覆盖真实错误的问题；parseSseBlock 纯函数单独测试。
