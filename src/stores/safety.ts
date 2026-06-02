import { create } from 'zustand'
import type {
  Accident,
  AccidentQueryParams,
  HazardReport,
  HazardReportQueryParams,
  SafetyCheck,
  SafetyCheckQueryParams,
  SafetyTraining,
  SafetyTrainingQueryParams,
  TrainingRecord,
} from '@/types/safety'

// ============ Store State Types ============

interface SafetyState {
  // Check state
  checks: SafetyCheck[]
  currentCheck: SafetyCheck | null
  checkQueryParams: SafetyCheckQueryParams
  checkTotal: number
  checkLoading: boolean

  // Hazard state
  hazards: HazardReport[]
  currentHazard: HazardReport | null
  hazardQueryParams: HazardReportQueryParams
  hazardTotal: number
  hazardLoading: boolean

  // Accident state
  accidents: Accident[]
  currentAccident: Accident | null
  accidentQueryParams: AccidentQueryParams
  accidentTotal: number
  accidentLoading: boolean

  // Training state
  trainings: SafetyTraining[]
  currentTraining: SafetyTraining | null
  trainingRecords: TrainingRecord[]
  trainingQueryParams: SafetyTrainingQueryParams
  trainingTotal: number
  trainingLoading: boolean

  // Actions - Check
  setChecks: (checks: SafetyCheck[]) => void
  setCurrentCheck: (check: SafetyCheck | null) => void
  setCheckQueryParams: (params: Partial<SafetyCheckQueryParams>) => void
  setCheckTotal: (total: number) => void
  setCheckLoading: (loading: boolean) => void
  addCheck: (check: SafetyCheck) => void
  updateCheck: (id: string, check: Partial<SafetyCheck>) => void
  removeCheck: (id: string) => void

  // Actions - Hazard
  setHazards: (hazards: HazardReport[]) => void
  setCurrentHazard: (hazard: HazardReport | null) => void
  setHazardQueryParams: (params: Partial<HazardReportQueryParams>) => void
  setHazardTotal: (total: number) => void
  setHazardLoading: (loading: boolean) => void
  addHazard: (hazard: HazardReport) => void
  updateHazard: (id: string, hazard: Partial<HazardReport>) => void
  removeHazard: (id: string) => void

  // Actions - Accident
  setAccidents: (accidents: Accident[]) => void
  setCurrentAccident: (accident: Accident | null) => void
  setAccidentQueryParams: (params: Partial<AccidentQueryParams>) => void
  setAccidentTotal: (total: number) => void
  setAccidentLoading: (loading: boolean) => void
  addAccident: (accident: Accident) => void
  updateAccident: (id: string, accident: Partial<Accident>) => void
  removeAccident: (id: string) => void

  // Actions - Training
  setTrainings: (trainings: SafetyTraining[]) => void
  setCurrentTraining: (training: SafetyTraining | null) => void
  setTrainingRecords: (records: TrainingRecord[]) => void
  setTrainingQueryParams: (params: Partial<SafetyTrainingQueryParams>) => void
  setTrainingTotal: (total: number) => void
  setTrainingLoading: (loading: boolean) => void
  addTraining: (training: SafetyTraining) => void
  updateTraining: (id: string, training: Partial<SafetyTraining>) => void
  removeTraining: (id: string) => void

  // Actions - Reset
  resetCheckState: () => void
  resetHazardState: () => void
  resetAccidentState: () => void
  resetTrainingState: () => void
  resetAll: () => void
}

const initialCheckState = {
  checks: [] as SafetyCheck[],
  currentCheck: null,
  checkQueryParams: { page: 1, page_size: 20 } as SafetyCheckQueryParams,
  checkTotal: 0,
  checkLoading: false,
}

const initialHazardState = {
  hazards: [] as HazardReport[],
  currentHazard: null,
  hazardQueryParams: { page: 1, page_size: 20 } as HazardReportQueryParams,
  hazardTotal: 0,
  hazardLoading: false,
}

const initialAccidentState = {
  accidents: [] as Accident[],
  currentAccident: null,
  accidentQueryParams: { page: 1, page_size: 20 } as AccidentQueryParams,
  accidentTotal: 0,
  accidentLoading: false,
}

const initialTrainingState = {
  trainings: [] as SafetyTraining[],
  currentTraining: null,
  trainingRecords: [] as TrainingRecord[],
  trainingQueryParams: { page: 1, page_size: 20 } as SafetyTrainingQueryParams,
  trainingTotal: 0,
  trainingLoading: false,
}

