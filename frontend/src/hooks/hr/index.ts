// 人事模块数据 hooks：统一请求加载与竞态防护范式，组件不再各自手写
// useState+useCallback+useEffect 三件套。

export { useEmployeeList, type EmployeeListQuery } from './useEmployeeList'
export { useHrDepartments } from './useHrDepartments'
export { useHrPositions } from './useHrPositions'
export { useHrFilterOptions } from './useHrFilterOptions'
