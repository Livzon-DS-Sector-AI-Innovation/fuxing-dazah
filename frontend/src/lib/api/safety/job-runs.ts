/**
 * 定时任务运行历史（Agent 任务运行中心，3.0 四期 1-D）。
 *
 * 后端 safety.scheduler_task_run_log（append-only）：调度器每次尝试落一行
 * （成功/失败/超时 + 耗时 + 错误摘要）。去重/重试/告警仍走 scheduler_job_runs。
 */
import { apiGet, API_BASE_URL } from '@/lib/http-client'

export interface TaskRunRecord {
  job_name: string
  started_at: string | null
  finished_at: string | null
  status: 'success' | 'failed' | 'no_source'
  duration_ms: number | null
  error: string | null
}

export interface JobRunItem {
  job_name: string
  description: string | null
  schedule_text: string
  enabled: boolean
  last_run: TaskRunRecord | null
}

export interface JobRunsData {
  /** 任务全集（含从未运行，last_run=null） */
  jobs: JobRunItem[]
  /** 全局最近 N 条运行历史（时间倒序） */
  recent: TaskRunRecord[]
}

export async function fetchSchedulerJobRuns(recentLimit = 100): Promise<JobRunsData> {
  return apiGet(
    `${API_BASE_URL}/api/v1/safety/scheduler-config/job-runs?recent_limit=${recentLimit}`,
  )
}
