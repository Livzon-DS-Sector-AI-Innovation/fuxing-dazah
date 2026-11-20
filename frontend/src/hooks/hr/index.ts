// 人事模块数据 hooks：统一请求加载与竞态防护范式，组件不再各自手写
// useState+useCallback+useEffect 三件套。
// useDebounce 原在 hooks/ 根下，消费方全为 HR 组件，收敛入模块目录（review 意见）。

export { useEmployeeList, type EmployeeListQuery } from './useEmployeeList'
export { useHrDepartments } from './useHrDepartments'
export { useHrPositions } from './useHrPositions'
export { useHrFilterOptions } from './useHrFilterOptions'
export { useDebounce, useDebouncedCallback } from './useDebounce'
