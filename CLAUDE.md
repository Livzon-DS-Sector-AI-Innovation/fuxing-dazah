# 项目说明

原料药厂管理系统，Next.js 16 App Router，TypeScript。
后端为独立的 Python FastAPI 服务，地址见 .env.local 的 API_BASE_URL。
UI或组件样式务必遵守：@DESIGN.md
你使用的技术和函数调用的方式可能有些过时，请使用context7获取最新技术文档。
使用antd组件和配置时，使用context7查询最新参数文档。

## 技术栈

- Next.js 16 + React 19 + TypeScript + Tailwind CSS
- 组件库：Ant Design V6（antd）
- 状态管理：Zustand（stores/ 目录）
- 服务端数据请求：直接 fetch（Server Component 内）
- 客户端数据请求：React Query（@tanstack/react-query）
- 表单：React Hook Form + Zod 校验

## 目录职责

- app/(dashboard)/<模块>/     路由页面，只做数据获取和布局组装
- components/<模块>/          该模块所有 UI 组件
- components/shared/          公共组件，不要擅自修改，如需新增找架构负责人
- actions/<模块>.ts           该模块所有写操作（Server Actions）
- stores/<模块>.ts            该模块客户端状态
- types/<模块>.ts             该模块 TypeScript 类型
- lib/                        基础设施，只允许修改自己负责模块的部分

## actions、stores、types 目录说明

内容多时按职责拆子目录，通过 index.ts 统一导出。
引用时始终从 index.ts 层导入，不进入子文件内部。

例：
✓ import { createBatch } from '@/actions/production'
✗ import { createBatch } from '@/actions/production/batch'

## Server vs Client 组件规则

page.tsx 默认是 Server Component，不加 'use client'。
只有以下情况才加 'use client'：
- 用了 useState / useEffect / 事件处理器
- 用了浏览器 API
- 用了 Zustand store

Client 组件放在 components/<模块>/ 里，page.tsx 只负责拿数据然后传给 Client 组件。

正确写法：
\`\`\`tsx
// app/(dashboard)/production/page.tsx（Server Component）
export default async function Page() {
  const data = await fetch(`${process.env.API_BASE_URL}/production/batches`, {
    headers: { Authorization: `Bearer ${await getServerToken()}` },
    next: { revalidate: 60 }
  }).then(r => r.json())
  
  return <BatchTable initialData={data} />  // BatchTable 是 Client 组件
}
\`\`\`

## 模块边界规则（重要）

不允许跨模块直接 import 组件内部文件。
如果需要用其他模块的东西，只能从该模块的 index.ts 导入。

禁止：
\`\`\`ts
import { BatchForm } from '@/components/production/BatchForm'  // 进入了模块内部
\`\`\`

允许：
\`\`\`ts
import { BatchTable } from '@/components/production'  // 通过 index.ts
\`\`\`

## 写操作必须用 Server Actions

所有 POST/PUT/DELETE 操作写在 actions/ 目录，不要在 Client 组件里直接 fetch 写接口。

\`\`\`ts
// actions/production.ts
'use server'
export async function createBatch(data: CreateBatchInput) {
  const token = await getServerToken()
  const res = await fetch(`${process.env.API_BASE_URL}/production/batches`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  })
  if (!res.ok) throw new Error('创建批次失败')
  revalidatePath('/production')
}
\`\`\`

## 飞书集成
暂时为空

## 不允许修改的文件

以下文件只有架构负责人可以修改，如有需求提 PR 说明原因：
- src/middleware.ts
- src/app/layout.tsx
- src/components/shared/ 下所有文件
- src/hooks/usePermission.ts

## 命名规范

- 组件文件：PascalCase（BatchTable.tsx）
- 非组件文件：camelCase（useBatch.ts、batchApi.ts）
- 类型名：PascalCase（BatchStatus、CreateBatchInput）
- Server Action 函数：动词开头（createBatch、updateBatch、submitApproval）
- API 请求函数放在 lib/api/<模块>.ts，函数名以 fetch 开头（fetchBatches、fetchBatchById）

## 新增页面的步骤

1. 在 app/(dashboard)/<模块>/ 下新建目录和 page.tsx
2. page.tsx 里 fetch 数据，传给 components/<模块>/ 里的组件
3. 组件写在 components/<模块>/ 里，需要交互的加 'use client'
4. 如果有写操作，写在 actions/<模块>.ts 里
5. 类型定义更新到 types/<模块>.ts
6. 新增的对外组件记得在 components/<模块>/index.ts 里导出