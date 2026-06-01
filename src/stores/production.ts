import { create } from 'zustand'
import type {
  Batch,
  BatchMaterial,
  ProductionPlan,
  PlanTask,
  ProcessSpec,
  ProcessStep,
  ProcessParameter,
  ProductionRecord,
  MaterialBalance,
  BatchQueryParams,
  PlanQueryParams,
  ProcessSpecQueryParams,
} from '@/types/production'

// ============ Store State Types ============

interface ProductionState {
  // Batch state
  batches: Batch[]
  currentBatch: Batch | null
  batchMaterials: BatchMaterial[]
  batchQueryParams: BatchQueryParams
  batchTotal: number
  batchLoading: boolean

  // Plan state
  plans: ProductionPlan[]
  currentPlan: ProductionPlan | null
  planTasks: PlanTask[]
  planQueryParams: PlanQueryParams
  planTotal: number
  planLoading: boolean

  // Process Spec state
  processSpecs: ProcessSpec[]
  currentProcessSpec: ProcessSpec | null
  processSteps: ProcessStep[]
  processParameters: ProcessParameter[]
  processSpecQueryParams: ProcessSpecQueryParams
  processSpecTotal: number
  processSpecLoading: boolean

  // Production Record state
  productionRecords: ProductionRecord[]
  productionRecordLoading: boolean

  // Material Balance state
  materialBalance: MaterialBalance | null
  materialBalanceLoading: boolean

  // Actions
  // Batch actions
  setBatches: (batches: Batch[]) => void
  setCurrentBatch: (batch: Batch | null) => void
  setBatchMaterials: (materials: BatchMaterial[]) => void
  setBatchQueryParams: (params: Partial<BatchQueryParams>) => void
  setBatchTotal: (total: number) => void
  setBatchLoading: (loading: boolean) => void
  addBatch: (batch: Batch) => void
  updateBatch: (id: string, batch: Partial<Batch>) => void
  removeBatch: (id: string) => void

  // Plan actions
  setPlans: (plans: ProductionPlan[]) => void
  setCurrentPlan: (plan: ProductionPlan | null) => void
  setPlanTasks: (tasks: PlanTask[]) => void
  setPlanQueryParams: (params: Partial<PlanQueryParams>) => void
  setPlanTotal: (total: number) => void
  setPlanLoading: (loading: boolean) => void
  addPlan: (plan: ProductionPlan) => void
  updatePlan: (id: string, plan: Partial<ProductionPlan>) => void
  removePlan: (id: string) => void

  // Process Spec actions
  setProcessSpecs: (specs: ProcessSpec[]) => void
  setCurrentProcessSpec: (spec: ProcessSpec | null) => void
  setProcessSteps: (steps: ProcessStep[]) => void
  setProcessParameters: (params: ProcessParameter[]) => void
  setProcessSpecQueryParams: (params: Partial<ProcessSpecQueryParams>) => void
  setProcessSpecTotal: (total: number) => void
  setProcessSpecLoading: (loading: boolean) => void
  addProcessSpec: (spec: ProcessSpec) => void
  updateProcessSpec: (id: string, spec: Partial<ProcessSpec>) => void
  removeProcessSpec: (id: string) => void

  // Production Record actions
  setProductionRecords: (records: ProductionRecord[]) => void
  setProductionRecordLoading: (loading: boolean) => void
  addProductionRecord: (record: ProductionRecord) => void

  // Material Balance actions
  setMaterialBalance: (balance: MaterialBalance | null) => void
  setMaterialBalanceLoading: (loading: boolean) => void

  // Reset actions
  resetBatchState: () => void
  resetPlanState: () => void
  resetProcessSpecState: () => void
  resetProductionRecordState: () => void
  resetMaterialBalanceState: () => void
  resetAll: () => void
}

const initialBatchState = {
  batches: [] as Batch[],
  currentBatch: null,
  batchMaterials: [] as BatchMaterial[],
  batchQueryParams: { page: 1, page_size: 20 } as BatchQueryParams,
  batchTotal: 0,
  batchLoading: false,
}

const initialPlanState = {
  plans: [] as ProductionPlan[],
  currentPlan: null,
  planTasks: [] as PlanTask[],
  planQueryParams: { page: 1, page_size: 20 } as PlanQueryParams,
  planTotal: 0,
  planLoading: false,
}

const initialProcessSpecState = {
  processSpecs: [] as ProcessSpec[],
  currentProcessSpec: null,
  processSteps: [] as ProcessStep[],
  processParameters: [] as ProcessParameter[],
  processSpecQueryParams: { page: 1, page_size: 20 } as ProcessSpecQueryParams,
  processSpecTotal: 0,
  processSpecLoading: false,
}

const initialProductionRecordState = {
  productionRecords: [] as ProductionRecord[],
  productionRecordLoading: false,
}

const initialMaterialBalanceState = {
  materialBalance: null as MaterialBalance | null,
  materialBalanceLoading: false,
}

