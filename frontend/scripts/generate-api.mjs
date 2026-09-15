// OpenAPI -> TypeScript 类型生成
// 数据源优先级：backend/openapi.json（后端导出物）> frontend/openapi.json（提交快照）> 在线 /openapi.json
// 产物：src/types/generated/schema.ts（新代码一律从此导入契约类型）
import { existsSync } from 'node:fs'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import openapiTS, { astToString } from 'openapi-typescript'

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')

const candidates = [
  path.resolve(frontendRoot, '..', 'backend', 'openapi.json'),
  path.resolve(frontendRoot, 'openapi.json'),
]

let spec = null
let source = ''
for (const p of candidates) {
  if (existsSync(p)) {
    spec = JSON.parse(await readFile(p, 'utf8'))
    source = p
    break
  }
}

if (!spec) {
  const base = process.env.API_BASE_URL || 'http://localhost:8000'
  const res = await fetch(`${base}/openapi.json`)
  if (!res.ok) {
    throw new Error(`fetch openapi.json failed: ${res.status} from ${base}`)
  }
  spec = await res.json()
  source = base
}

const ast = await openapiTS(spec)
const output = astToString(ast)

const outDir = path.resolve(frontendRoot, 'src', 'types', 'generated')
await mkdir(outDir, { recursive: true })
const outFile = path.join(outDir, 'schema.ts')
await writeFile(outFile, output)

console.log(`[generate-api] source: ${source}`)
console.log(`[generate-api] written: ${outFile} (${output.length} bytes)`)
