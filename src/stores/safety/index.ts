'use client'

import { create } from 'zustand'
export { useWorkflowStore } from './workflowSlice'
import type { SafetyState } from './types'
import {
  initialCheckState,
  initialHazardState,
  initialAccidentState,
  initialTrainingState,
  initialRegulationState,
  initialRevisionState,
  initialAIWorkflowConfigState,
  initialPersonnelState,
  initialPermitState,
  initialArticleState,
  initialSpecialOpReportState,
  initialDailyRiskReportState,
  initialHazardIdentificationState,
  initialEhsChangeState,
  initialContractorState,
  initialOhHazardMonitorState,
  initialOhHealthExamState,
  initialScheduledTaskState,
} from './initialStates'

export const useSafetyStore = create<SafetyState>((set) => ({
  // Initial states
  ...initialCheckState,
  ...initialHazardState,
  ...initialAccidentState,
  ...initialTrainingState,
  ...initialRegulationState,
  ...initialRevisionState,
  ...initialAIWorkflowConfigState,
  ...initialPersonnelState,
  ...initialPermitState,
  ...initialArticleState,
  ...initialSpecialOpReportState,
  ...initialDailyRiskReportState,
  ...initialHazardIdentificationState,
  ...initialEhsChangeState,
  ...initialContractorState,
  ...initialOhHazardMonitorState,
  ...initialOhHealthExamState,
  ...initialScheduledTaskState,

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

  // ============ Regulation Actions ============
  setRegulations: (regulations) => set({ regulations }),
  setCurrentRegulation: (regulation) => set({ currentRegulation: regulation }),
  setRegulationQueryParams: (params) =>
    set((state) => ({ regulationQueryParams: { ...state.regulationQueryParams, ...params } })),
  setRegulationTotal: (total) => set({ regulationTotal: total }),
  setRegulationLoading: (loading) => set({ regulationLoading: loading }),

  addRegulation: (regulation) =>
    set((state) => ({ regulations: [regulation, ...state.regulations] })),

  updateRegulation: (id, updates) =>
    set((state) => ({
      regulations: state.regulations.map((r) => (r.id === id ? { ...r, ...updates } : r)),
      currentRegulation:
        state.currentRegulation?.id === id
          ? { ...state.currentRegulation, ...updates }
          : state.currentRegulation,
    })),

  removeRegulation: (id) =>
    set((state) => ({
      regulations: state.regulations.filter((r) => r.id !== id),
      currentRegulation: state.currentRegulation?.id === id ? null : state.currentRegulation,
    })),

  // ============ Revision Actions ============
  setRevisions: (revisions) => set({ revisions }),
  setCurrentRevision: (revision) => set({ currentRevision: revision }),
  setRevisionQueryParams: (params) =>
    set((state) => ({ revisionQueryParams: { ...state.revisionQueryParams, ...params } })),
  setRevisionTotal: (total) => set({ revisionTotal: total }),
  setRevisionLoading: (loading) => set({ revisionLoading: loading }),

  addRevision: (revision) =>
    set((state) => ({ revisions: [revision, ...state.revisions] })),

  updateRevision: (id, updates) =>
    set((state) => ({
      revisions: state.revisions.map((r) => (r.id === id ? { ...r, ...updates } : r)),
      currentRevision:
        state.currentRevision?.id === id
          ? { ...state.currentRevision, ...updates }
          : state.currentRevision,
    })),

  removeRevision: (id) =>
    set((state) => ({
      revisions: state.revisions.filter((r) => r.id !== id),
      currentRevision: state.currentRevision?.id === id ? null : state.currentRevision,
    })),

  // ============ AI Workflow Config Actions ============
  setAIWorkflowConfigs: (configs) => set({ aiWorkflowConfigs: configs }),
  setCurrentAIWorkflowConfig: (config) => set({ currentAIWorkflowConfig: config }),
  setAIWorkflowConfigQueryParams: (params) =>
    set((state) => ({
      aiWorkflowConfigQueryParams: { ...state.aiWorkflowConfigQueryParams, ...params },
    })),
  setAIWorkflowConfigTotal: (total) => set({ aiWorkflowConfigTotal: total }),
  setAIWorkflowConfigLoading: (loading) => set({ aiWorkflowConfigLoading: loading }),

  addAIWorkflowConfig: (config) =>
    set((state) => ({ aiWorkflowConfigs: [config, ...state.aiWorkflowConfigs] })),

  updateAIWorkflowConfig: (id, updates) =>
    set((state) => ({
      aiWorkflowConfigs: state.aiWorkflowConfigs.map((c) =>
        c.id === id ? { ...c, ...updates } : c
      ),
      currentAIWorkflowConfig:
        state.currentAIWorkflowConfig?.id === id
          ? { ...state.currentAIWorkflowConfig, ...updates }
          : state.currentAIWorkflowConfig,
    })),

  removeAIWorkflowConfig: (id) =>
    set((state) => ({
      aiWorkflowConfigs: state.aiWorkflowConfigs.filter((c) => c.id !== id),
      currentAIWorkflowConfig:
        state.currentAIWorkflowConfig?.id === id ? null : state.currentAIWorkflowConfig,
    })),

  // ============ Personnel Actions ============
  setPersonnel: (personnel) => set({ personnel }),
  setCurrentPersonnel: (p) => set({ currentPersonnel: p }),
  setPersonnelQueryParams: (params) =>
    set((state) => ({ personnelQueryParams: { ...state.personnelQueryParams, ...params } })),
  setPersonnelTotal: (total) => set({ personnelTotal: total }),
  setPersonnelLoading: (loading) => set({ personnelLoading: loading }),

  addPersonnel: (p) =>
    set((state) => ({ personnel: [p, ...state.personnel] })),

  updatePersonnel: (id, updates) =>
    set((state) => ({
      personnel: state.personnel.map((r) => (r.id === id ? { ...r, ...updates } : r)),
      currentPersonnel: state.currentPersonnel?.id === id ? { ...state.currentPersonnel, ...updates } : state.currentPersonnel,
    })),

  removePersonnel: (id) =>
    set((state) => ({
      personnel: state.personnel.filter((r) => r.id !== id),
      currentPersonnel: state.currentPersonnel?.id === id ? null : state.currentPersonnel,
    })),

  // ============ Permit Actions ============
  setPermits: (permits) => set({ permits }),
  setCurrentPermit: (p) => set({ currentPermit: p }),
  setPermitQueryParams: (params) =>
    set((state) => ({ permitQueryParams: { ...state.permitQueryParams, ...params } })),
  setPermitTotal: (total) => set({ permitTotal: total }),
  setPermitLoading: (loading) => set({ permitLoading: loading }),

  addPermit: (p) =>
    set((state) => ({ permits: [p, ...state.permits] })),

  updatePermit: (id, updates) =>
    set((state) => ({
      permits: state.permits.map((r) => (r.id === id ? { ...r, ...updates } : r)),
      currentPermit: state.currentPermit?.id === id ? { ...state.currentPermit, ...updates } : state.currentPermit,
    })),

  removePermit: (id) =>
    set((state) => ({
      permits: state.permits.filter((r) => r.id !== id),
      currentPermit: state.currentPermit?.id === id ? null : state.currentPermit,
    })),

  // ============ Knowledge Article Actions ============
  setArticles: (articles) => set({ articles }),
  setCurrentArticle: (a) => set({ currentArticle: a }),
  setArticleQueryParams: (params) =>
    set((state) => ({ articleQueryParams: { ...state.articleQueryParams, ...params } })),
  setArticleTotal: (total) => set({ articleTotal: total }),
  setArticleLoading: (loading) => set({ articleLoading: loading }),

  addArticle: (a) =>
    set((state) => ({ articles: [a, ...state.articles] })),

  updateArticle: (id, updates) =>
    set((state) => ({
      articles: state.articles.map((r) => (r.id === id ? { ...r, ...updates } : r)),
      currentArticle: state.currentArticle?.id === id ? { ...state.currentArticle, ...updates } : state.currentArticle,
    })),

  removeArticle: (id) =>
    set((state) => ({
      articles: state.articles.filter((r) => r.id !== id),
      currentArticle: state.currentArticle?.id === id ? null : state.currentArticle,
    })),

  // ============ Special Operation Report Actions ============
  setSpecialOpReports: (reports) => set({ specialOpReports: reports }),
  setCurrentSpecialOpReport: (r) => set({ currentSpecialOpReport: r }),
  setSpecialOpReportQueryParams: (params) =>
    set((state) => ({ specialOpReportQueryParams: { ...state.specialOpReportQueryParams, ...params } })),
  setSpecialOpReportTotal: (total) => set({ specialOpReportTotal: total }),
  setSpecialOpReportLoading: (loading) => set({ specialOpReportLoading: loading }),

  addSpecialOpReport: (r) =>
    set((state) => ({ specialOpReports: [r, ...state.specialOpReports] })),
  updateSpecialOpReport: (id, updates) =>
    set((state) => ({
      specialOpReports: state.specialOpReports.map((r) => (r.id === id ? { ...r, ...updates } : r)),
      currentSpecialOpReport: state.currentSpecialOpReport?.id === id ? { ...state.currentSpecialOpReport, ...updates } : state.currentSpecialOpReport,
    })),
  removeSpecialOpReport: (id) =>
    set((state) => ({
      specialOpReports: state.specialOpReports.filter((r) => r.id !== id),
      currentSpecialOpReport: state.currentSpecialOpReport?.id === id ? null : state.currentSpecialOpReport,
    })),

  // ============ Daily Risk Report Actions ============
  setDailyRiskReports: (reports) => set({ dailyRiskReports: reports }),
  setCurrentDailyRiskReport: (r) => set({ currentDailyRiskReport: r }),
  setDailyRiskReportQueryParams: (params) =>
    set((state) => ({ dailyRiskReportQueryParams: { ...state.dailyRiskReportQueryParams, ...params } })),
  setDailyRiskReportTotal: (total) => set({ dailyRiskReportTotal: total }),
  setDailyRiskReportLoading: (loading) => set({ dailyRiskReportLoading: loading }),

  addDailyRiskReport: (r) =>
    set((state) => ({ dailyRiskReports: [r, ...state.dailyRiskReports] })),
  updateDailyRiskReport: (id, updates) =>
    set((state) => ({
      dailyRiskReports: state.dailyRiskReports.map((r) => (r.id === id ? { ...r, ...updates } : r)),
      currentDailyRiskReport: state.currentDailyRiskReport?.id === id ? { ...state.currentDailyRiskReport, ...updates } : state.currentDailyRiskReport,
    })),
  removeDailyRiskReport: (id) =>
    set((state) => ({
      dailyRiskReports: state.dailyRiskReports.filter((r) => r.id !== id),
      currentDailyRiskReport: state.currentDailyRiskReport?.id === id ? null : state.currentDailyRiskReport,
    })),

  // ============ HazardIdentification Actions ============
  setHazardIdentifications: (items, total) =>
    set({ hazardIdentifications: items, hazardIdentificationTotal: total ?? items.length }),
  setCurrentHazardIdentification: (item) => set({ currentHazardIdentification: item }),
  setHazardIdentificationQueryParams: (params) =>
    set((state) => ({
      hazardIdentificationQueryParams: { ...state.hazardIdentificationQueryParams, ...params },
    })),
  setHazardIdentificationTotal: (total) => set({ hazardIdentificationTotal: total }),
  setHazardIdentificationLoading: (loading) => set({ hazardIdentificationLoading: loading }),
  addHazardIdentification: (item) =>
    set((state) => ({ hazardIdentifications: [item, ...state.hazardIdentifications] })),
  updateHazardIdentification: (id, data) =>
    set((state) => ({
      hazardIdentifications: state.hazardIdentifications.map((h) =>
        h.id === id ? { ...h, ...data } : h
      ),
      currentHazardIdentification:
        state.currentHazardIdentification?.id === id
          ? { ...state.currentHazardIdentification, ...data }
          : state.currentHazardIdentification,
    })),
  removeHazardIdentification: (id) =>
    set((state) => ({
      hazardIdentifications: state.hazardIdentifications.filter((h) => h.id !== id),
      currentHazardIdentification:
        state.currentHazardIdentification?.id === id ? null : state.currentHazardIdentification,
    })),

  // ============ EHS Change Actions ============
  setEhsChanges: (ehsChanges) => set({ ehsChanges }),
  setCurrentEhsChange: (currentEhsChange) => set({ currentEhsChange }),
  setEhsChangeQueryParams: (params) =>
    set((state) => ({ ehsChangeQueryParams: { ...state.ehsChangeQueryParams, ...params } })),
  setEhsChangeTotal: (ehsChangeTotal) => set({ ehsChangeTotal }),
  setEhsChangeLoading: (ehsChangeLoading) => set({ ehsChangeLoading }),
  addEhsChange: (c) =>
    set((state) => ({ ehsChanges: [c, ...state.ehsChanges] })),
  updateEhsChange: (id, updates) =>
    set((state) => ({
      ehsChanges: state.ehsChanges.map((c) => (c.id === id ? { ...c, ...updates } : c)),
      currentEhsChange: state.currentEhsChange?.id === id ? { ...state.currentEhsChange, ...updates } : state.currentEhsChange,
    })),
  removeEhsChange: (id) =>
    set((state) => ({
      ehsChanges: state.ehsChanges.filter((c) => c.id !== id),
      currentEhsChange: state.currentEhsChange?.id === id ? null : state.currentEhsChange,
    })),

  // ============ Contractor Actions ============
  setContractors: (contractors) => set({ contractors }),
  setCurrentContractor: (c) => set({ currentContractor: c }),
  setContractorQueryParams: (params) =>
    set((state) => ({ contractorQueryParams: { ...state.contractorQueryParams, ...params } })),
  setContractorTotal: (total) => set({ contractorTotal: total }),
  setContractorLoading: (loading) => set({ contractorLoading: loading }),
  addContractor: (c) =>
    set((state) => ({ contractors: [c, ...state.contractors] })),
  updateContractor: (id, updates) =>
    set((state) => ({
      contractors: state.contractors.map((c) => (c.id === id ? { ...c, ...updates } : c)),
      currentContractor: state.currentContractor?.id === id ? { ...state.currentContractor, ...updates } : state.currentContractor,
    })),
  removeContractor: (id) =>
    set((state) => ({
      contractors: state.contractors.filter((c) => c.id !== id),
      currentContractor: state.currentContractor?.id === id ? null : state.currentContractor,
    })),
  setContractorWorkRecords: (records) => set({ contractorWorkRecords: records }),

  // ============ OH Hazard Monitor Actions ============
  setOhHazardMonitors: (items) => set({ ohHazardMonitors: items }),
  setCurrentOhHazardMonitor: (item) => set({ currentOhHazardMonitor: item }),
  setOhHazardMonitorQueryParams: (params) =>
    set((state) => ({ ohHazardMonitorQueryParams: { ...state.ohHazardMonitorQueryParams, ...params } })),
  setOhHazardMonitorTotal: (total) => set({ ohHazardMonitorTotal: total }),
  setOhHazardMonitorLoading: (loading) => set({ ohHazardMonitorLoading: loading }),
  addOhHazardMonitor: (item) =>
    set((state) => ({ ohHazardMonitors: [item, ...state.ohHazardMonitors] })),
  updateOhHazardMonitor: (id, data) =>
    set((state) => ({
      ohHazardMonitors: state.ohHazardMonitors.map((m) => (m.id === id ? { ...m, ...data } : m)),
      currentOhHazardMonitor: state.currentOhHazardMonitor?.id === id ? { ...state.currentOhHazardMonitor, ...data } : state.currentOhHazardMonitor,
    })),
  removeOhHazardMonitor: (id) =>
    set((state) => ({
      ohHazardMonitors: state.ohHazardMonitors.filter((m) => m.id !== id),
      currentOhHazardMonitor: state.currentOhHazardMonitor?.id === id ? null : state.currentOhHazardMonitor,
    })),

  // ============ OH Health Exam Actions ============
  setOhHealthExams: (items) => set({ ohHealthExams: items }),
  setCurrentOhHealthExam: (item) => set({ currentOhHealthExam: item }),
  setOhHealthExamQueryParams: (params) =>
    set((state) => ({ ohHealthExamQueryParams: { ...state.ohHealthExamQueryParams, ...params } })),
  setOhHealthExamTotal: (total) => set({ ohHealthExamTotal: total }),
  setOhHealthExamLoading: (loading) => set({ ohHealthExamLoading: loading }),
  addOhHealthExam: (item) =>
    set((state) => ({ ohHealthExams: [item, ...state.ohHealthExams] })),
  updateOhHealthExam: (id, data) =>
    set((state) => ({
      ohHealthExams: state.ohHealthExams.map((e) => (e.id === id ? { ...e, ...data } : e)),
      currentOhHealthExam: state.currentOhHealthExam?.id === id ? { ...state.currentOhHealthExam, ...data } : state.currentOhHealthExam,
    })),
  removeOhHealthExam: (id) =>
    set((state) => ({
      ohHealthExams: state.ohHealthExams.filter((e) => e.id !== id),
      currentOhHealthExam: state.currentOhHealthExam?.id === id ? null : state.currentOhHealthExam,
    })),

  // ============ Scheduled Task Actions ============
  setScheduledTasks: (items, total) => set({ scheduledTasks: items, scheduledTaskTotal: total ?? items.length }),
  setCurrentScheduledTask: (item) => set({ currentScheduledTask: item }),
  setScheduledTaskQueryParams: (params) =>
    set((state) => ({ scheduledTaskQueryParams: { ...state.scheduledTaskQueryParams, ...params } })),
  setScheduledTaskTotal: (total) => set({ scheduledTaskTotal: total }),
  setScheduledTaskLoading: (loading) => set({ scheduledTaskLoading: loading }),
  addScheduledTask: (item) =>
    set((state) => ({ scheduledTasks: [item, ...state.scheduledTasks] })),
  updateScheduledTask: (id, data) =>
    set((state) => ({
      scheduledTasks: state.scheduledTasks.map((t) => (t.id === id ? { ...t, ...data } : t)),
      currentScheduledTask:
        state.currentScheduledTask?.id === id
          ? { ...state.currentScheduledTask, ...data }
          : state.currentScheduledTask,
    })),
  removeScheduledTask: (id) =>
    set((state) => ({
      scheduledTasks: state.scheduledTasks.filter((t) => t.id !== id),
    })),
  setScheduledTaskLogs: (logs) => set({ scheduledTaskLogs: logs }),
  setScheduledTaskLogsLoading: (loading) => set({ scheduledTaskLogsLoading: loading }),
  setDataSourceOptions: (options) => set({ dataSourceOptions: options }),
  setFeishuChats: (chats) => set({ feishuChats: chats }),

  // ============ Reset Actions ============
  resetCheckState: () => set(initialCheckState),
  resetHazardState: () => set(initialHazardState),
  resetAccidentState: () => set(initialAccidentState),
  resetTrainingState: () => set(initialTrainingState),
  resetRegulationState: () => set(initialRegulationState),
  resetRevisionState: () => set(initialRevisionState),
  resetAIWorkflowConfigState: () => set(initialAIWorkflowConfigState),
  resetPersonnelState: () => set(initialPersonnelState),
  resetPermitState: () => set(initialPermitState),
  resetArticleState: () => set(initialArticleState),
  resetSpecialOpReportState: () => set(initialSpecialOpReportState),
  resetDailyRiskReportState: () => set(initialDailyRiskReportState),
  resetEhsChangeState: () => set(initialEhsChangeState),
  resetContractorState: () => set(initialContractorState),
  resetHazardIdentificationState: () => set(initialHazardIdentificationState),
  resetOhHazardMonitorState: () => set(initialOhHazardMonitorState),
  resetOhHealthExamState: () => set(initialOhHealthExamState),
  resetScheduledTaskState: () => set(initialScheduledTaskState),

  resetAll: () =>
    set({
      ...initialCheckState,
      ...initialHazardState,
      ...initialAccidentState,
      ...initialTrainingState,
      ...initialRegulationState,
      ...initialRevisionState,
      ...initialAIWorkflowConfigState,
      ...initialPersonnelState,
      ...initialPermitState,
      ...initialArticleState,
      ...initialSpecialOpReportState,
      ...initialDailyRiskReportState,
      ...initialHazardIdentificationState,
      ...initialEhsChangeState,
      ...initialContractorState,
      ...initialOhHazardMonitorState,
      ...initialOhHealthExamState,
      ...initialScheduledTaskState,
    }),
}))
