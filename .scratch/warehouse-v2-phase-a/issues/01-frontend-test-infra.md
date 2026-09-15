# 01: 前端测试设施与脚本

**What to build:** 开发者可以在 frontend 运行 `pnpm test` 执行组件测试、`pnpm typecheck` 做全量类型检查；首个样例测试落地（库存页签容器渲染三个页签），作为后续所有前端票的测试接缝。安装 devDependencies：vitest、@vitejs/plugin-react、@testing-library/react、@testing-library/jest-dom、@testing-library/user-event、happy-dom。

**Blocked by:** None (can start immediately)

**Status:** done

- [x] package.json 新增 test / typecheck 脚本且均可执行通过
- [x] vitest.config.ts（happy-dom 环境 + setup 文件引入 jest-dom matchers，suite 超时 15s）
- [x] 至少 1 个组件测试通过（库存页签容器渲染三标签）
- [x] 不改变任何业务组件行为；typecheck 全量通过

> 备注：vitest 将 `server-only` 别名到 src/test/server-only-stub.ts（Next 语义在测试环境的等价物）；组件测试需 mock '@/actions/warehouse'（组件挂载即取数）。
