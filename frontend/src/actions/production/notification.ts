'use server'

import { revalidatePath } from 'next/cache'
import { API_BASE, actionFetch, type ActionResult } from './helpers'
import type {
  NotificationConfigUpdateInput,
  ProductionNotificationConfig,
} from '@/types/production'

const BASE = `${API_BASE}/production`
const CONFIG_PATH = '/production/notification-config'

export async function fetchNotificationConfigs(): Promise<
  ActionResult<ProductionNotificationConfig[]>
> {
  return actionFetch<ProductionNotificationConfig[]>(
    `${BASE}/notification-configs`,
  )
}

export async function updateNotificationConfig(
  notifyType: string,
  input: NotificationConfigUpdateInput,
): Promise<ActionResult<ProductionNotificationConfig>> {
  const result = await actionFetch<ProductionNotificationConfig>(
    `${BASE}/notification-configs/${encodeURIComponent(notifyType)}`,
    {
      method: 'PUT',
      body: JSON.stringify(input),
    },
  )
  if (result.success) revalidatePath(CONFIG_PATH)
  return result
}
