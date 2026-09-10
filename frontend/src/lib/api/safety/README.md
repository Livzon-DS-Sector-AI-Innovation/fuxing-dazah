# lib/api/safety 客户端 API 层约定

安全模块的**只读查询**（列表 / 详情 / 统计）统一放这里，供 React Query 的 `queryFn` 调用。
写操作（增删改 / 审批 / 同步）继续留在 `actions/safety` 的 server action 里。

## 约定

- 每个子模块一个文件：`accident.ts` / `hazard.ts` / `contractor.ts` / `check.ts` / ...
- 只依赖 `@/lib/http-client` 的 `apiGet` / `apiFetchPaginated` / `apiPost`，不直接 fetch。
- 函数命名：`fetchXxxList` / `fetchXxxDetail` / `fetchXxxStats`，返回干净 data（或 `{ items, total }`）。
- 失败时 throw（由 React Query 捕获），不做 message 提示。
- 客户端 API 不写 `revalidatePath`。

## 参考实现

见 `src/lib/api/knowledge.ts`（知识库，首个落地案例）与 `src/lib/api/equipment-personnel.ts`。

## 迁移模板（以 accident 为例）

```ts
import type { Accident } from '@/types/safety'
import { apiFetchPaginated } from '@/lib/http-client'

export async function fetchAccidentList(params) {
  const sp = new URLSearchParams()
  // ...
  return apiFetchPaginated(`/api/v1/safety/accidents?${sp}`)
}
```
