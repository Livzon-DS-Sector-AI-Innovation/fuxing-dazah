import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import PushTasksTab from './PushTasksTab'
import { renderWithQuery } from '@/test/utils'
import type { WarehousePushTaskView } from '@/types/warehouse'
vi.mock('@/actions/warehouse', () => ({
  getWarehousePushTasks: vi.fn(),
  updateWarehousePushTask: vi.fn(),
  triggerWarehousePushTask: vi.fn(),
  getWarehouseConfigAudits: vi.fn().mockResolvedValue([]),
  getWarehousePushLogs: vi.fn().mockResolvedValue({ items: [], total: 0, page: 1, page_size: 50 }),
}))

import {
  getWarehousePushTasks,
  triggerWarehousePushTask,
  updateWarehousePushTask,
} from '@/actions/warehouse'

const mockedList = vi.mocked(getWarehousePushTasks)
const mockedUpdate = vi.mocked(updateWarehousePushTask)
const mockedTrigger = vi.mocked(triggerWarehousePushTask)

const task = (over: Partial<WarehousePushTaskView>): WarehousePushTaskView => ({
  task_name: over.task_name ?? 'morning_report',
  scene: over.task_name ?? 'morning_report',
  label: over.label ?? '晨报推送',
  description: over.description ?? '每日 08:00 推送昨日出入库汇总',
  trigger: over.trigger ?? 'scheduled',
  enabled: over.enabled ?? true,
  schedule: over.schedule === undefined ? { type: 'daily', time: '08:00' } : over.schedule,
  targets: over.targets ?? ['oc_test'],
  source: over.source ?? 'db',
})

beforeEach(() => {
  vi.clearAllMocks()
  mockedList.mockResolvedValue({
    tasks: [
      task({}),
      task({
        task_name: 'express_notify',
        label: '快递发货通知',
        description: '成品出库确认后自动推送',
        trigger: 'event',
        schedule: null,
        enabled: false,
        targets: [],
      }),
    ],
  })
})

describe('PushTasksTab', () => {
  it('渲染任务行（含频率与目标回显）', async () => {
    renderWithQuery(<PushTasksTab canUpdate />)
    expect(await screen.findByTestId('wh-push-row-morning_report')).toBeTruthy()
    expect(screen.getByText('晨报推送')).toBeTruthy()
    expect(screen.getByText('频率：每日 08:00')).toBeTruthy()
    expect(screen.getByText(/当前生效：oc_test/)).toBeTruthy()
    expect(screen.getByTestId('wh-push-row-express_notify')).toBeTruthy()
    expect(screen.getByText('频率：事件触发')).toBeTruthy()
  })

  it('启停切换即时 PUT 并刷新审计', async () => {
    const user = userEvent.setup()
    mockedUpdate.mockResolvedValue(task({ enabled: false }))
    renderWithQuery(<PushTasksTab canUpdate />)

    const switches = await screen.findAllByRole('switch')
    await user.click(switches[0])

    await waitFor(() => {
      expect(mockedUpdate).toHaveBeenCalledWith('morning_report', { enabled: false })
    })
  })

  it('目标列表编辑保存（空串转 null=清空覆盖）', async () => {
    const user = userEvent.setup()
    mockedUpdate.mockResolvedValue(task({ targets: ['oc_a', 'ou_b'] }))
    renderWithQuery(<PushTasksTab canUpdate />)

    const input = await screen.findByTestId('wh-push-target-morning_report')
    const textbox = input.querySelector('input')
    expect(textbox).toBeTruthy()
    await user.clear(textbox as HTMLInputElement)
    await user.type(textbox as HTMLInputElement, 'oc_a,ou_b{Enter}')

    await waitFor(() => {
      expect(mockedUpdate).toHaveBeenCalledWith('morning_report', {
        targets: 'oc_a,ou_b',
      })
    })
  })

  it('手动触发调用 action 并反馈执行结果', async () => {
    const user = userEvent.setup()
    mockedTrigger.mockResolvedValue({
      task_name: 'morning_report',
      scene: 'morning_report',
      status: 'executed',
      slot: null,
      log_count: 1,
    })
    renderWithQuery(<PushTasksTab canUpdate />)

    await screen.findByTestId('wh-push-row-morning_report')
    await user.click(screen.getByTestId('wh-push-trigger-morning_report'))

    await waitFor(() => {
      expect(mockedTrigger).toHaveBeenCalledWith('morning_report', false)
    })
    await waitFor(() => {
      expect(screen.getByText(/推送已执行/)).toBeTruthy()
    })
  })

  it('演练勾选后触发传 dry_run=true', async () => {
    const user = userEvent.setup()
    mockedTrigger.mockResolvedValue({
      task_name: 'morning_report',
      scene: 'morning_report',
      status: 'executed',
      slot: null,
      log_count: 1,
    })
    renderWithQuery(<PushTasksTab canUpdate />)

    await screen.findByTestId('wh-push-row-morning_report')
    const checkboxes = screen.getAllByRole('checkbox')
    await user.click(checkboxes[0])
    await user.click(screen.getByTestId('wh-push-trigger-morning_report'))

    await waitFor(() => {
      expect(mockedTrigger).toHaveBeenCalledWith('morning_report', true)
    })
  })

  it('只读模式：开关与输入禁用', async () => {
    renderWithQuery(<PushTasksTab canUpdate={false} />)
    await screen.findByTestId('wh-push-row-morning_report')
    const switches = screen.getAllByRole('switch')
    expect(switches.every(s => (s as HTMLElement).classList.contains('ant-switch-disabled'))).toBe(true)
    const trigger = screen.getByTestId('wh-push-trigger-morning_report')
    expect(trigger).toHaveProperty('disabled', true)
  })
})
