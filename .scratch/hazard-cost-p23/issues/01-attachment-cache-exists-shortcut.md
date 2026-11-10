# 01: 附件缓存 exists 短路

**What to build:** 同一记录的同一附件被 ①识别 / ②初审 / 例外复核员任一方再次处理（含失败重试）时，不再发起任何网络下载——下载前按确定性存储键探测统一附件存储，命中直接返回存量路径；未命中走原三级回退并照常落盘。缓存行为受 app_config 开关控制（默认开），开关关闭时行为与现状逐字节一致。

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] S1 wiring 测试：exists 命中时 fake client 零下载调用（策略 1/2/3 均不触发），返回存量路径
- [ ] 未命中时走原三级回退且照常 store_bytes（既有行为回归）
- [ ] 开关关闭时回退现状全量下载（fake store exists 不被消费）
- [ ] registry 新键走 commit-tree 流水线（HEAD blob + 自己 hunk），热生效、默认 True
- [ ] 同文件内他人 WIP hunk 零触碰（git diff 复核）
- [ ] ruff/mypy 本文件无新增错误；测试全 fake
