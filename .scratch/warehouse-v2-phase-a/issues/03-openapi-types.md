# 03: OpenAPI 类型生成脚本

**What to build:** 开发者运行 `pnpm generate:api` 即可从后端 openapi.json（优先读 ../backend 导出物，否则 fetch /openapi.json）经 openapi-typescript 生成 src/types/generated/schema.ts；为后续新代码提供机器同步的类型契约管道。存量手写类型本次不迁移。

**Blocked by:** None (can start immediately)

**Status:** done

- [x] scripts/generate-api.mjs 存在且 pnpm generate:api 可重复运行成功
- [x] src/types/generated/schema.ts 生成并提交（153KB，源自 frontend/openapi.json 快照）
- [x] 不改动既有手写 types/*.ts 的任何内容
