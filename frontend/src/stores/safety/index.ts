// Safety module stores — barrel re-exports
// All consumers import from '@/stores/safety'

'use client'

// ============================================================
// Per-domain stores (NEW — prefer these for new code)
// ============================================================
export { useHazardStore } from './hazardStore'
export { useTrainingStore } from './trainingStore'
export { useRegulationStore } from './regulationStore'
export { useRevisionStore } from './revisionStore'
export { useSpecialOpsPersonnelStore } from './specialOpsPersonnelStore'
export { useSpecialOpsPermitStore } from './specialOpsPermitStore'
export { useKnowledgeStore } from './knowledgeStore'
export { useSpecialOpReportStore } from './specialOpReportStore'
export { useHazardIdentificationStore } from './hazardIdentificationStore'
export { useEhsChangeStore } from './ehsChangeStore'
export { useContractorStore } from './contractorStore'

// ============================================================
// Legacy monolithic store (backward compatibility)
// ============================================================
export { useSafetyStore } from './deprecatedStore'
export type { SafetyState } from './types'