export const useProductionStore = create<ProductionState>((set) => ({
  // Initial Batch state
  ...initialBatchState,

  // Initial Plan state
  ...initialPlanState,

  // Initial Process Spec state
  ...initialProcessSpecState,

  // Initial Production Record state
  ...initialProductionRecordState,

  // Initial Material Balance state
  ...initialMaterialBalanceState,

  // ============ Batch Actions ============
  setBatches: (batches) => set({ batches }),
  setCurrentBatch: (batch) => set({ currentBatch: batch }),
  setBatchMaterials: (materials) => set({ batchMaterials: materials }),
  setBatchQueryParams: (params) =>
    set((state) => ({ batchQueryParams: { ...state.batchQueryParams, ...params } })),
  setBatchTotal: (total) => set({ batchTotal: total }),
  setBatchLoading: (loading) => set({ batchLoading: loading }),

  addBatch: (batch) =>
    set((state) => ({ batches: [batch, ...state.batches] })),

  updateBatch: (id, updates) =>
    set((state) => ({
      batches: state.batches.map((b) => (b.id === id ? { ...b, ...updates } : b)),
      currentBatch: state.currentBatch?.id === id ? { ...state.currentBatch, ...updates } : state.currentBatch,
    })),

  removeBatch: (id) =>
    set((state) => ({
      batches: state.batches.filter((b) => b.id !== id),
      currentBatch: state.currentBatch?.id === id ? null : state.currentBatch,
    })),

  // ============ Plan Actions ============
  setPlans: (plans) => set({ plans }),
  setCurrentPlan: (plan) => set({ currentPlan: plan }),
  setPlanTasks: (tasks) => set({ planTasks: tasks }),
  setPlanQueryParams: (params) =>
    set((state) => ({ planQueryParams: { ...state.planQueryParams, ...params } })),
  setPlanTotal: (total) => set({ planTotal: total }),
  setPlanLoading: (loading) => set({ planLoading: loading }),

  addPlan: (plan) =>
    set((state) => ({ plans: [plan, ...state.plans] })),

  updatePlan: (id, updates) =>
    set((state) => ({
      plans: state.plans.map((p) => (p.id === id ? { ...p, ...updates } : p)),
      currentPlan: state.currentPlan?.id === id ? { ...state.currentPlan, ...updates } : state.currentPlan,
    })),

  removePlan: (id) =>
    set((state) => ({
      plans: state.plans.filter((p) => p.id !== id),
      currentPlan: state.currentPlan?.id === id ? null : state.currentPlan,
    })),

  // ============ Process Spec Actions ============
  setProcessSpecs: (specs) => set({ processSpecs: specs }),
  setCurrentProcessSpec: (spec) => set({ currentProcessSpec: spec }),
  setProcessSteps: (steps) => set({ processSteps: steps }),
  setProcessParameters: (params) => set({ processParameters: params }),
  setProcessSpecQueryParams: (params) =>
    set((state) => ({ processSpecQueryParams: { ...state.processSpecQueryParams, ...params } })),
  setProcessSpecTotal: (total) => set({ processSpecTotal: total }),
  setProcessSpecLoading: (loading) => set({ processSpecLoading: loading }),

  addProcessSpec: (spec) =>
    set((state) => ({ processSpecs: [spec, ...state.processSpecs] })),

  updateProcessSpec: (id, updates) =>
    set((state) => ({
      processSpecs: state.processSpecs.map((s) => (s.id === id ? { ...s, ...updates } : s)),
      currentProcessSpec: state.currentProcessSpec?.id === id ? { ...state.currentProcessSpec, ...updates } : state.currentProcessSpec,
    })),

  removeProcessSpec: (id) =>
    set((state) => ({
      processSpecs: state.processSpecs.filter((s) => s.id !== id),
      currentProcessSpec: state.currentProcessSpec?.id === id ? null : state.currentProcessSpec,
    })),

  // ============ Production Record Actions ============
  setProductionRecords: (records) => set({ productionRecords: records }),
  setProductionRecordLoading: (loading) => set({ productionRecordLoading: loading }),

  addProductionRecord: (record) =>
    set((state) => ({ productionRecords: [record, ...state.productionRecords] })),

  // ============ Material Balance Actions ============
  setMaterialBalance: (balance) => set({ materialBalance: balance }),
  setMaterialBalanceLoading: (loading) => set({ materialBalanceLoading: loading }),

  // ============ Reset Actions ============
  resetBatchState: () => set(initialBatchState),
  resetPlanState: () => set(initialPlanState),
  resetProcessSpecState: () => set(initialProcessSpecState),
  resetProductionRecordState: () => set(initialProductionRecordState),
  resetMaterialBalanceState: () => set(initialMaterialBalanceState),

  resetAll: () =>
    set({
      ...initialBatchState,
      ...initialPlanState,
      ...initialProcessSpecState,
      ...initialProductionRecordState,
      ...initialMaterialBalanceState,
    }),
}))