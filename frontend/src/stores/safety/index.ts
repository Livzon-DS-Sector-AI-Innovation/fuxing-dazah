// Safety module stores — barrel re-exports
// All consumers import from '@/stores/safety'

'use client'

// 保留域的 zustand store（多数页面已迁 react-query，此处仅存仍被引用的）
export { useKnowledgeGraphStore } from './knowledgeGraphStore'