export const useSafetyStore = create<SafetyState>((set) => ({
  // Initial states
  ...initialCheckState,
  ...initialHazardState,
  ...initialAccidentState,
  ...initialTrainingState,

  // ============ Check Actions ============
  setChecks: (checks) => set({ checks }),
  setCurrentCheck: (check) => set({ currentCheck: check }),
  setCheckQueryParams: (params) =>
    set((state) => ({ checkQueryParams: { ...state.checkQueryParams, ...params } })),
  setCheckTotal: (total) => set({ checkTotal: total }),
  setCheckLoading: (loading) => set({ checkLoading: loading }),

  addCheck: (check) =>
    set((state) => ({ checks: [check, ...state.checks] })),

  updateCheck: (id, updates) =>
    set((state) => ({
      checks: state.checks.map((c) => (c.id === id ? { ...c, ...updates } : c)),
      currentCheck: state.currentCheck?.id === id ? { ...state.currentCheck, ...updates } : state.currentCheck,
    })),

  removeCheck: (id) =>
    set((state) => ({
      checks: state.checks.filter((c) => c.id !== id),
      currentCheck: state.currentCheck?.id === id ? null : state.currentCheck,
    })),

  // ============ Hazard Actions ============
  setHazards: (hazards) => set({ hazards }),
  setCurrentHazard: (hazard) => set({ currentHazard: hazard }),
  setHazardQueryParams: (params) =>
    set((state) => ({ hazardQueryParams: { ...state.hazardQueryParams, ...params } })),
  setHazardTotal: (total) => set({ hazardTotal: total }),
  setHazardLoading: (loading) => set({ hazardLoading: loading }),

  addHazard: (hazard) =>
    set((state) => ({ hazards: [hazard, ...state.hazards] })),

  updateHazard: (id, updates) =>
    set((state) => ({
      hazards: state.hazards.map((h) => (h.id === id ? { ...h, ...updates } : h)),
      currentHazard: state.currentHazard?.id === id ? { ...state.currentHazard, ...updates } : state.currentHazard,
    })),

  removeHazard: (id) =>
    set((state) => ({
      hazards: state.hazards.filter((h) => h.id !== id),
      currentHazard: state.currentHazard?.id === id ? null : state.currentHazard,
    })),

  // ============ Accident Actions ============
  setAccidents: (accidents) => set({ accidents }),
  setCurrentAccident: (accident) => set({ currentAccident: accident }),
  setAccidentQueryParams: (params) =>
    set((state) => ({ accidentQueryParams: { ...state.accidentQueryParams, ...params } })),
  setAccidentTotal: (total) => set({ accidentTotal: total }),
  setAccidentLoading: (loading) => set({ accidentLoading: loading }),

  addAccident: (accident) =>
    set((state) => ({ accidents: [accident, ...state.accidents] })),

  updateAccident: (id, updates) =>
    set((state) => ({
      accidents: state.accidents.map((a) => (a.id === id ? { ...a, ...updates } : a)),
      currentAccident: state.currentAccident?.id === id ? { ...state.currentAccident, ...updates } : state.currentAccident,
    })),

  removeAccident: (id) =>
    set((state) => ({
      accidents: state.accidents.filter((a) => a.id !== id),
      currentAccident: state.currentAccident?.id === id ? null : state.currentAccident,
    })),

  // ============ Training Actions ============
  setTrainings: (trainings) => set({ trainings }),
  setCurrentTraining: (training) => set({ currentTraining: training }),
  setTrainingRecords: (records) => set({ trainingRecords: records }),
  setTrainingQueryParams: (params) =>
    set((state) => ({ trainingQueryParams: { ...state.trainingQueryParams, ...params } })),
  setTrainingTotal: (total) => set({ trainingTotal: total }),
  setTrainingLoading: (loading) => set({ trainingLoading: loading }),

  addTraining: (training) =>
    set((state) => ({ trainings: [training, ...state.trainings] })),

  updateTraining: (id, updates) =>
    set((state) => ({
      trainings: state.trainings.map((t) => (t.id === id ? { ...t, ...updates } : t)),
      currentTraining: state.currentTraining?.id === id ? { ...state.currentTraining, ...updates } : state.currentTraining,
    })),

  removeTraining: (id) =>
    set((state) => ({
      trainings: state.trainings.filter((t) => t.id !== id),
      currentTraining: state.currentTraining?.id === id ? null : state.currentTraining,
    })),

  // ============ Reset Actions ============
  resetCheckState: () => set(initialCheckState),
  resetHazardState: () => set(initialHazardState),
  resetAccidentState: () => set(initialAccidentState),
  resetTrainingState: () => set(initialTrainingState),

  resetAll: () =>
    set({
      ...initialCheckState,
      ...initialHazardState,
      ...initialAccidentState,
      ...initialTrainingState,
    }),
}))
